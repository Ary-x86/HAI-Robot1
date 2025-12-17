# robot/robot_brain.py
#
# High-level idea (architecture):
# - We run TWO loops in parallel:
#   1) game_loop(): polls your backend (/state) every ~0.5s to detect new turns, mood, game_over, etc.
#      It drives "midgame" reactions (taunts + optional behaviors) and the long "game over" routine.
#   2) listen_loop(): continuously listens to the microphone, transcribes speech, and decides whether
#      to respond via LLM, do a special "blowout interrupt", or handle rematch YES/NO.
#
# Why two loops?
# - The game state changes due to moves and backend logic; polling is easy and robust.
# - Speech is event-driven (whenever the user talks); mixing that into the polling loop gets messy.
#
# Why this code feels more "human-like" / "natural":
# - The robot has state-dependent mood (winning / losing / close) that changes how often it talks,
#   how often it moves, and which kinds of sounds it plays.
# - It has "opening hype": it talks a LOT at the beginning of the game, then gradually calms down.
# - It has "bored/idle" behavior and "wait SFX" timers that trigger if the human stalls.
# - It has rare "blowout interrupts": if it's winning/losing by a lot, it sometimes refuses to
#   respond normally ("I'm trying to focus") and ignores what the user said, like a real competitor.
# - It has cooldowns to avoid spam (SFX cooldown, behavior cooldown).
#
# Important fix included in this version:
# - HARD REMATCH HANDLER (race-condition fix):
#   Sometimes the user says "yes" right as the game ends. If the backend already says game_over=True
#   but our game_loop hasn't processed that state yet, rematch_mode might still be False.
#   That creates a race: the message goes to "gameplay" LLM instead of "rematch", so no reset happens.
#   The fix: if the backend says game_over=True, we handle yes/no DIRECTLY in listen_loop (no LLM),
#   and we force rematch_mode = True there. That makes rematch 100% reliable even if the user speaks
#   during the ending sequence.

import os
import sys
import json
import time
import random
import requests
import signal
import threading
import speech_recognition as sr
from dotenv import load_dotenv

# Twisted (WAMP engine)
# - Autobahn + Twisted gives you a WAMP client that can call robot APIs safely.
# - Note: listen_loop runs in a background thread, so it must use reactor.callFromThread
#   when making WAMP calls.
from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from twisted.internet import threads, reactor
from autobahn.twisted.util import sleep as tSleep

import audioop  # built-in: lets us compute RMS loudness from raw PCM bytes

# OpenAI
from openai import OpenAI

load_dotenv()

# top-level globals
import re
user_name = None  # we learn this once, then use it to personalize taunts/speech

