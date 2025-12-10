# robot/robot_client.py
import json
import os
import sys

# Add the project root to sys.path to allow imports if needed, 
# though we mostly need dotenv here.
from dotenv import load_dotenv

from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep as tSleep
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.internet import reactor

# 1. Load environment variables
load_dotenv()

STATE_URL = b"http://127.0.0.1:8000/state"
RESET_URL = b"http://127.0.0.1:8000/reset"

# 2. Get Realm from .env (Fallback to the one in your README if missing)
ROBOT_REALM = os.getenv("RIDK_REALM", "rie.691ce2fd82c3bec9b226dfc9")
WAMP_URL = os.getenv("RIDK_WAMP_URL", "ws://wamp.robotsindeklas.nl")

print(f"[robot] Connecting to Realm: {ROBOT_REALM}")

last_turn_index = -1

def _parse_json(body_bytes: bytes):
    return json.loads(body_bytes.decode("utf-8"))

@inlineCallbacks
def reset_game():
    agent = Agent(reactor)
    try:
        resp = yield agent.request(
            b"POST",
            RESET_URL,
            Headers({b"User-Agent": [b"robot-client"]}),
            None,
        )
        body = yield readBody(resp)
        print("[robot] Game reset response:", body[:120])
    except Exception as e:
        print("[robot] Error while calling /reset:", e)

@inlineCallbacks
def handle_snapshot(session, snapshot: dict):
    game_over = snapshot["game_over"]
    winner = snapshot["winner"]
    taunt = snapshot.get("last_taunt") or ""

    # Keep robot in a neutral "ready" posture
    yield session.call("rom.optional.behavior.play", name="BlocklyStand")

    if not game_over:
        if taunt:
            print(f"[robot] Saying: {taunt}")
            yield session.call("rie.dialogue.say", text=taunt)
        return

    # --- Game over branches ---
    if winner == -1: # AI won
        if taunt:
            yield session.call("rie.dialogue.say", text=taunt)
        yield session.call("rie.dialogue.say", text="Good game. Let's shake hands.")
        yield session.call("rom.optional.behavior.play", name="BlocklyDab")
        yield session.call("rie.dialogue.say", text="Just kidding.")
        yield session.call("rom.optional.behavior.play", name="BlocklyCrouch")
        yield reset_game()

    elif winner == 1: # Human won
        if taunt:
            yield session.call("rie.dialogue.say", text=taunt)
        yield session.call("rom.optional.behavior.play", name="BlocklyWaveRightArm")
        yield session.call("rie.dialogue.say", text="You beat me. Rematch next time.")
        yield reset_game()

    elif winner == "draw":
        if taunt:
            yield session.call("rie.dialogue.say", text=taunt)
        yield session.call("rie.dialogue.say", text="Draw game. Boring.")
        yield reset_game()

@inlineCallbacks
def poll_loop(session):
    global last_turn_index
    agent = Agent(reactor)
    
    print(f"[robot] Polling {STATE_URL.decode()}...")

    while True:
        try:
            response = yield agent.request(
                b"GET",
                STATE_URL,
                Headers({b"User-Agent": [b"robot-client"]}),
                None,
            )
            body = yield readBody(response)
            snapshot = _parse_json(body)
            ti = snapshot["turn_index"]

            if ti > last_turn_index:
                last_turn_index = ti
                print(f"[robot] New turn_index = {ti}")
                yield handle_snapshot(session, snapshot)

        except Exception as e:
            print("[robot] Error while polling state:", e)

        yield tSleep(1.5)

@inlineCallbacks
def main(session, details):
    print("[robot] Connected to RIDK WAMP.")
    yield poll_loop(session)
    session.leave()

wamp = Component(
    transports=[{
        "url": WAMP_URL,
        "serializers": ["msgpack"],
        "max_retries": 0,
    }],
    realm=ROBOT_REALM,
)

wamp.on_join(main)

if __name__ == "__main__":
    run([wamp])