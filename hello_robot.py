from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep

@inlineCallbacks
def main(session, details):
    # Put robot in some pose (optional)
    yield session.call("rom.optional.behavior.play", name="BlocklyRest")

    # Start audio stream
    yield session.call(
        "rom.actuator.audio.stream",
        url="https://stream.qmusic.nl/qmusic/mp3",
        sync=False,
    )

    # Let it play a bit
    yield sleep(10)

    # Stop audio
    yield session.call("rom.actuator.audio.stop")

    # Disconnect
    session.leave()

wamp = Component(
    transports=[{
        "url": "ws://wamp.robotsindeklas.nl",
        "serializers": ["msgpack"],
        "max_retries": 0,
    }],
    realm="rie.6918c48a375fb38004f5389f",
)

wamp.on_join(main)

if __name__ == "__main__":
    run([wamp])