def maybe_extract_name(text: str) -> str | None:
    """
    Extremely simple name extraction:
    - Looks for "my name is X", "I am X", "I'm X"
    - Keeps it intentionally strict (letters, numbers, underscore, dash) and short,
      so we don't accidentally capture full sentences.
    """
    t = (text or "").strip()
    patterns = [
        r"\bmy name is\s+([A-Za-z][A-Za-z0-9_-]{0,20})\b",
        r"\bi am\s+([A-Za-z][A-Za-z0-9_-]{0,20})\b",
        r"\bi'm\s+([A-Za-z][A-Za-z0-9_-]{0,20})\b",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


import tempfile

# -------------------------------------------------------------------------
# POSTURE TRACKING (BEST-EFFORT)
#
# Why this exists:
# - In your demo, the robot "sat/crouched" for the whole interaction.
# - That happens when you call a crouch behavior (e.g., BlocklyCrouch)
#   and then never force it to stand again.
# - The platform doesn't reliably expose "current pose", so we track what *we told it* to do.
#
# This is not perfect state, but it works great in practice:
# - Every time we successfully play a behavior, we update last_posture.
# - At "key moments" (new turn, after reset), we auto-stand if we believe it's crouched.
# -------------------------------------------------------------------------
last_posture = "stand"  # "stand" or "crouch" (best-effort tracking)

def _mark_posture_from_behavior(name: str):
    global last_posture
    if name in ("BlocklyCrouch", "BlocklySad"):
        last_posture = "crouch"
    elif name == "BlocklyStand":
        last_posture = "stand"


# If the model tries to ask for the name midgame, we block it.
NAME_ASK_RE = re.compile(r"\b(what'?s|what is)\s+your\s+name\b|\bdrop\s+your\s+name\b", re.I)
# Placeholders we might get from the LLM; we replace them if we know the user's name.
PLACEHOLDER_RE = re.compile(r"\[player name\]|\[player_name\]|\{player_name\}|\{player name\}", re.I)

# --- REMATCH "YES/NO" INTENT (race-condition fix) ---
# We *intentionally* do this with regex rather than LLM:
# - It's faster, deterministic, and doesn't fail if the LLM returns something weird.
# - It also avoids the race where rematch_mode isn't flipped yet but backend game_over is true.
YES_RE = re.compile(r"\b(yes|yeah|yep|sure|ok|okay|rematch|again|run it back|let'?s go)\b", re.I)
NO_RE  = re.compile(r"\b(no|nah|nope|quit|stop|leave|exit)\b", re.I)

def sanitize_midgame_taunt(t: str) -> str:
    """
    Keep midgame taunts safe + consistent:
    - Replace placeholders with user_name if known
    - Prevent "what's your name" spam
    - Force it into one-line speech (robot TTS works better without newlines)
    """
    global user_name
    t = (t or "").strip()
    if not t:
        return ""

    if user_name:
        t = PLACEHOLDER_RE.sub(user_name, t)

        # If it still tries to ask for name, kill it.
        if NAME_ASK_RE.search(t):
            return f"{user_name}, stop stalling and play."

    # keep it one sentence-ish
    t = t.replace("\n", " ").strip()
    return t


# --- OPENING HYPE (talk a lot early game) ---
# This is a simple "personality curve":
# - Early game: robot is extra chatty (confidence/hype)
# - Later: calms down to baseline talk frequency
OPENING_TURNS = 4          # first 4 turns -> very chatty
OPENING_SPEAK_CHANCE = 0.95
OPENING_FADE_TURNS = 6     # then fade down over next 6 turns to normal

def opening_speak_multiplier(turn: int) -> float:
    """
    turn: 0-based turn index from backend
    Returns a multiplier / override factor for early-game talking.

    Returns:
    - None: meaning "hard override talk chance to OPENING_SPEAK_CHANCE"
    - float: multiplier applied to dynamic talk chance
    """
    if turn < 0:
        return 1.0

    if turn <= OPENING_TURNS:
        return None  # special-case: hard override to OPENING_SPEAK_CHANCE

    fade_start = OPENING_TURNS + 1
    fade_end = fade_start + OPENING_FADE_TURNS

    if turn >= fade_end:
        return 1.0

    # linear fade from high -> 1.0
    # at fade_start: boost ~ (OPENING_SPEAK_CHANCE / baseline)
    alpha = (turn - fade_start) / float(OPENING_FADE_TURNS)  # 0..1
    return (1.0 - alpha) * 2.0 + alpha * 1.0  # 2x -> 1x (simple + safe)





# --- BLOWOUT INTERRUPTS (rare, human-like "not responding") ---
# This is the "sometimes I just ignore you and focus" behavior.
# Key constraints:
# - Only happens when lead is extreme (>= 6 or <= -6)
# - Only once per game per condition (once while losing big, once while winning big)
# - When it triggers, we explicitly IGNORE the user's message (continue)
BLOWOUT_LEAD = 6  # lead >= +6 = winning_big, lead <= -6 = losing_big

LOSING_BIG_INTERRUPTS = [
    "Shh—I'm trying to focus.",
    "Wait wait wait, I'm thinking.",
    "S-s-s-stop, I'm trying to focus.",
]

WINNING_BIG_INTERRUPTS = [
    "You talk a lot for someone getting cooked.",
    "Less talking, more moves.",
    "Focus on the board, you're spiraling.",
]

# Per-game flags (reset when a new game starts)
used_losing_big_interrupt = False
used_winning_big_interrupt = False
_prev_game_over_seen = None  # helps detect True -> False transition after /reset

def reset_per_game_flags():
    """
    Reset "once per game" behaviors.
    Called when we detect a new game start (game_over True -> False),
    and also directly after triggering /reset (extra safety).
    """
    global used_losing_big_interrupt, used_winning_big_interrupt
    used_losing_big_interrupt = False
    used_winning_big_interrupt = False



# --- CONFIG ---
USE_LOCAL_MIC = True  # Set False for physical robot
ROBOT_REALM = os.getenv("RIDK_REALM", "rie.693b0e88a7cba444073b9c99")
WAMP_URL = os.getenv("RIDK_WAMP_URL", "ws://wamp.robotsindeklas.nl")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
API_URL = "http://127.0.0.1:8000"

# -------------------------------------------------------------------------
# STT CONFIG (SWITCHABLE)
#
# Why this exists:
# - speech_recognition + Google Web Speech can be shaky in noisy rooms / accents.
# - OpenAI transcription tends to be more robust for short utterances.
#
# How to switch:
# - Default is Google: STT_PROVIDER=google
# - Use OpenAI:       STT_PROVIDER=openai
#
# Optional override flag (nice for quick testing):
# - If USE_OPENAI_STT=1, we force openai regardless of STT_PROVIDER.
#
# Notes:
# - OpenAI STT requires OPENAI_API_KEY to be set.
# - If OpenAI STT fails (network / key / model), we can fall back to Google if enabled.
# -------------------------------------------------------------------------
STT_PROVIDER = os.getenv("STT_PROVIDER", "google").strip().lower()  # "google" or "openai"
USE_OPENAI_STT = os.getenv("USE_OPENAI_STT", "0").strip() in ("1", "true", "yes", "y")
STT_MODEL = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")  # only used if provider=openai

# Whether we fall back to Google if OpenAI STT errors out (recommended for demos).
STT_FALLBACK_TO_GOOGLE = os.getenv("STT_FALLBACK_TO_GOOGLE", "1").strip() in ("1", "true", "yes", "y")

# Optional: language hint for Google recognizer (can slightly improve accuracy).
# Example: "en-US", "nl-NL"
STT_GOOGLE_LANGUAGE = os.getenv("STT_GOOGLE_LANGUAGE", "").strip() or None




# -------------------------------------------------------------------------
# STT QUALITY GATES (THIS FIXES "RANDOM 1 WORD" HALLUCINATIONS)
#
# Why:
# - OpenAI STT will often return *some* token even for junk/noise.
# - We prevent that by rejecting audio that is too short or too quiet BEFORE transcription.
#
# How to tune:
# - STT_MIN_AUDIO_SEC: raise if you still get junk words from tiny noises
# - STT_MIN_RMS: raise if keyboard clicks still get through; lower if it misses quiet speakers
#
# Debug:
# - STT_DEBUG_AUDIO=1 prints duration + RMS so you can tune thresholds empirically.
# -------------------------------------------------------------------------
STT_MIN_AUDIO_SEC = float(os.getenv("STT_MIN_AUDIO_SEC", "0.20"))  # 0.20–0.35 is a good range
STT_MIN_RMS = int(os.getenv("STT_MIN_RMS", "180"))                 # 150–350 depending on mic/room
STT_DEBUG_AUDIO = os.getenv("STT_DEBUG_AUDIO", "0").strip() in ("1", "true", "yes", "y")

# Optional: force OpenAI to assume a language (reduces "random foreign word" guesses).
# For demos where you want English: set STT_OPENAI_LANGUAGE=en
# Leave empty for auto-detect.
STT_OPENAI_LANGUAGE = os.getenv("STT_OPENAI_LANGUAGE", "").strip() or None

# Optional: ignore 1-word midgame transcripts (prevents bot replying to "I.", "uh", random noise tokens)
# IMPORTANT: Rematch YES/NO still works because we bypass this filter when game_over=True.
IGNORE_ONE_WORD_MIDGAME = os.getenv("IGNORE_ONE_WORD_MIDGAME", "1").strip() in ("1", "true", "yes", "y")
ONE_WORD_ALLOWLIST = {
    "hi", "hello", "hey",
    "yes", "no", "yeah", "yep", "nope",
    "ok", "okay",
    "rematch", "again",
}



# --- TUNING (BASELINES) ---
# These are the "default personality parameters".
# The dynamic_profile will shift these slightly based on lead/mood.
MOVE_SPEAK_CHANCE = 0.33   # baseline; will be modulated dynamically

# IMPORTANT CHANGE:
# - Raised from 0.10 -> 0.18 to reduce "dead robot" probability during short demos.
# - Your behavior system was probably working, just not triggering often enough.
BEHAVIOR_CHANCE   = 0.18   # baseline; will be modulated dynamically

# Optional tiny bump (still controlled by cooldown):
# - More frequent SFX makes state changes more obvious (winning vs losing).
SFX_CHANCE        = 0.30   # baseline; will be modulated dynamically

# Idle behavior:
# - If user stalls too long, the robot does something (sound + maybe a small move)
IDLE_TIMEOUT = 20.0
IDLE_INTERVAL = 15.0

# --- ANTI-SPAM / WAIT TIMER ---
# "wait_sfx" is a delayed sound that triggers if the user takes too long on the SAME turn.
WAIT_SFX_CHANCE = 0.20     # baseline; will be modulated dynamically
WAIT_SFX_DELAY_MIN = 4.0
WAIT_SFX_DELAY_MAX = 40.0

SFX_COOLDOWN = 10.0  # never play SFX more frequently than this


# --- BEHAVIOR ANTI-SPAM ---
# Robot motions are high-impact; we enforce stronger cooldowns than speech.
BEHAVIOR_COOLDOWN = 25.0          # seconds between any two behaviors (big impact)
TAG_BEHAVIOR_MAX_CHANCE = 0.12    # even if LLM tags, only do it sometimes
TAG_BEHAVIOR_DELAY = 0.6          # wait a bit so speech isn't cut off

last_behavior_time = 0.0
last_behavior_name = None


client = OpenAI(api_key=OPENAI_API_KEY)
recognizer = sr.Recognizer()

# --- SOUND EFFECTS ---
# Each category is a pool of URLs. We randomly pick one when playing that category.
SOUNDS = {
    "WIN": [
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/tmp_7901-951678082.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/vine-boom.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/mi-bombo.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/fahhh_KcgAXfs.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/let-me-know.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/meme-de-creditos-finales.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/rat-dance-music.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/wrong-answer-sound-effect.mp3",
    ],
    "LOSE": [
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/downer_noise.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/spongebob-fail.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/sponge-stank-noise.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/another-one_dPvHt2Z.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/baby-laughing-meme.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/bye-bye-lumi-athena-sfx.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/ny-video-online-audio-converter.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/sitcom-laughing-1.mp3",
    ],
    "ANNOY": [
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/awkward-moment.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/tuco-get-out.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/oh-my-god-bro-oh-hell-nah-man.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/%EF%BC%82Adrian%EF%BC%82%20Sound%20Effect%20%5BAQXqiVtF2DI%5D.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/aplausos_2.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/enrique.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/error_CDOxCYm.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/he-he-he-ha-clash-royale-deep-fried.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/metal-pipe-clang.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/rizz-sound-effect.mp3",
    ],
    "WAIT": [
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/%EF%BC%82Adrian%EF%BC%82%20Sound%20Effect%20%5BAQXqiVtF2DI%5D.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/we-are-charlie-kirk-song.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/500-cigarettes-tiktok-version.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/pluh.mp3",
    ],
}

# --- BEHAVIORS ---
# These are robot motion "macros" defined in the robot platform.
# We choose different moves based on mood (winning/losing/annoyed/idle).
MOVES = {
    "WIN_BIG": ["BlocklyDiscoDance", "BlocklyStarWars", "BlocklyMacarena"],
    "WIN_SMALL": ["BlocklyDab", "BlocklyHappy", "BlocklyApplause"],
    "LOSE": ["BlocklyCrouch", "BlocklyShrug", "BlocklySad"],
    "ANNOY": ["BlocklySneeze", "BlocklySaxophone", "BlocklyTurnAround"],
    "IDLE": ["BlocklyTaiChiChuan", "BlocklyStand"],
}

# --- GLOBAL STATE ---
# Shared state across loops.
# NOTE: These are accessed from different threads without locks.
# For this use-case it’s usually fine because:
# - We mainly do "best effort" gating (cooldowns, flags)
# - Occasional off-by-one timing doesn't break safety
current_game_state = {"ai_lead": 0, "game_over": False}
last_turn_index = -1
is_speaking = False            # used to avoid overlapping audio + SFX
rematch_mode = False           # set when game ends; used to switch speech logic
last_interaction_time = time.time()

# --- SHUTDOWN + WAIT TIMER + COOLDOWN ---
shutdown_event = threading.Event()

wait_sfx_due = None
wait_sfx_turn = None
wait_sfx_category = "WAIT"
last_sfx_time = 0.0

# --- DYNAMIC PROFILE (UPDATED EACH TICK) ---
# This dict is continuously overwritten by compute_dynamic_profile().
dynamic_profile = {
    "mood": "close",
    "lead": 0,
    "move_speak_chance": MOVE_SPEAK_CHANCE,
    "behavior_chance": BEHAVIOR_CHANCE,
    "sfx_chance": SFX_CHANCE,
    "wait_sfx_chance": WAIT_SFX_CHANCE,
}

# -------------------------
# Dynamic helpers
# -------------------------

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def _clamp01(x: float) -> float:
    return _clamp(x, 0.0, 1.0)

def _mood_from_lead(lead: int) -> str:
    # You can tweak these thresholds safely.
    if lead >= 6:
        return "winning_big"
    if lead >= 3:
        return "winning"
    if lead <= -6:
        return "losing_big"
    if lead <= -3:
        return "losing"
    return "close"

def compute_dynamic_profile(lead: int) -> dict:
    """
    Convert game lead into noticeable-but-not-insane probability shifts.

    The goal is: "it feels aware of the game" without becoming chaotic/spammy.
    We do that by:
    - normalizing lead into [-1, 1]
    - gently nudging baseline probabilities
    - clamping everything to [0, 1]

    Intuition:
    - Winning => slightly more confident talk + slightly more celebration
    - Losing  => slightly less confident talk + more "waiting / bored / coping" vibes
    """
    mood = _mood_from_lead(lead)

    # Normalize into [-1, 1] using a "meaningful" lead scale.
    # (Connect 4 lead feels real at ~6+)
    adv = _clamp(lead / 6.0, -1.0, 1.0)

    # More talk + more moves when winning, less when losing
    move_speak = _clamp01(MOVE_SPEAK_CHANCE + 0.06 * adv)  # small shift, stays subtle
    behavior    = _clamp01(BEHAVIOR_CHANCE   + 0.20 * max(0, adv) - 0.10 * max(0, -adv))
    # Slightly more SFX when emotional (close or losing), but never spammy due to cooldown anyway
    sfx         = _clamp01(SFX_CHANCE        + 0.10 * abs(adv) + (0.05 if mood == "close" else 0.0))
    # Losing => more "WAIT/bored" timer triggers, winning => less
    wait_chance = _clamp01(WAIT_SFX_CHANCE   + 0.20 * max(0, -adv) - 0.15 * max(0, adv))

    return {
        "mood": mood,
        "lead": lead,
        "move_speak_chance": move_speak,
        "behavior_chance": behavior,
        "sfx_chance": sfx,
        "wait_sfx_chance": wait_chance,
    }

def choose_wait_sfx_category(mood: str) -> str:
    """
    This is where the robot *feels* different (sound palette depends on mood):
    - winning => celebratory / cocky (WIN)
    - close   => tension/annoy (ANNOY)
    - losing  => bored/deflated (WAIT)

    This is a simple trick that makes the bot "feel alive" without extra LLM calls.
    """
    # IMPORTANT CHANGE:
    # - When losing, we now actually use LOSE sounds (instead of mostly WAIT/ANNOY).
    # - This makes the emotional palette shift much more obvious during the game,
    #   not only at the final game-over moment.
    if mood in ("winning_big", "winning"):
        # Mostly WIN but sometimes ANNOY so it's not a casino
        return "WIN" if random.random() < 0.8 else "ANNOY"
    if mood == "close":
        return "ANNOY" if random.random() < 0.85 else "WAIT"
    # losing / losing_big -> actually use LOSE most of the time
    return "LOSE" if random.random() < 0.7 else "WAIT"

def choose_idle_sfx_category(mood: str) -> str:
    # Idle should reflect the state too.
    # IMPORTANT CHANGE:
    # - Losing idle now uses LOSE instead of WAIT so it sounds "deflated" rather than "random meme".
    if mood in ("winning_big", "winning"):
        return "ANNOY"  # “hurry up” energy
    if mood == "close":
        return "ANNOY"
    return "LOSE"       # losing => deflated/losing palette

def dynamic_prompt_suffix(lead: int) -> str:
    """
    Very cheap win: the LLM prompt changes based on lead magnitude.
    No big refactor needed.

    We DON'T rewrite the whole system prompt each time; we just append a mood hint.
    """
    mood = _mood_from_lead(lead)
    if mood == "winning_big":
        return " You are DOMINATING: be smug, cocky, and playful. Flex hard."
    if mood == "winning":
        return " You are winning: be confident and teasing."
    if mood == "losing_big":
        return " You are getting cooked: be salty, defensive, and a bit stressed."
    if mood == "losing":
        return " You are losing: be annoyed, blame luck/sensors, sound less confident."
    return " It's close: be tense, impatient, and competitive."

# -------------------------
# Shutdown wiring
# -------------------------

def request_shutdown(reason: str = ""):
    # Unified shutdown so both threads + reactor stop cleanly.
    if reason:
        print(f"[Brain] Shutdown requested: {reason}")
    shutdown_event.set()
    try:
        reactor.callFromThread(reactor.stop)
    except Exception:
        pass

def _sig_handler(signum, frame):
    request_shutdown(f"signal {signum}")

signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)

