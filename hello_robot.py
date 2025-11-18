from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep

# tune these if you want
MUSIC_SECONDS = 40      # roughly how long you want the song+dance to last
DAB_SECONDS_EST = 4.0   # rough duration of one BlocklyDab animation in seconds

@inlineCallbacks
def main(session, details):
    # 1. Make sure the robot is standing
    yield session.call("rom.optional.behavior.play", name="BlocklyStand")
    yield sleep(1.0)

    # 2. Intro line
    yield session.call(
        "rie.dialogue.say",
        text="yo bro i really want to eat some cheeseburgers."
    )

    # 3. Start the music (non-blocking)
    # yield session.call(
    #     "rom.actuator.audio.stream",
    #     url=(
    #         "https://raw.githubusercontent.com/Ary-x86/HAI-Robot1/"
    #         "refs/heads/main/audio/"
    #         "i%20want%20some%20cheeseburgers%20just%20to%20eat%20"
    #         "%28clean%20version%21%EF%BC%9F%29%20%5Buzl55C2ekFE%5D.mp3"
    #     ),
    #     sync=False,
    # )

    yield session.call(
        "rom.actuator.audio.stream",
        url=(
            # "https://raw.githubusercontent.com/Ary-x86/HAI-Robot1/refs/heads/main/audio/i%20want%20some%20cheeseburgers%20just%20to%20eat%20%28clean%20version%21%EF%BC%9F%29%20%5Buzl55C2ekFE%5D.mp3",
            "https://raw.githubusercontent.com/Ary-x86/HAI-Robot1/refs/heads/main/audio/i%20want%20some%20cheeseburgers%20just%20to%20eat%20(clean%20version!%EF%BC%9F)%20%5Buzl55C2ekFE%5D.mp3"
        ),
        sync=False,
    )

    # 4. Keep dabbing while the music plays
    danced = 0.0
    while danced < MUSIC_SECONDS:
        # this call returns when the dab animation finishes
        yield session.call("rom.optional.behavior.play", name="BlocklyDuck")
        danced += DAB_SECONDS_EST   # just our rough estimate

    # 5. Stop the music right after the last dab
    yield session.call("rom.actuator.audio.stop")

    # 6. Outro line
    yield session.call(
        "rie.dialogue.say",
        text="Yo, dat was hard as fuck bro!!!"
    )

    # 7. Optional: crouch / rest
    yield session.call("rom.optional.behavior.play", name="BlocklyApplause")


    yield session.call("rom.optional.behavior.play", name="BlocklyGangnamStyle")

    yield sleep(1.0)

    yield session.call(
        "rie.dialogue.say",
        text="six seven"
    )
    yield session.call("rom.optional.behavior.play", name="BlocklyCrouch")

    # 8. Disconnect
    session.leave()


wamp = Component(
    transports=[{
        "url": "ws://wamp.robotsindeklas.nl",
        "serializers": ["msgpack"],
        "max_retries": 0,
    }],
    #realm="rie.6918c48a375fb38004f5389f",
    realm="rie.691ce2fd82c3bec9b226dfc9",
)

wamp.on_join(main)

if __name__ == "__main__":
    run([wamp])
