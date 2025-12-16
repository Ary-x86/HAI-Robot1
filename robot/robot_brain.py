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

# --- CONFIG ---
USE_LOCAL_MIC = True  # Set False for physical robot
ROBOT_REALM = os.getenv("RIDK_REALM", "rie.693b0e88a7cba444073b9c99")
WAMP_URL = os.getenv("RIDK_WAMP_URL", "ws://wamp.robotsindeklas.nl")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
API_URL = "http://127.0.0.1:8000"

# --- TUNING ---
MOVE_SPEAK_CHANCE = 0.5   # 50% chance to speak text after a move
BEHAVIOR_CHANCE = 0.25    # 25% chance to do a physical move (Occasional/Surprising)
SFX_CHANCE = 0.80         # 80% chance to play a sound effect (Frequent)

IDLE_TIMEOUT = 12.0       # Seconds of silence before "Bored" logic kicks in
IDLE_INTERVAL = 8.0       # Seconds between bored events

# --- NEW (ANTI-SPAM / WAIT TIMER) ---
WAIT_SFX_CHANCE = 0.80
WAIT_SFX_DELAY_MIN = 0.0
WAIT_SFX_DELAY_MAX = 15.0

SFX_COOLDOWN = 4.0        # Minimum seconds between any two SFX calls

client = OpenAI(api_key=OPENAI_API_KEY)
recognizer = sr.Recognizer()