# -------------------------
# API
# -------------------------

def fetch_game_state():
    """
    Poll the backend for game state.
    Expected keys (based on your usage):
    - turn_index, game_over, last_taunt, ai_lead, winner, etc.
    """
    try:
        res = requests.get(f"{API_URL}/state", timeout=0.5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {}

def trigger_reset():
    """
    Ask backend to reset the game.
    NOTE: We keep this fire-and-forget; if it fails, game_over will stay true
    and the rematch handler will keep prompting.
    """
    try:
        requests.post(f"{API_URL}/reset", timeout=1)
    except Exception:
        pass

def generate_response(user_text, context_type="gameplay"):
    """
    LLM response generator.

    Two "modes":
    - gameplay: short toxic trash-talk; optionally tags for robot behaviors
    - rematch: constrained "YES/NO" decision in output

    Even though we now handle game_over rematch directly (race fix),
    we keep this mode for safety/fallback and because rematch_mode can still be used.
    """
    try:
        if context_type == "rematch":
            system_msg = "If YES: 'ACTION_RESET'. If NO: 'ACTION_QUIT'. Else ask again."
            context = f"User said: {user_text}"
        else:
            state = fetch_game_state()
            lead = int(state.get("ai_lead", 0) or 0)

            system_msg = (
                "You are 'Robo', a cocky, competitive Connect 4 robot. "
                "Keep responses SHORT (1 sentence). "
                "Use Gen Z slang lightly. "
                "Never mention being an AI or OpenAI. "
                "You can perform actions by ending your sentence with tags: "
                "[DANCE], [DAB], [SNEEZE], [CLAP], [SAD]. "
                "Tags are RARE: use a tag in at most 1 out of 10 replies, otherwise no tag. "
                "Only use tags if the situation is extreme."
                "ask for the users name at first and then keep calling them by their name"
                "don't use emojis in the responses"
            ) + dynamic_prompt_suffix(lead)

            context = f"Score Lead: {lead}. User said: {user_text}"
            if user_name:
                system_msg += f" The user's name is {user_name}. Never ask for their name. Always address them by name."
            else:
                system_msg += " If you don't know the user's name yet, ask once, then stop asking."

        try:
            response = client.responses.create(
                model=OPENAI_MODEL,
                instructions=system_msg,
                input=context,
                max_output_tokens=60,
            )
            return response.output_text or ""
        except Exception as e:
            # Basic fallback if model name is wrong/unavailable.
            msg = str(e).lower()
            if "model" in msg and ("not found" in msg or "404" in msg):
                response = client.responses.create(
                    model="gpt-4o-mini",
                    instructions=system_msg,
                    input=context,
                    max_output_tokens=60,
                )
                return response.output_text or ""
            raise

    except Exception as e:
        print(f"[Brain] LLM Error: {e}")
        return ""

# -------------------------
# WAIT SFX scheduling
# -------------------------

def schedule_wait_sfx(turn: int, profile: dict):
    """
    Schedules a delayed SFX for THIS turn.

    Concept:
    - When it's the user's "turn" or the game is waiting, the human might stall.
    - So we schedule a sound that triggers after some random delay.
    - If the turn changes or the robot speaks, we cancel it.

    Category + chance are dynamic based on mood.
    """
    global wait_sfx_due, wait_sfx_turn, wait_sfx_category
    wait_sfx_turn = turn

    # Choose category from mood (this is the “noticeable” part)
    wait_sfx_category = choose_wait_sfx_category(profile["mood"])

    if random.random() < float(profile.get("wait_sfx_chance", WAIT_SFX_CHANCE)):
        wait_sfx_due = time.time() + random.uniform(WAIT_SFX_DELAY_MIN, WAIT_SFX_DELAY_MAX)
    else:
        wait_sfx_due = None

def cancel_wait_sfx():
    # Called whenever turn changes or game ends; prevents out-of-context sounds.
    global wait_sfx_due, wait_sfx_turn
    wait_sfx_due = None
    wait_sfx_turn = None



# -------------------------
# Actuation
# -------------------------

@inlineCallbacks
def safe_play_behavior(session, name: str, sync: bool = True, why: str = ""):
    """
    Always logs failures. If behaviors are unavailable in the environment,
    you'll SEE it immediately in the console.
    """
    try:
        print(f"[Brain] 🕺 Behavior: {name} (sync={sync}) {('|' + why) if why else ''}")
        yield session.call("rom.optional.behavior.play", name=name, sync=sync)
        _mark_posture_from_behavior(name)
    except Exception as e:
        print(f"[Brain] ❌ Behavior failed ({name}): {e}")




@inlineCallbacks
def play_sfx(session, category, force=False):
    """
    Plays random sound w/ cooldown + dynamic chance + no overlap with speech.

    Why:
    - Sound effects add "texture" and make the robot feel reactive.
    - Cooldown prevents it from becoming an annoying soundboard.
    """
    global last_sfx_time

    if shutdown_event.is_set():
        return
    if is_speaking:
        return

    now = time.time()
    if now - last_sfx_time < SFX_COOLDOWN:
        return

    # Dynamic chance (still respects force)
    effective = float(dynamic_profile.get("sfx_chance", SFX_CHANCE))
    if not force and random.random() > effective:
        return

    url_list = SOUNDS.get(category, [])
    if url_list:
        url = random.choice(url_list)
        print(f"[Brain] 🎵 Playing SFX ({category}): {url}")
        last_sfx_time = now
        yield session.call("rom.actuator.audio.stream", url=url, sync=False)

@inlineCallbacks
def perform_midgame_event(session, text, anim_name, sfx_category, profile: dict, turn: int):
    """
    Midgame reactions after a move.
    Speech + behavior are dynamically modulated.

    This is called from game_loop when a new turn is detected and last_taunt exists.
    """
    move_speak = float(profile.get("move_speak_chance", MOVE_SPEAK_CHANCE))

    # Opening hype: hard override for first moves, then fade
    mult = opening_speak_multiplier(turn)
    if mult is None:
        move_speak = OPENING_SPEAK_CHANCE
    else:
        move_speak = _clamp01(move_speak * mult)

    behave = float(profile.get("behavior_chance", BEHAVIOR_CHANCE))

    # IMPORTANT CHANGE:
    # - Demos are short. If you miss behaviors in the first ~30 seconds, the robot feels "dead".
    # - So we enforce a minimum behavior probability for the first couple turns.
    # - This does NOT remove randomness; it just reduces the chance of "0 behaviors forever".
    if turn <= 2:
        behave = max(behave, 0.35)  # guarantee you likely see *something* early

    global is_speaking

    # Speech is probabilistic so it doesn't respond on every single move
    # (that would feel robotic and spammy).
    if text and random.random() < move_speak:
        print(f"[Brain] 🤖 Speaking: {text}")
        is_speaking = True
        try:
            yield session.call("rie.dialogue.say", text=text)
        finally:
            is_speaking = False

    if sfx_category:
        yield play_sfx(session, sfx_category, force=True)

    # Behaviors are also probabilistic and are kept rarer than speech.
    # IMPORTANT CHANGE:
    # - Use safe_play_behavior so failures are visible AND posture tracking updates.
    if anim_name and random.random() < behave:
        yield safe_play_behavior(session, anim_name, sync=True, why="midgame reaction")

@inlineCallbacks
def perform_idle_action(session, profile: dict):
    """
    Triggers when bored; now reflects mood.

    Why:
    - Humans get impatient when the other player stalls.
    - A subtle idle reaction makes the robot feel present even when nothing happens.
    """
    mood = profile.get("mood", "close")
    print(f"[Brain] ⏳ Robot is bored... (mood={mood})")

    cat = choose_idle_sfx_category(mood)
    yield play_sfx(session, cat, force=True)

    # idle move probability also shifts a bit:
    # losing => less movement (deflated), winning => slightly more
    adv = _clamp((profile.get("lead", 0) or 0) / 6.0, -1.0, 1.0)
    idle_move_chance = _clamp01(0.25 + 0.10 * max(0, adv) - 0.10 * max(0, -adv))

    if random.random() < idle_move_chance:
        anim = random.choice(MOVES["IDLE"])
        yield safe_play_behavior(session, anim, sync=True, why="idle action")

# -------------------------
# Speech-to-text helpers
# -------------------------

def transcribe_audio_google(audio: sr.AudioData) -> str | None:
    """
    Google Web Speech via speech_recognition.

    Pros:
    - free-ish / easy / no extra API code
    Cons:
    - can be inaccurate in noisy rooms / accents / short utterances
    """
    try:
        if STT_GOOGLE_LANGUAGE:
            return (recognizer.recognize_google(audio, language=STT_GOOGLE_LANGUAGE) or "").strip()
        return (recognizer.recognize_google(audio) or "").strip()
    except Exception as e:
        # Keep logs minimal here; listen_loop already does try/except,
        # but for debugging STT quality it's useful to see failures.
        print(f"[Brain] STT(Google) failed: {e}")
        return None

def transcribe_audio_openai(audio: sr.AudioData) -> str | None:
    """
    OpenAI speech-to-text.

    Why we write to a temp WAV:
    - The OpenAI client expects a file-like object for transcription.
    - speech_recognition gives us raw bytes; easiest is to dump to a temp .wav.

    Notes:
    - We use delete=False + manual unlink to avoid file-handle quirks on some platforms.
    - If this fails, listen_loop can fall back to Google if STT_FALLBACK_TO_GOOGLE=1.
    """
    try:
        wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
                f.write(wav_bytes)
                f.flush()

            with open(tmp_path, "rb") as audio_file:
                # NOTE:
                # - Passing a language hint reduces "random foreign word" guesses for noise.
                # - Keep STT_OPENAI_LANGUAGE empty if you want auto-detect.
                kwargs = {}
                if STT_OPENAI_LANGUAGE:
                    kwargs["language"] = STT_OPENAI_LANGUAGE

                tr = client.audio.transcriptions.create(
                    model=STT_MODEL,
                    file=audio_file,
                    response_format="text",
                    **kwargs,
                )


            # The SDK can return either a string or an object with `.text`.
            if isinstance(tr, str):
                return tr.strip()
            if hasattr(tr, "text"):
                return (tr.text or "").strip()
            return str(tr).strip()

        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    except Exception as e:
        print(f"[Brain] STT(OpenAI) failed: {e}")
        return None



def transcribe_audio(audio: sr.AudioData) -> str | None:
    """
    Single entry point for STT so the rest of the code stays clean.

    Decision logic:
    - If USE_OPENAI_STT=1 -> force OpenAI
    - Else use STT_PROVIDER (google/openai)
    - If OpenAI fails and STT_FALLBACK_TO_GOOGLE=1 -> try Google as backup
    """
    provider = "openai" if USE_OPENAI_STT else STT_PROVIDER

    if provider == "openai":
        # If key is missing, don't hard-crash the demo; try fallback.
        if not OPENAI_API_KEY:
            print("[Brain] STT(OpenAI) selected but OPENAI_API_KEY is missing. Falling back to Google.")
            return transcribe_audio_google(audio)

        text = transcribe_audio_openai(audio)
        if text:
            return text

        if STT_FALLBACK_TO_GOOGLE:
            return transcribe_audio_google(audio)

        return None

    # default: google
    return transcribe_audio_google(audio)



def _audio_stats_for_gate(audio: sr.AudioData) -> tuple[float, int]:
    """
    Compute (duration_seconds, rms) for the captured audio.

    We intentionally convert to 16kHz / 16-bit mono-style raw PCM for consistent RMS behavior
    across different microphones/devices.

    - duration_seconds: rejects micro-bursts (clicks, bumps, tiny noise)
    - rms: rejects quiet background hiss that OpenAI would otherwise "turn into a word"
    """
    try:
        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)  # 16kHz, 16-bit
        if not raw:
            return 0.0, 0
        duration = len(raw) / (16000 * 2)  # samples * bytes_per_sample
        rms = audioop.rms(raw, 2)          # 2 bytes/sample
        return duration, rms
    except Exception:
        # If anything goes wrong, fail "open" (let STT try) rather than breaking the pipeline.
        return 0.0, 999999


