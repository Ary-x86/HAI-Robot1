# robot_client.py

# terminal 1 – web + game
# uvicorn app.main:app --reload

# # terminal 2 – robot brain
# python robot_client.py


import json

from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep as tSleep
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
from twisted.internet import reactor

API_URL = b"http://127.0.0.1:8000/state"

# your robot realm from the portal:
ROBOT_REALM = "rie.6918c48a375fb38004f5389f"

last_turn_index = -1  # remember last processed turn


def _parse_json(body_bytes: bytes):
    return json.loads(body_bytes.decode("utf-8"))


@inlineCallbacks
def handle_snapshot(session, snapshot: dict):
    """
    Decide what the robot should say/do based on game snapshot.
    """
    game_over = snapshot["game_over"]
    winner = snapshot["winner"]
    ai_lead = snapshot["ai_lead"]

    # Keep robot in a "ready" posture
    yield session.call("rom.optional.behavior.play", name="BlocklyStand")

    if not game_over:
        # Ongoing game, just trash talk based on lead
        if ai_lead > 15:
            text = "I'm farming you, this is brutal."
        elif ai_lead > 7:
            text = "You're kind of losing, you know that right?"
        elif ai_lead < -15:
            text = "Okay, wait, you're actually destroying me. Respect."
        elif ai_lead < -7:
            text = "Hmm, you're ahead. Don't get cocky though."
        else:
            text = "Close game so far. But I still think you'll fold in the end."

        yield session.call("rie.dialogue.say", text=text)
        return

    # Game over → different behaviour
    if winner == -1:
        # Robot / AI won
        yield session.call("rie.dialogue.say",
                           text="Good game. Come on, let's shake hands.")
        # fake handshake using dab (we don't know the real handshake behavior)
        yield session.call("rom.optional.behavior.play", name="BlocklyDab")
        yield session.call("rie.dialogue.say",
                           text="Just kidding. I don't shake hands with losers.")
        yield session.call("rom.optional.behavior.play", name="BlocklyCrouch")

    elif winner == 1:
        # Human won
        yield session.call("rie.dialogue.say",
                           text="Okay, okay. You actually beat me. That was clean.")
        yield session.call("rom.optional.behavior.play", name="BlocklyWaveRightArm")
        yield session.call("rie.dialogue.say",
                           text="Don't get used to it though, rematch next time.")

    elif winner == "draw":
        yield session.call("rie.dialogue.say",
                           text="Draw. Mid game. Nobody wins, nobody loses.")
        yield session.call("rom.optional.behavior.play", name="BlocklyWaveRightArm")

    # you can add more drama here if you want


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
                API_URL,
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