# --- SOUND EFFECTS ---
# Full URLs as requested
SOUNDS = {
    "WIN": [
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/tmp_7901-951678082.mp3",  # MLG Airhorn
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/vine-boom.mp3",  # Vine Boom
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/mi-bombo.mp3",  # Wow
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/fahhh_KcgAXfs.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/let-me-know.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/meme-de-creditos-finales.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/rat-dance-music.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/wrong-answer-sound-effect.mp3",
    ],
    "LOSE": [
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/downer_noise.mp3",  # Sad Violin
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/spongebob-fail.mp3",  # GTA Wasted
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/sponge-stank-noise.mp3",  # Spongebob Fail
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/another-one_dPvHt2Z.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/baby-laughing-meme.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/bye-bye-lumi-athena-sfx.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/ny-video-online-audio-converter.mp3",
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/sitcom-laughing-1.mp3",
    ],
    "ANNOY": [
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/awkward-moment.mp3",  # Discord
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/tuco-get-out.mp3",  # Cartoon Slip
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/oh-my-god-bro-oh-hell-nah-man.mp3",  # Bruh
        "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/%EF%BC%82Adrian%EF%BC%82%20Sound%20Effect%20%5BAQXqiVtF2DI%5D.mp3",  # Adrian
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

# --- NEW GLOBALS (SHUTDOWN + WAIT TIMER + COOLDOWN) ---
shutdown_event = threading.Event()

wait_sfx_due = None         # epoch seconds when WAIT SFX should fire
wait_sfx_turn = None        # the turn_index the timer belongs to
last_sfx_time = 0.0         # for cooldown


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
    Keeps your original behavior, but adds a safe fallback if the chosen model errors (e.g., no access).
    """
    try:
        if context_type == "rematch":
            system_msg = "If YES: 'ACTION_RESET'. If NO: 'ACTION_QUIT'. Else ask again."
            context = f"User said: {user_text}"
        else:
            state = fetch_game_state()
            lead = state.get("ai_lead", 0)
            system_msg = (
                "You are 'Robo', a cocky, competitive Connect 4 robot. "
                "Keep responses SHORT (1 sentence). "
                "You can perform actions by ending your sentence with tags: "
                "[DANCE], [DAB], [SNEEZE], [CLAP], [SAD]. "
                "Only use tags if the situation is extreme."
            )
            context = f"Score Lead: {lead}. User said: {user_text}"

        try:
            response = client.responses.create(
                model=OPENAI_MODEL,
                instructions=system_msg,
                input=context,
                max_output_tokens=60,
            )
            return response.output_text or ""
        except Exception as e:
            # Fallback to gpt-4o-mini if model is unavailable / 404-ish
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


def schedule_wait_sfx(turn: int):
    """
    Schedules a WAIT SFX for the CURRENT turn_index.
    If any new move happens (turn_index changes), we cancel/reschedule.
    """
    global wait_sfx_due, wait_sfx_turn
    wait_sfx_turn = turn

    if random.random() < WAIT_SFX_CHANCE:
        wait_sfx_due = time.time() + random.uniform(WAIT_SFX_DELAY_MIN, WAIT_SFX_DELAY_MAX)
    else:
        wait_sfx_due = None


def cancel_wait_sfx():
    global wait_sfx_due, wait_sfx_turn
    wait_sfx_due = None
    wait_sfx_turn = None


@inlineCallbacks
def play_sfx(session, category, force=False):
    """Plays a random sound from the category, with cooldown + no overlap with speech."""
    global last_sfx_time

    if shutdown_event.is_set():
        return

    # No SFX while speaking (prevents stacking)
    if is_speaking:
        return

    # Cooldown to stop spam even if logic triggers frequently
    now = time.time()
    if now - last_sfx_time < SFX_COOLDOWN:
        return

    # Chance Check (kept)
    if not force and random.random() > SFX_CHANCE:
        return

    url_list = SOUNDS.get(category, [])
    if url_list:
        url = random.choice(url_list)
        print(f"[Brain] 🎵 Playing SFX ({category}): {url}")
        last_sfx_time = now
        yield session.call("rom.actuator.audio.stream", url=url, sync=False)


@inlineCallbacks
def perform_midgame_event(session, text, anim_name, sfx_category):
    """
    Handles events that happen after a Game Move.
    Uses separate probabilities for Speech, Sound, and Movement.
    """
    # 1. Speech (50% chance)
    if text and random.random() < MOVE_SPEAK_CHANCE:
        print(f"[Brain] 🤖 Speaking: {text}")
        yield session.call("rie.dialogue.say", text=text)

    # 2. Sound Effect (optional; for midgame we typically pass None now)
    if sfx_category and random.random() < SFX_CHANCE:
        yield play_sfx(session, sfx_category, force=True)

    # 3. Behavior (25% chance - Occasional/Surprise)
    if anim_name and random.random() < BEHAVIOR_CHANCE:
        print(f"[Brain] 🕺 Performing: {anim_name}")
        yield session.call("rom.optional.behavior.play", name=anim_name, sync=True)


@inlineCallbacks
def perform_idle_action(session):
    """Triggers when bored."""
    print("[Brain] ⏳ Robot is bored...")

    # 50/50 chance between Annoying Sound or Waiting Sound
    if random.choice([True, False]):
        yield play_sfx(session, "ANNOY", force=True)
    else:
        yield play_sfx(session, "WAIT", force=True)

    # Occasionally do a small idle move
    if random.random() < 0.3:
        anim = random.choice(MOVES["IDLE"])
        yield session.call("rom.optional.behavior.play", name=anim, sync=True)


@inlineCallbacks
def game_loop(session):
    global last_turn_index, current_game_state, rematch_mode, is_speaking, last_interaction_time
    print("[Brain] 🎮 Game Loop Active")

    # schedule for initial idle state (turn might be -1 until first fetch)
    cancel_wait_sfx()

    while not shutdown_event.is_set():
        try:
            state = yield threads.deferToThread(fetch_game_state)
            if state:
                current_game_state = state
                turn = state.get("turn_index", -1)
                game_over = state.get("game_over", False)
                taunt = state.get("last_taunt", "")
                lead = state.get("ai_lead", 0)
                winner = state.get("winner")

                # --- FIRE WAIT SFX IF DUE (only if no move happened since scheduling) ---
                if (
                    wait_sfx_due is not None
                    and not game_over
                    and not rematch_mode
                    and not is_speaking
                    and turn == wait_sfx_turn
                    and time.time() >= wait_sfx_due
                ):
                    yield play_sfx(session, "WAIT", force=True)
                    cancel_wait_sfx()

                # --- IDLE CHECK (kept, but cooldown will limit spam) ---
                if (
                    not game_over
                    and not is_speaking
                    and (time.time() - last_interaction_time > IDLE_TIMEOUT)
                ):
                    yield perform_idle_action(session)
                    # push next idle check into the future to avoid constant triggering
                    last_interaction_time = time.time() + IDLE_INTERVAL

                # --- NEW TURN DETECTED ---
                if turn > last_turn_index:
                    last_turn_index = turn
                    last_interaction_time = time.time()

                    # Any new move cancels & reschedules WAIT timer
                    cancel_wait_sfx()
                    if not game_over and not rematch_mode:
                        schedule_wait_sfx(turn)

                    # 1. GAME OVER ROUTINE (ONLY place WIN/LOSE SFX happen)
                    if game_over and not rematch_mode:
                        print("[Brain] 🏁 GAME OVER.")
                        rematch_mode = True
                        cancel_wait_sfx()

                        if winner == -1:  # AI Won
                            # Play WIN Sound FIRST
                            yield play_sfx(session, "WIN", force=True)

                            # Handshake Troll Routine
                            yield session.call("rie.dialogue.say", text="Good game. Come on, let’s shake hands.")
                            yield session.call("rom.optional.behavior.play", name="BlocklyDab", sync=True)
                            yield session.call("rie.dialogue.say", text="Just kidding. I don’t shake hands with losers.")
                            yield session.call("rom.optional.behavior.play", name="BlocklyGangnamStyle", sync=True)
                            yield session.call("rom.optional.behavior.play", name="BlocklyCrouch", sync=True)

                        elif winner == 1:  # Human Won
                            yield play_sfx(session, "LOSE", force=True)
                            yield session.call("rie.dialogue.say", text="No way... I demand a recount.")
                            yield session.call("rom.optional.behavior.play", name="BlocklyCrouch", sync=True)

                        else:
                            yield play_sfx(session, "ANNOY", force=True)
                            yield session.call("rie.dialogue.say", text="Draw game.")

                        yield tSleep(1.0)
                        yield session.call("rie.dialogue.say", text="Do you want a rematch? Say yes.")

                    # 2. MID-GAME MOVE (NO WIN/LOSE SFX HERE ANYMORE)
                    elif not rematch_mode and taunt and not is_speaking:
                        anim = None

                        if lead >= 6:
                            anim = random.choice(MOVES["WIN_BIG"])
                        elif lead <= -6:
                            anim = random.choice(MOVES["LOSE"])
                        elif lead > 2:
                            anim = random.choice(MOVES["WIN_SMALL"])
                        elif lead < -2:
                            anim = "BlocklyShrug"
                        else:
                            # Close game: sometimes do annoy behavior, but keep SFX quiet (WAIT timer handles sound)
                            if random.random() < 0.2:
                                anim = random.choice(MOVES["ANNOY"])

                        yield perform_midgame_event(session, taunt, anim, sfx_category=None)

                # After reset happens (game_over false), leave rematch mode
                if not game_over and rematch_mode:
                    rematch_mode = False
                    # New round: schedule WAIT timer for the current turn
                    cancel_wait_sfx()
                    if turn >= 0:
                        schedule_wait_sfx(turn)

        except Exception as e:
            # Don’t silently swallow forever; at least show something helpful
            print(f"[Brain] game_loop error: {e}")

        yield tSleep(0.5)


def listen_loop(session):
    global is_speaking, rematch_mode, last_interaction_time

    with sr.Microphone() as source:
        print("[Brain] 🎧 Calibrating...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[Brain] 👂 Listening!")

        while not shutdown_event.is_set():
            try:
                # IMPORTANT: timeout prevents the thread from blocking forever (Ctrl-C now works)
                try:
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=5)
                except sr.WaitTimeoutError:
                    continue

                try:
                    text = recognizer.recognize_google(audio)
                    last_interaction_time = time.time()
                    print(f"[Brain] 🗣️ You: {text}")
                except Exception:
                    continue

                if is_speaking:
                    reactor.callFromThread(session.call, "rie.dialogue.stop")

                is_speaking = True
                context = "rematch" if rematch_mode else "gameplay"
                reply = generate_response(text, context) or ""

                # Parse Tags
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
                    # NORMAL CONVERSATION FLOW
                    if speech:
                        print(f"[Brain] 🤖 Robot: {speech}")
                        reactor.callFromThread(session.call, "rie.dialogue.say", text=speech)

                    # Only tagged behavior here (kept)
                    if anim:
                        reactor.callFromThread(do_behavior, session, anim)

                time.sleep(1.0)
                is_speaking = False

            except Exception as e:
                is_speaking = False
                # keep running, but show one-line debug
                # (speech libs are noisy sometimes)
                # print(f"[Brain] listen_loop error: {e}")

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


# Optional: shut down cleanly if component leaves/disconnects
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