def _should_transcribe_audio(audio: sr.AudioData) -> bool:
    """
    Hard gate BEFORE calling STT.

    This is the main fix for your issue:
    - If audio is too short or too quiet, we skip transcription entirely.
    - That prevents OpenAI from hallucinating random 1-word outputs.
    """
    dur, rms = _audio_stats_for_gate(audio)

    if STT_DEBUG_AUDIO:
        print(f"[Brain] 🎙️ audio_gate: dur={dur:.3f}s rms={rms} (min_dur={STT_MIN_AUDIO_SEC}, min_rms={STT_MIN_RMS})")

    if dur < STT_MIN_AUDIO_SEC:
        return False
    if rms < STT_MIN_RMS:
        return False
    return True


def _should_ignore_transcript_midgame(text: str, game_over_now: bool) -> bool:
    """
    Optional SECOND gate AFTER transcription.

    Why:
    - Even with audio gating, sometimes you still get a clean 1-word token from small noises.
    - In a Connect-4 demo, replying to random 1-word inputs kills the vibe.

    Rules:
    - Never ignore during game_over rematch flow (YES/NO might be 1 word).
    - If IGNORE_ONE_WORD_MIDGAME=1:
        ignore single-word transcripts unless in allowlist.
    """
    if game_over_now:
        return False

    if not IGNORE_ONE_WORD_MIDGAME:
        return False

    words = [w for w in re.findall(r"[A-Za-z']+", (text or "").lower()) if w]
    if len(words) <= 1:
        w = words[0] if words else ""
        if w and (w in ONE_WORD_ALLOWLIST):
            return False
        return True

    return False


