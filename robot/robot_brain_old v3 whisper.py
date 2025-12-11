import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

# Twisted (WAMP engine)
from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks
from twisted.internet import threads, reactor
# Import correct sleep
from autobahn.twisted.util import sleep as tSleep

# OpenAI
from openai import OpenAI

# Local Audio
import sounddevice as sd

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from app.audio_helper import AudioBuffer, RMS_THRESHOLD, SILENCE_DURATION, RUDE_SILENCE_DURATION, SAMPLE_RATE

load_dotenv()

# --- CONFIG ---
USE_LOCAL_MIC = True  # <--- SET TO FALSE WHEN DEPLOYING TO PHYSICAL ROBOT

ROBOT_REALM = os.getenv("RIDK_REALM", "rie.693b0e88a7cba444073b9c99")
WAMP_URL = os.getenv("RIDK_WAMP_URL", "ws://wamp.robotsindeklas.nl")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini") 
API_URL = "http://127.0.0.1:8000"

client = OpenAI(api_key=OPENAI_API_KEY)

# --- GLOBAL STATE ---
audio_buf = AudioBuffer()
current_game_state = {"ai_lead": 0, "game_over": False} 
last_turn_index = -1 
is_processing = False       
interrupted = False         

def fetch_game_state():
    try:
        res = requests.get(f"{API_URL}/state", timeout=1)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {}

# --- OPENAI WORKER FUNCTIONS ---

def transcribe_audio(filename):
    try:
        print(f"[Brain] 🎤 Transcribing...")
        with open(filename, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", file=f
            )
        return transcript.text
    except Exception as e:
        print(f"[Brain] Whisper Error: {e}")
        return ""

def generate_response(user_text, game_state, is_rude):
    try:
        lead = game_state.get("ai_lead", 0)
        system_msg = (
            "You are 'Robo', a cocky, annoying Connect 4 robot. "
            "Keep responses SHORT (1 sentence). Speak for TTS. "
            "React to the user's trash talk."
        )
        if is_rude: system_msg += " You are losing. Be defensive and interrupt."
        elif lead > 0: system_msg += " You are winning. Be smug."

        context = f"Game Score Lead: {lead}. User said: {user_text}"
        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=system_msg,
            input=context
        )
        return response.output_text
    except Exception as e:
        print(f"[Brain] LLM Error: {e}")
        return "Whatever."

# --- ASYNC PIPELINES ---

@inlineCallbacks
def game_loop(session):
    global last_turn_index, current_game_state, is_processing
    print("[Brain] 🎮 Game Loop Active")
    
    while True:
        try:
            state = yield threads.deferToThread(fetch_game_state)
            if state:
                current_game_state = state
                turn = state.get("turn_index", -1)
                taunt = state.get("last_taunt", "")
                
                if turn > last_turn_index:
                    print(f"[Brain] 🎲 New Turn: {turn}")
                    last_turn_index = turn
                    if taunt and not is_processing:
                        print(f"[Brain] 🤖 Robot says (Move): {taunt}")
                        yield session.call("rie.dialogue.say", text=taunt)
        except Exception as e:
            print(f"[Brain] Poll error: {e}")
        yield tSleep(1.0)

@inlineCallbacks
def process_conversation_pipeline(session, wav_file):
    global is_processing, interrupted
    is_processing = True
    interrupted = False

    # 1. Transcribe
    user_text = yield threads.deferToThread(transcribe_audio, wav_file)
    AudioBuffer.cleanup(wav_file)

    if not user_text or not user_text.strip():
        is_processing = False
        return

    print(f"[Brain] 🗣️ You said: '{user_text}'")

    if interrupted:
        print("[Brain] 🛑 Interrupted (Transcription)")
        is_processing = False
        return

    # 2. LLM
    ai_lead = current_game_state.get("ai_lead", 0)
    is_rude = ai_lead < 0 
    robot_reply = yield threads.deferToThread(generate_response, user_text, current_game_state, is_rude)

    if interrupted:
        print("[Brain] 🛑 Interrupted (Thinking)")
        is_processing = False
        return

    # 3. Speak
    if is_rude:
        robot_reply = "Shhh! " + robot_reply
        # Attempt gesture, but don't crash if fails
        try: yield session.call("rom.optional.behavior.play", name="BlocklyShrug")
        except: pass

    print(f"[Brain] 🤖 Robot replies: '{robot_reply}'")
    yield session.call("rie.dialogue.say", text=robot_reply)
    is_processing = False

def process_audio_chunk(raw_data, is_local_mic):
    global is_processing, interrupted
    
    # 1. Add chunk & get loudness
    rms = audio_buf.add_chunk(raw_data, is_local_mic=is_local_mic)
    now = time.time()

    # 2. Threshold Logic
    if rms > RMS_THRESHOLD:
        audio_buf.silence_start_time = now
        # Barge-in
        if is_processing:
            print("!!! BARGE-IN DETECTED !!!")
            interrupted = True
    else:
        # Silence detected
        ai_lead = current_game_state.get("ai_lead", 0)
        wait_limit = RUDE_SILENCE_DURATION if ai_lead < 0 else SILENCE_DURATION

        if (now - audio_buf.silence_start_time > wait_limit) and len(audio_buf.buffer) > 10:
            if not is_processing:
                wav_file = audio_buf.save_to_wav()
                audio_buf.clear()
                if wav_file:
                    # Trigger Async Pipeline via Twisted Reactor
                    reactor.callLater(0, lambda: process_conversation_pipeline(session_global, wav_file))

def local_mic_loop():
    """
    Reads from local sounddevice stream and feeds the logic.
    """
    # Open Stream
    with sd.InputStream(callback=audio_buf.callback, channels=1, samplerate=SAMPLE_RATE):
        print("[Brain] 🎧 Local Microphone Active. Speak into your laptop!")
        while True:
            # Pull from the thread-safe queue in audio_helper
            chunk = audio_buf.get_chunk_from_queue()
            if chunk is not None:
                # Process strictly on main thread logic
                reactor.callFromThread(process_audio_chunk, chunk, True)
            else:
                time.sleep(0.01)

def on_robot_audio_frame(frame):
    """Callback for WAMP audio stream"""
    data = frame.get('data', {})
    raw_bytes = data.get('body.head.front') or data.get('body.head.middle')
    if raw_bytes:
        process_audio_chunk(raw_bytes, False)

# --- WAMP SETUP ---

session_global = None

@inlineCallbacks
def main(session, details):
    global session_global
    session_global = session
    print(f"[Brain] Connected to Robot {ROBOT_REALM}")

    # 1. Setup Audio Input
    if USE_LOCAL_MIC:
        # Run local mic loop in a background thread so it doesn't block WAMP
        reactor.callInThread(local_mic_loop)
    else:
        print("[Brain] Subscribing to Robot Microphones...")
        yield session.subscribe(on_robot_audio_frame, "rom.sensor.hearing.stream")
        yield session.call("rom.sensor.hearing.stream")

    # 2. Start Game Loop
    yield game_loop(session)

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