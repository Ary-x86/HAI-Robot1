# robot/robot_client.py
#
# terminal 1 – web + game:
#   uvicorn app.main:app --reload
#
# terminal 2 – robot brain:
#   python robot/robot_client.py

import json

from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep as tSleep
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.internet import reactor

STATE_URL = b"http://127.0.0.1:8000/state"
RESET_URL = b"http://127.0.0.1:8000/reset"

# your robot realm from the portal:
ROBOT_REALM = "rie.691d1e4d82c3bec9b226e0de"

last_turn_index = -1  # remember last processed turn


def _parse_json(body_bytes: bytes):
    return json.loads(body_bytes.decode("utf-8"))


@inlineCallbacks
def reset_game():
    """
    Ask the FastAPI backend to reset the Connect-4 game.
    """
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
    """
    Decide what the robot should say/do based on game snapshot.
    LLM-generated banter comes in via snapshot['last_taunt'].
    """
    game_over = snapshot["game_over"]
    winner = snapshot["winner"]
    taunt = snapshot.get("last_taunt") or ""

    # Keep robot in a neutral "ready" posture
    yield session.call("rom.optional.behavior.play", name="BlocklyStand")

    if not game_over:
        # Mid-game or intro → just say the taunt line
        if taunt:
            yield session.call("rie.dialogue.say", text=taunt)
        return

    # --- Game over branches ---

    if winner == -1:
        # Robot / AI won
        if taunt:
            yield session.call("rie.dialogue.say", text=taunt)

        # Fake handshake troll
        yield session.call(
            "rie.dialogue.say",
            text="Good game. Come on, let’s shake hands."
        )
        yield session.call("rom.optional.behavior.play", name="BlocklyDab")
        yield session.call(
            "rie.dialogue.say",
            text="Just kidding. I don’t shake hands with losers."
        )

        yield session.call("rom.optional.behavior.play", name="BlocklyGangnamStyle")
        
        yield session.call("rom.optional.behavior.play", name="BlocklyCrouch")

        # Prepare next round
        yield reset_game()

    elif winner == 1:
        # Human won
        if taunt:
            yield session.call("rie.dialogue.say", text=taunt)
        yield session.call("rom.optional.behavior.play", name="BlocklyWaveRightArm")
        yield session.call(
            "rie.dialogue.say",
            text="You actually beat me… alright, rematch next time."
        )
        yield reset_game()

    elif winner == "draw":
        # Draw
        if taunt:
            yield session.call("rie.dialogue.say", text=taunt)
        yield session.call("rom.optional.behavior.play", name="BlocklyWaveRightArm")
        yield session.call(
            "rie.dialogue.say",
            text="Draw game. Nobody clutched, that’s kinda mid."
        )
        yield reset_game()


@inlineCallbacks
def poll_loop(session):
    """
    Poll the FastAPI server for updated game state and react when it changes.
    """
    global last_turn_index

    agent = Agent(reactor)

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
                print(f"[robot] New turn_index = {ti}, reacting…")
                yield handle_snapshot(session, snapshot)

        except Exception as e:
            print("[robot] Error while polling state:", e)

        # don't hammer the server
        yield tSleep(1.5)


@inlineCallbacks
def main(session, details):
    print("[robot] Connected to RIDK WAMP, starting poll loop.")
    yield poll_loop(session)
    # poll_loop never returns unless there's a fatal error
    session.leave()


# --- WAMP connection object ---

wamp = Component(
    transports=[{
        "url": "ws://wamp.robotsindeklas.nl",
        "serializers": ["msgpack"],
        "max_retries": 0,
    }],
    realm=ROBOT_REALM,
)

wamp.on_join(main)

if __name__ == "__main__":
    run([wamp])