# -------------------------
# Main loops
# -------------------------

@inlineCallbacks
def game_loop(session):
    """
    This loop is the "game event detector":
    - It polls /state
    - Detects new turns and game_over transitions
    - Drives:
      - scheduled wait SFX (stalling)
      - idle actions (long silence)
      - game-over routine
      - midgame taunts/animations

    Important:
    - This loop is NOT responsible for listening to speech.
    - Speech comes from listen_loop.
    """
    global last_turn_index, current_game_state, rematch_mode, is_speaking, last_interaction_time, dynamic_profile, last_posture
    print("[Brain] 🎮 Game Loop Active")

    cancel_wait_sfx()

    while not shutdown_event.is_set():
        try:
            state = yield threads.deferToThread(fetch_game_state)
            if state:
                current_game_state = state
                turn = int(state.get("turn_index", -1) or -1)
                game_over = bool(state.get("game_over", False))
                taunt = state.get("last_taunt", "")
                lead = int(state.get("ai_lead", 0) or 0)
                winner = state.get("winner")

                # Update dynamic profile every tick (cheap + effective)
                dynamic_profile = compute_dynamic_profile(lead)

                # --- FIRE WAIT SFX IF DUE ---
                if (
                    wait_sfx_due is not None
                    and not game_over
                    and not rematch_mode
                    and not is_speaking
                    and turn == wait_sfx_turn
                    and time.time() >= wait_sfx_due
                ):
                    yield play_sfx(session, wait_sfx_category, force=True)
                    cancel_wait_sfx()

                # --- IDLE CHECK ---
                if (
                    not game_over
                    and not is_speaking
                    and (time.time() - last_interaction_time > IDLE_TIMEOUT)
                ):
                    yield perform_idle_action(session, dynamic_profile)
                    last_interaction_time = time.time() + IDLE_INTERVAL

                # --- NEW TURN DETECTED ---
                if turn > last_turn_index:
                    last_turn_index = turn
                    last_interaction_time = time.time()

                    cancel_wait_sfx()
                    if not game_over and not rematch_mode:
                        schedule_wait_sfx(turn, dynamic_profile)

                    # IMPORTANT CHANGE:
                    # - If we believe the robot is currently crouched (from earlier game-over routine),
                    #   force it back to stand at the start of the next turn.
                    # - This prevents the "sat down forever" demo failure mode.
                    if last_posture == "crouch" and (not game_over):
                        yield safe_play_behavior(session, "BlocklyStand", sync=True, why="new turn auto-stand")

                    # 1) GAME OVER ROUTINE
                    if game_over and not rematch_mode:
                        print("[Brain] 🏁 GAME OVER.")
                        rematch_mode = True
                        cancel_wait_sfx()

                        # This is your "scripted" ending sequence.
                        # Scripted content is good here because it is reliable and feels intentional.
                        if winner == -1:
                            yield play_sfx(session, "WIN", force=True)
                            yield session.call("rie.dialogue.say", text="Good game. Come on, let’s shake hands.")
                            yield safe_play_behavior(session, "BlocklyDab", sync=True, why="game over win (-1)")
                            yield session.call("rie.dialogue.say", text="Just kidding. I don’t shake hands with losers.")
                            yield safe_play_behavior(session, "BlocklyGangnamStyle", sync=True, why="game over win (-1)")
                            yield safe_play_behavior(session, "BlocklyCrouch", sync=True, why="game over win (-1) crouch punchline")

                        elif winner == 1:
                            yield play_sfx(session, "LOSE", force=True)
                            yield session.call("rie.dialogue.say", text="No way... I demand a recount.")
                            yield safe_play_behavior(session, "BlocklyCrouch", sync=True, why="game over lose (1)")

                        else:
                            yield play_sfx(session, "ANNOY", force=True)
                            yield session.call("rie.dialogue.say", text="Draw game.")

                        yield tSleep(1.0)
                        yield session.call("rie.dialogue.say", text="Do you want a rematch? Say yes.")

                    # 2) MID-GAME MOVE (now mood-aware)
                    elif not rematch_mode and taunt and not is_speaking:
                        mood = dynamic_profile["mood"]
                        anim = None

                        # winning => dance more; losing => deflated; close => irritated
                        if mood == "winning_big":
                            anim = random.choice(MOVES["WIN_BIG"])
                        elif mood == "winning":
                            anim = random.choice(MOVES["WIN_SMALL"])
                        elif mood == "losing_big":
                            anim = random.choice(MOVES["LOSE"])
                        elif mood == "losing":
                            anim = "BlocklyShrug" if random.random() < 0.6 else random.choice(MOVES["LOSE"])
                        else:
                            # close game => annoyance gestures sometimes
                            if random.random() < 0.35:
                                anim = random.choice(MOVES["ANNOY"])

                        taunt = sanitize_midgame_taunt(taunt)

                        # We keep midgame SFX mostly off so it doesn't stack;
                        # the WAIT timer handles state-colored sounds.
                        yield perform_midgame_event(
                            session,
                            taunt,
                            anim,
                            sfx_category=None,
                            profile=dynamic_profile,
                            turn=turn
                        )

                # After reset happens (game_over false), leave rematch mode
                if not game_over and rematch_mode:
                    rematch_mode = False
                    cancel_wait_sfx()
                    if turn >= 0:
                        schedule_wait_sfx(turn, dynamic_profile)

                    # Extra safety: after rematch ends and gameplay resumes,
                    # force a stand pose if we were crouched.
                    if last_posture == "crouch":
                        yield safe_play_behavior(session, "BlocklyStand", sync=True, why="post-rematch auto-stand")

        except Exception as e:
            print(f"[Brain] game_loop error: {e}")

        yield tSleep(0.5)


