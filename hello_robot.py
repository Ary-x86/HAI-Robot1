from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep

# tune these 
MUSIC_SECONDS = 40      #how long we want the song+dance to last
DAB_SECONDS_EST = 4.0   #duration of one BlocklyDab animation in seconds

@inlineCallbacks
def main(session, details):
    #make bot stand
    yield session.call("rom.optional.behavior.play", name="BlocklyStand")
    yield sleep(1.0)

    yield session.call("rom.actuator.motor.write",
        frames=[{"time": 400, "data": {"body.head.pitch": 0.1}},
            {"time": 1200, "data": {"body.head.pitch": -0.1}},
            {"time": 2000, "data": {"body.head.pitch": 0.1}},
            {"time": 2400, "data": {"body.head.pitch": 0.0}}],
        force=True
    ) 



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
            "https://github.com/Ary-x86/HAI-Robot1/raw/refs/heads/main/audio/i%20want%20some%20cheeseburgers%20just%20to%20eat.mp3"
        ),
        sync=False,
    )

    #dab while music plays (should be a non audio behviour)
    danced = 0.0
    while danced < MUSIC_SECONDS:
        #to sync the dab stopping with the music, qwe can add any moves we want that should keep looping
        yield session.call("rom.optional.behavior.play", name="BlocklyDuck")
        danced += DAB_SECONDS_EST   #estimate

    # stop music
    yield session.call("rom.actuator.audio.stop")

  
    yield session.call(
        "rie.dialogue.say",
        text="Yo, dat was hard!!!"
    )


    yield session.call("rom.optional.behavior.play", name="BlocklyApplause")


    yield session.call("rom.optional.behavior.play", name="BlocklyGangnamStyle")

    yield sleep(1.0)

    yield session.call(
        "rie.dialogue.say",
        text="Anyway, let's continue playing"
    )
    #yield session.call("rom.optional.behavior.play", name="BlocklyCrouch")

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
