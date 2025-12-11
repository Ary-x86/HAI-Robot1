import os
import sys
import json
import time
import requests
import speech_recognition as sr  # NEW: Faster, simpler handling
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
USE_LOCAL_MIC = True 
ROBOT_REALM = os.getenv("RIDK_REALM", "rie.693b0e88a7cba444073b9c99")
WAMP_URL = os.getenv("RIDK_WAMP_URL", "ws://wamp.robotsindeklas.nl")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini") 
API_URL = "http://127.0.0.1:8000"

client = OpenAI(api_key=OPENAI_API_KEY)
recognizer = sr.Recognizer()

# --- GLOBAL STATE ---
current_game_state = {"ai_lead": 0, "game_over": False} 
last_turn_index = -1 
is_speaking = False

def fetch_game_state():
    try:
        res = requests.get(f"{API_URL}/state", timeout=0.5) # Fast timeout
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {}

def generate_response(user_text):
    """Send text + context to Responses API."""
    try:
        # Get latest state just before generating
        state = fetch_game_state()
        lead = state.get("ai_lead", 0)
        
        system_msg = (
            "You are 'Robo', a cocky, competitive robot playing Connect 4. "
            "Keep responses SHORT (1 sentence). React to the user's trash talk."
        )
        
        if lead < 0: system_msg += " You are losing. Be annoyed and defensive."
        elif lead > 0: system_msg += " You are winning. Be smug."

        context = f"Game Score Lead: {lead}. User said: {user_text}"

        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=system_msg,
            input=context,
            max_output_tokens=60 
        )
        return response.output_text
    except Exception as e:
        print(f"[Brain] LLM Error: {e}")
        return ""

@inlineCallbacks
def game_loop(session):
    global last_turn_index, current_game_state
    print("[Brain] 🎮 Game Loop Active")
    
    while True:
        try:
            state = yield threads.deferToThread(fetch_game_state)
            if state:
                current_game_state = state
                turn = state.get("turn_index", -1)
                taunt = state.get("last_taunt", "")
                
                if turn > last_turn_index:
                    last_turn_index = turn
                    # Only speak move-taunts if we aren't already having a conversation
                    if taunt and not is_speaking:
                        print(f"[Brain] 🤖 Robot says (Move): {taunt}")
                        yield session.call("rie.dialogue.say", text=taunt)
        except Exception as e:
            pass
        yield tSleep(1.0)

def listen_and_respond_loop(session):
    """
    Runs in a separate thread. 
    Continuously listens to mic, transcribes, and speaks.
    """
    global is_speaking
    
    # Adjust for ambient noise once at startup
    with sr.Microphone() as source:
        print("[Brain] 🎧 Calibrating microphone for 1 second...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[Brain] 👂 Listening! Speak now.")

        while True:
            try:
                # 1. Listen (Blocking call, efficient silence detection)
                # timeout=None means wait forever for speech
                # phrase_time_limit=5 means cut off after 5s of talking
                audio = recognizer.listen(source, phrase_time_limit=5)
                
                # 2. Transcribe (Fast Google API, free & included in library)
                # Much faster than uploading file to OpenAI Whisper
                try:
                    user_text = recognizer.recognize_google(audio)
                    print(f"[Brain] 🗣️ You: {user_text}")
                except sr.UnknownValueError:
                    # Couldn't understand audio (silence/noise)
                    continue 

                # 3. Interrupt Robot if it was speaking
                if is_speaking:
                    print("[Brain] 🛑 Interrupted!")
                    # Send stop command to robot (Fire & Forget)
                    reactor.callFromThread(session.call, "rie.dialogue.stop")
                
                is_speaking = True

                # 4. Generate Response
                # We use the existing OpenAI client function
                reply = generate_response(user_text)
                
                if reply:
                    print(f"[Brain] 🤖 Robot: {reply}")
                    # Send speak command via Twisted Reactor to be thread-safe
                    reactor.callFromThread(session.call, "rie.dialogue.say", text=reply)
                    
                    # Estimate speaking time (roughly) to unset flag
                    # 1 word ~= 0.4 seconds
                    speak_time = len(reply.split()) * 0.4
                    time.sleep(speak_time) 
                    is_speaking = False

            except Exception as e:
                print(f"[Brain] Error in loop: {e}")
                is_speaking = False

# --- WAMP SETUP ---

session_global = None

@inlineCallbacks
def main(session, details):
    global session_global
    session_global = session
    print(f"[Brain] Connected to Robot {ROBOT_REALM}")

    if USE_LOCAL_MIC:
        # Start the listening loop in a background thread
        reactor.callInThread(listen_and_respond_loop, session)
    else:
        print("Remote robot mic implementation pending...")

    # Start Game Loop
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