def _should_allow_tag_behavior(anim: str) -> bool:
    """
    Make LLM-tagged behaviors a rare, state-aware surprise.

    Why this exists:
    - LLM sometimes outputs behavior tags like [DANCE]
    - We don't want the robot to do a dance every time the LLM feels like it
    - So we gate it through:
      - a global cooldown
      - mood appropriateness (no happy dance while losing)
      - a small probability
      - anti-repeat check (same move twice feels robotic)
    """
    global last_behavior_time, last_behavior_name

    now = time.time()
    if now - last_behavior_time < BEHAVIOR_COOLDOWN:
        return False

    mood = dynamic_profile.get("mood", "close")

    # Don't allow "win" dances unless actually winning
    if anim in MOVES["WIN_BIG"] or anim in MOVES["WIN_SMALL"]:
        if mood not in ("winning", "winning_big"):
            return False

    # Don't allow "sad/lose" moves unless actually losing
    if anim in MOVES["LOSE"]:
        if mood not in ("losing", "losing_big"):
            return False

    # avoid repeating the same move back-to-back
    if anim == last_behavior_name:
        return False

    # small probability even when tagged
    base = TAG_BEHAVIOR_MAX_CHANCE
    # tiny bit more expressive when winning big
    if mood == "winning_big":
        base = min(0.18, base + 0.06)

    # also respect your dynamic behavior chance but make it stricter for convo
    dyn = float(dynamic_profile.get("behavior_chance", BEHAVIOR_CHANCE))
    p = min(base, dyn * 0.5)   # important: convo should be rarer than midgame

    if random.random() > p:
        return False

    # reserve cooldown immediately so multiple tags in a row don't queue behaviors
    last_behavior_time = now
    last_behavior_name = anim
    return True





