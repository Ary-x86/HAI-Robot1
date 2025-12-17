# robot/robot_brain.py

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
from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from twisted.internet import threads, reactor
from autobahn.twisted.util import sleep as tSleep

# OpenAI
from openai import OpenAI

load_dotenv()

# top-level globals
import re
user_name = None

def maybe_extract_name(text: str) -> str | None:
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

NAME_ASK_RE = re.compile(r"\b(what'?s|what is)\s+your\s+name\b|\bdrop\s+your\s+name\b", re.I)
PLACEHOLDER_RE = re.compile(r"\[player name\]|\[player_name\]|\{player_name\}|\{player name\}", re.I)

def sanitize_midgame_taunt(t: str) -> str:
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
OPENING_TURNS = 4          # first 4 turns -> very chatty
OPENING_SPEAK_CHANCE = 0.95
OPENING_FADE_TURNS = 6     # then fade down over next 6 turns to normal

def opening_speak_multiplier(turn: int) -> float:
    """
    turn: 0-based turn index from backend
    Returns a multiplier / override factor for early-game talking.
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
_prev_game_over_seen = None


def reset_per_game_flags():
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

# --- TUNING (BASELINES) ---
MOVE_SPEAK_CHANCE = 0.33   # baseline; will be modulated dynamically
BEHAVIOR_CHANCE   = 0.1   # baseline; will be modulated dynamically
SFX_CHANCE        = 0.25   # baseline; will be modulated dynamically

IDLE_TIMEOUT = 20.0
IDLE_INTERVAL = 15.0

# --- ANTI-SPAM / WAIT TIMER ---
WAIT_SFX_CHANCE = 0.15     # baseline; will be modulated dynamically
WAIT_SFX_DELAY_MIN = 4.0
WAIT_SFX_DELAY_MAX = 40.0

SFX_COOLDOWN = 10.0


# --- BEHAVIOR ANTI-SPAM ---
BEHAVIOR_COOLDOWN = 25.0          # seconds between any two behaviors (big impact)
TAG_BEHAVIOR_MAX_CHANCE = 0.12    # even if LLM tags, only do it sometimes
TAG_BEHAVIOR_DELAY = 0.6          # wait a bit so speech isn't cut off

last_behavior_time = 0.0
last_behavior_name = None


client = OpenAI(api_key=OPENAI_API_KEY)
recognizer = sr.Recognizer()

# --- SOUND EFFECTS ---
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
MOVES = {
    "WIN_BIG": ["BlocklyDiscoDance", "BlocklyStarWars", "BlocklyMacarena"],
    "WIN_SMALL": ["BlocklyDab", "BlocklyHappy", "BlocklyApplause"],
    "LOSE": ["BlocklyCrouch", "BlocklyShrug", "BlocklySad"],
    "ANNOY": ["BlocklySneeze", "BlocklySaxophone", "BlocklyTurnAround"],
    "IDLE": ["BlocklyTaiChiChuan", "BlocklyStand"],
}

# --- GLOBAL STATE ---
current_game_state = {"ai_lead": 0, "game_over": False}
last_turn_index = -1
is_speaking = False
rematch_mode = False
last_interaction_time = time.time()

# --- SHUTDOWN + WAIT TIMER + COOLDOWN ---
shutdown_event = threading.Event()

wait_sfx_due = None
wait_sfx_turn = None
wait_sfx_category = "WAIT"
last_sfx_time = 0.0

# --- DYNAMIC PROFILE (UPDATED EACH TICK) ---
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
    Baselines stay respected; everything is clamped to [0,1].
    """
    mood = _mood_from_lead(lead)

    # Normalize into [-1, 1] using a "meaningful" lead scale.
    # (Connect 4 lead feels real at ~6+)
    adv = _clamp(lead / 6.0, -1.0, 1.0)

    # More talk + more moves when winning, less when losing
    move_speak = _clamp01(MOVE_SPEAK_CHANCE + 0.06 * adv)  # ~0.27..0.39           # +/- ~0.18
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
    This is where the robot *feels* different:
    - winning => celebratory / cocky (WIN)
    - close   => tension/annoy (ANNOY)
    - losing  => bored/deflated (WAIT)
    """
    if mood in ("winning_big", "winning"):
        # Mostly WIN but sometimes ANNOY so it's not a casino
        return "WIN" if random.random() < 0.75 else "ANNOY"
    if mood == "close":
        return "ANNOY" if random.random() < 0.85 else "WAIT"
    # losing / losing_big
    return "WAIT" if random.random() < 0.85 else "ANNOY"

def choose_idle_sfx_category(mood: str) -> str:
    # Idle should reflect the state too.
    if mood in ("winning_big", "winning"):
        return "ANNOY"  # “hurry up” energy
    if mood == "close":
        return "ANNOY"
    return "WAIT"       # losing => deflated/bored

def dynamic_prompt_suffix(lead: int) -> str:
    """
    Very cheap win: the LLM prompt changes based on lead magnitude.
    No big refactor needed.
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
    try:
        res = requests.get(f"{API_URL}/state", timeout=0.5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {}

def trigger_reset():
    try:
        requests.post(f"{API_URL}/reset", timeout=1)
    except Exception:
        pass

def generate_response(user_text, context_type="gameplay"):
    """
    Same behavior, but now prompt style changes dynamically with lead.
    Also keeps your model fallback.
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
    global wait_sfx_due, wait_sfx_turn
    wait_sfx_due = None
    wait_sfx_turn = None

# -------------------------
# Actuation
# -------------------------

@inlineCallbacks
def play_sfx(session, category, force=False):
    """Plays random sound w/ cooldown + dynamic chance + no overlap with speech."""
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
    """
    move_speak = float(profile.get("move_speak_chance", MOVE_SPEAK_CHANCE))

    # Opening hype: hard override for first moves, then fade
    mult = opening_speak_multiplier(turn)
    if mult is None:
        move_speak = OPENING_SPEAK_CHANCE
    else:
        move_speak = _clamp01(move_speak * mult)

    behave      = float(profile.get("behavior_chance", BEHAVIOR_CHANCE))

    global is_speaking

    if text and random.random() < move_speak:
        print(f"[Brain] 🤖 Speaking: {text}")
        is_speaking = True
        try:
            yield session.call("rie.dialogue.say", text=text)
        finally:
            is_speaking = False


    if sfx_category:
        yield play_sfx(session, sfx_category, force=True)

    if anim_name and random.random() < behave:
        print(f"[Brain] 🕺 Performing: {anim_name}")
        yield session.call("rom.optional.behavior.play", name=anim_name, sync=True)

@inlineCallbacks
def perform_idle_action(session, profile: dict):
    """Triggers when bored; now reflects mood."""
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
        yield session.call("rom.optional.behavior.play", name=anim, sync=True)

# -------------------------
# Main loops
# -------------------------

@inlineCallbacks
def game_loop(session):
    global last_turn_index, current_game_state, rematch_mode, is_speaking, last_interaction_time, dynamic_profile
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

                    # 1) GAME OVER ROUTINE
                    if game_over and not rematch_mode:
                        print("[Brain] 🏁 GAME OVER.")
                        rematch_mode = True
                        cancel_wait_sfx()

                        if winner == -1:
                            yield play_sfx(session, "WIN", force=True)
                            yield session.call("rie.dialogue.say", text="Good game. Come on, let’s shake hands.")
                            yield session.call("rom.optional.behavior.play", name="BlocklyDab", sync=True)
                            yield session.call("rie.dialogue.say", text="Just kidding. I don’t shake hands with losers.")
                            yield session.call("rom.optional.behavior.play", name="BlocklyGangnamStyle", sync=True)
                            yield session.call("rom.optional.behavior.play", name="BlocklyCrouch", sync=True)

                        elif winner == 1:
                            yield play_sfx(session, "LOSE", force=True)
                            yield session.call("rie.dialogue.say", text="No way... I demand a recount.")
                            yield session.call("rom.optional.behavior.play", name="BlocklyCrouch", sync=True)

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
                        yield perform_midgame_event(session, taunt, anim, sfx_category=None, profile=dynamic_profile, turn=turn)

                # After reset happens (game_over false), leave rematch mode
                if not game_over and rematch_mode:
                    rematch_mode = False
                    cancel_wait_sfx()
                    if turn >= 0:
                        schedule_wait_sfx(turn, dynamic_profile)

        except Exception as e:
            print(f"[Brain] game_loop error: {e}")

        yield tSleep(0.5)


def _should_allow_tag_behavior(anim: str) -> bool:
    """Make LLM-tagged behaviors a rare, state-aware surprise."""
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
    global is_speaking, rematch_mode, last_interaction_time

    with sr.Microphone() as source:
        print("[Brain] 🎧 Calibrating...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[Brain] 👂 Listening!")

        while not shutdown_event.is_set():
            try:
                try:
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=5)
                except sr.WaitTimeoutError:
                    continue

                try:
                    text = recognizer.recognize_google(audio)
                    last_interaction_time = time.time()
                    print(f"[Brain] 🗣️ You: {text}")
                    # Peek game state NOW to decide "blowout interrupt"
                    state = fetch_game_state()
                    lead_now = int(state.get("ai_lead", 0) or 0)
                    game_over_now = bool(state.get("game_over", False))

                    # Reset per-game flags when a new game starts:
                    # Detect transition: game_over True -> False (after /reset)
                    global _prev_game_over_seen
                    if _prev_game_over_seen is None:
                        _prev_game_over_seen = game_over_now
                    else:
                        if _prev_game_over_seen and not game_over_now:
                            reset_per_game_flags()
                        _prev_game_over_seen = game_over_now

                    # Only do this midgame (not during rematch prompt, not after game_over)
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

                global user_name
                if user_name is None:
                    name = maybe_extract_name(text)
                    if name:
                        user_name = name
                        print(f"[Brain] ✅ Learned user_name={user_name}")


                if is_speaking:
                    reactor.callFromThread(session.call, "rie.dialogue.stop")

                is_speaking = True
                context = "rematch" if rematch_mode else "gameplay"
                reply = generate_response(text, context) or ""

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

                speech = (
                    reply.replace("[DANCE]", "")
                    .replace("[DAB]", "")
                    .replace("[SNEEZE]", "")
                    .replace("[CLAP]", "")
                    .replace("[SAD]", "")
                    .strip()
                )

                if "ACTION_RESET" in reply:
                    print("[Brain] 🟢 Rematch!")
                    reactor.callFromThread(session.call, "rie.dialogue.say", text="Here we go again!")
                    trigger_reset()
                    rematch_mode = False

                elif "ACTION_QUIT" in reply:
                    print("[Brain] 🔴 Quit.")
                    reactor.callFromThread(session.call, "rie.dialogue.say", text="Fine, bye.")
                    reactor.callFromThread(session.call, "rom.optional.behavior.play", name="BlocklyCrouch", sync=False)

                else:
                    if speech:
                        print(f"[Brain] 🤖 Robot: {speech}")
                        reactor.callFromThread(session.call, "rie.dialogue.say", text=speech)

                    if anim and _should_allow_tag_behavior(anim):
                        reactor.callFromThread(reactor.callLater, TAG_BEHAVIOR_DELAY, do_behavior, session, anim)


                time.sleep(1.0)
                is_speaking = False

            except Exception:
                is_speaking = False

    print("[Brain] listen_loop exited.")

def do_behavior(session, name):
    print(f"[Brain] 🕺 Triggered: {name}")
    session.call("rom.optional.behavior.play", name=name, sync=True)

# --- WAMP SETUP ---

session_global = None

@inlineCallbacks
def main(session, details):
    global session_global
    session_global = session
    print(f"[Brain] Connected to Robot {ROBOT_REALM}")

    yield session.call("rom.optional.behavior.play", name="BlocklyStand")

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