def listen_loop(session):
    """
    This loop is the "speech brain".

    Pipeline:
    1) Listen for audio (short phrase_time_limit)
    2) Speech-to-text via Google recognizer
    3) Peek backend game state *immediately* (fresh truth)
    4) Special handlers:
       - HARD REMATCH (race condition fix): if game_over_now=True, parse YES/NO directly
       - Blowout interrupts (win/lose by a lot): say a canned phrase + ignore input
    5) If none of the above triggers, use LLM to generate a one-liner response
    6) Optionally trigger a behavior tag (rare)
    """
    global is_speaking, rematch_mode, last_interaction_time, last_posture

    with sr.Microphone() as source:
        print("[Brain] 🎧 Calibrating...")
        
        # ------------------------------------------------------------------
        # MIC TUNING
        #
        # These reduce false triggers (mic deciding "speech started" on tiny noises).
        # Combined with the audio gate, this makes STT rock-solid in demos.
        # ------------------------------------------------------------------
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.6
        recognizer.non_speaking_duration = 0.3
        recognizer.phrase_threshold = 0.25

        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[Brain] 👂 Listening!")

        while not shutdown_event.is_set():
            try:
                try:
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=5)
                    # ------------------------------------------------------------------
                    # AUDIO GATE (MOST IMPORTANT FIX)
                    #
                    # We drop audio that is too short/quiet BEFORE we call STT.
                    # This prevents OpenAI from hallucinating random 1-word "transcripts".
                    # ------------------------------------------------------------------
                    if not _should_transcribe_audio(audio):
                        continue

                except sr.WaitTimeoutError:
                    continue

                try:
                    # IMPORTANT CHANGE:
                    # - STT is now switchable (Google vs OpenAI) using STT_PROVIDER / USE_OPENAI_STT.
                    # - This is isolated behind transcribe_audio() so the rest of the logic stays identical.
                    text = transcribe_audio(audio) or ""
                    if not text:
                        continue

                    last_interaction_time = time.time()
                    print(f"[Brain] 🗣️ You: {text}")

                    # Peek game state NOW (fresh backend truth).
                    # This lets speech logic react correctly even if game_loop hasn't ticked yet.
                    state = fetch_game_state()
                    lead_now = int(state.get("ai_lead", 0) or 0)
                    game_over_now = bool(state.get("game_over", False))
                    # ------------------------------------------------------------------
                    # POST-STT FILTER (OPTIONAL BUT VERY EFFECTIVE)
                    #
                    # If we are NOT in rematch/game_over flow, ignore 1-word transcripts.
                    # This stops the robot replying to random single tokens (noise -> "I", "Dios", etc.).
                    # ------------------------------------------------------------------
                    if _should_ignore_transcript_midgame(text, game_over_now=game_over_now):
                        if STT_DEBUG_AUDIO:
                            print(f"[Brain] 🧹 Ignored short transcript midgame: {text!r}")
                        continue


                    # Reset per-game flags when a new game starts:
                    # Detect transition: game_over True -> False (after /reset)
                    global _prev_game_over_seen
                    if _prev_game_over_seen is None:
                        _prev_game_over_seen = game_over_now
                    else:
                        if _prev_game_over_seen and not game_over_now:
                            reset_per_game_flags()
                        _prev_game_over_seen = game_over_now

                    # ------------------------------------------------------------------
                    # HARD REMATCH HANDLER (race-condition fix)
                    #
                    # Problem:
                    # - User says "yes" exactly when the game ends.
                    # - Backend already says game_over=True.
                    # - But game_loop hasn't processed it yet -> rematch_mode might still be False.
                    # - Then we send text to gameplay LLM, and reset never triggers.
                    #
                    # Fix:
                    # - If backend says game_over_now=True, we treat rematch as active RIGHT HERE.
                    # - We parse YES/NO deterministically using regex and trigger reset immediately.
                    # - This path avoids the LLM entirely, so it can't "forget" to output ACTION_RESET.
                    # ------------------------------------------------------------------
                    if game_over_now:
                        # Force rematch mode locally even if game_loop hasn't updated it yet.
                        rematch_mode = True

                        # If robot is currently talking, stop it so user input gets priority.
                        if is_speaking:
                            reactor.callFromThread(session.call, "rie.dialogue.stop")

                        # "YES" -> reset the game
                        if YES_RE.search(text):
                            print("[Brain] 🟢 Rematch (direct)!")
                            is_speaking = True
                            reactor.callFromThread(session.call, "rie.dialogue.say", text="Here we go again!")
                            trigger_reset()

                            # IMPORTANT CHANGE:
                            # - Auto-stand shortly after reset so we don't stay crouched into the next game.
                            # - We schedule this on the reactor thread because behaviors must run there.
                            reactor.callFromThread(
                                reactor.callLater,
                                0.6,
                                safe_play_behavior,
                                session,
                                "BlocklyStand",
                                True,
                                "post-reset auto-stand (direct rematch)"
                            )

                            # We already know a new game is starting; reset once-per-game flags now.
                            # (We ALSO reset on game_over True->False transition, so this is redundant safety.)
                            reset_per_game_flags()

                            rematch_mode = False
                            time.sleep(0.6)
                            is_speaking = False
                            continue

                        # "NO" -> quit / end interaction
                        if NO_RE.search(text):
                            print("[Brain] 🔴 Quit (direct).")
                            is_speaking = True
                            reactor.callFromThread(session.call, "rie.dialogue.say", text="Fine, bye.")
                            reactor.callFromThread(
                                session.call,
                                "rom.optional.behavior.play",
                                name="BlocklyCrouch",
                                sync=False
                            )
                            last_posture = "crouch"
                            time.sleep(0.6)
                            is_speaking = False
                            continue

                        # Unclear answer -> prompt again (still no LLM)
                        is_speaking = True
                        reactor.callFromThread(
                            session.call,
                            "rie.dialogue.say",
                            text="Say yes for a rematch, or no to quit."
                        )
                        time.sleep(0.6)
                        is_speaking = False
                        continue

                    # Only do blowout interrupts midgame (not during rematch prompt, not after game_over)
                    global used_losing_big_interrupt, used_winning_big_interrupt

                    if (not rematch_mode) and (not game_over_now):
                        if (lead_now <= -BLOWOUT_LEAD) and (not used_losing_big_interrupt):
                            used_losing_big_interrupt = True
                            phrase = random.choice(LOSING_BIG_INTERRUPTS)

                            if is_speaking:
                                reactor.callFromThread(session.call, "rie.dialogue.stop")

                            print(f"[Brain] 🤖 BlowoutInterrupt(LOSING): {phrase}")
                            is_speaking = True
                            reactor.callFromThread(session.call, "rie.dialogue.say", text=phrase)
                            time.sleep(1.0)
                            is_speaking = False
                            continue  # IMPORTANT: ignore user's message, no LLM response

                        if (lead_now >= BLOWOUT_LEAD) and (not used_winning_big_interrupt):
                            used_winning_big_interrupt = True
                            phrase = random.choice(WINNING_BIG_INTERRUPTS)

                            if is_speaking:
                                reactor.callFromThread(session.call, "rie.dialogue.stop")

                            print(f"[Brain] 🤖 BlowoutInterrupt(WINNING): {phrase}")
                            is_speaking = True
                            reactor.callFromThread(session.call, "rie.dialogue.say", text=phrase)
                            time.sleep(1.0)
                            is_speaking = False
                            continue  # IMPORTANT: ignore user's message, no LLM response

                except Exception:
                    continue

                # Learn user name (only once). This is used for personalization.
                # IMPORTANT CHANGE:
                # - Previously you only learned the name once (user_name is None).
                # - If STT misheard the name the first time, you were stuck forever.
                # - Now: if user says "my name is X" again, we update it.
                global user_name
                name = maybe_extract_name(text)
                if name and name != user_name:
                    user_name = name
                    print(f"[Brain] ✅ Updated user_name={user_name}")

                # If robot is speaking, stop current speech so responses feel reactive.
                if is_speaking:
                    reactor.callFromThread(session.call, "rie.dialogue.stop")

                is_speaking = True

                # PATCH 3 (extra safety):
                # - Decide context based on rematch_mode *AND* fresh backend truth.
                # - This prevents misrouting even if rematch_mode lags behind reality.
                #   (We already handle game_over_now above, but this is a safe belt-and-suspenders.)
                latest_state = fetch_game_state()
                latest_game_over = bool(latest_state.get("game_over", False))
                context = "rematch" if (rematch_mode or latest_game_over) else "gameplay"

                reply = generate_response(text, context) or ""

                # Behavior tags in the model output map to actual robot motions
                anim = None
                if "[DANCE]" in reply:
                    anim = random.choice(MOVES["WIN_BIG"])
                elif "[DAB]" in reply:
                    anim = "BlocklyDab"
                elif "[SNEEZE]" in reply:
                    anim = "BlocklySneeze"
                elif "[CLAP]" in reply:
                    anim = "BlocklyApplause"
                elif "[SAD]" in reply:
                    anim = random.choice(MOVES["LOSE"])

                # Clean the actual spoken text by removing tags.
                speech = (
                    reply.replace("[DANCE]", "")
                    .replace("[DAB]", "")
                    .replace("[SNEEZE]", "")
                    .replace("[CLAP]", "")
                    .replace("[SAD]", "")
                    .strip()
                )

                # LLM-based rematch handling still exists as fallback.
                # In practice, the direct handler above should handle game_over reliably first.
                if "ACTION_RESET" in reply:
                    print("[Brain] 🟢 Rematch!")
                    reactor.callFromThread(session.call, "rie.dialogue.say", text="Here we go again!")
                    trigger_reset()

                    # IMPORTANT CHANGE:
                    # - Same auto-stand behavior after reset for the LLM fallback path.
                    reactor.callFromThread(
                        reactor.callLater,
                        0.6,
                        safe_play_behavior,
                        session,
                        "BlocklyStand",
                        True,
                        "post-reset auto-stand (LLM fallback)"
                    )

                    reset_per_game_flags()
                    rematch_mode = False

                elif "ACTION_QUIT" in reply:
                    print("[Brain] 🔴 Quit.")
                    reactor.callFromThread(session.call, "rie.dialogue.say", text="Fine, bye.")
                    reactor.callFromThread(session.call, "rom.optional.behavior.play", name="BlocklyCrouch", sync=False)
                    last_posture = "crouch"

                else:
                    if speech:
                        print(f"[Brain] 🤖 Robot: {speech}")
                        reactor.callFromThread(session.call, "rie.dialogue.say", text=speech)

                    # If an animation was requested and passes our gating, schedule it slightly after speech
                    # so the audio doesn't get cut.
                    if anim and _should_allow_tag_behavior(anim):
                        reactor.callFromThread(reactor.callLater, TAG_BEHAVIOR_DELAY, do_behavior, session, anim)

                time.sleep(1.0)
                is_speaking = False

            except Exception:
                is_speaking = False

    print("[Brain] listen_loop exited.")

def do_behavior(session, name):
    # Runs in reactor thread (scheduled by reactor.callLater)
    # IMPORTANT CHANGE:
    # - Use safe_play_behavior for better logs + posture tracking.
    print(f"[Brain] 🕺 Triggered: {name}")
    safe_play_behavior(session, name, sync=True, why="LLM-tagged behavior")

# --- WAMP SETUP ---

session_global = None

@inlineCallbacks
def main(session, details):
    """
    Entry point when WAMP connects.
    - Set robot to a known baseline pose
    - Start listen_loop in a thread if using local mic
    - Start game_loop in the reactor
    """
    global session_global
    session_global = session
    print(f"[Brain] Connected to Robot {ROBOT_REALM}")

    # IMPORTANT CHANGE:
    # - Use safe_play_behavior so failures are visible and posture tracking stays correct.
    yield safe_play_behavior(session, "BlocklyStand", sync=True, why="startup baseline")

    if USE_LOCAL_MIC:
        reactor.callInThread(listen_loop, session)

    yield game_loop(session)

def _on_leave(session, details):
    print("[Brain] WAMP left:", details)
    request_shutdown("wamp leave")

def _on_disconnect(session, was_clean):
    print("[Brain] WAMP disconnected. clean=", was_clean)
    request_shutdown("wamp disconnect")

wamp = Component(
    transports=[{"url": WAMP_URL, "serializers": ["msgpack"], "max_retries": 999999}],
    realm=ROBOT_REALM,
)
wamp.on_join(main)
wamp.on_leave(_on_leave)
wamp.on_disconnect(_on_disconnect)

if __name__ == "__main__":
    run([wamp])
