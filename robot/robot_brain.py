import os
import sys
import json
import time
import random
import requests
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

# Tuning
BEHAVIOR_CHANCE = 0.35  # 35% chance to perform a physical move
SFX_CHANCE = 0.50       # 50% chance to play a sound effect

client = OpenAI(api_key=OPENAI_API_KEY)
recognizer = sr.Recognizer()

# --- SOUND EFFECTS ---
# PASTE YOUR FULL GITHUB (RAW) URLs INSIDE THE QUOTES BELOW
SOUNDS = {
    "WIN": [
        "", # 1. MLG Airhorn (Loud & Proud)
        "", # 2. Vine Boom / Explosion
        "", # 3. "Wow" (Anime style or Owen Wilson)
    ],
    "LOSE": [
        "", # 1. Sad Violin / Tiny Violin
        "", # 2. GTA "Wasted" sound
        "", # 3. Spongebob "Fail" sound (Womp womp)
    ],
    "ANNOY": [
        "", # 1. Discord Notification (To confuse the user)
        "", # 2. Cartoon Slip/Fall whistle
        "", # 3. "Bruh" sound effect
        "", # 4. Adrian Scream (Your specific request)
    ],
    "WAIT": [
        "", # 1. Jeopardy Thinking Music (Short clip)
        "", # 2. Elevator Bossa Nova
    ]
}

# --- BEHAVIORS ---
MOVES = {
    "WIN_BIG": ["BlocklyDiscoDance", "BlocklyGangnamStyle", "BlocklyStarWars"],
    "WIN_SMALL": ["BlocklyDab", "BlocklyMacarena", "BlocklyHappy"],
    "LOSE": ["BlocklyCrouch", "BlocklyShrug", "BlocklySad"],
    "ANNOY": ["BlocklySneeze", "BlocklyApplause", "BlocklySaxophone"], 
    "IDLE": ["BlocklyTaiChiChuan", "BlocklyStand"]
}

# --- GLOBAL STATE ---
current_game_state = {"ai_lead": 0, "game_over": False} 
last_turn_index = -1 
is_speaking = False
rematch_mode = False

def fetch_game_state():
    try:
        res = requests.get(f"{API_URL}/state", timeout=0.5)
        if res.status_code == 200: return res.json()
    except: pass
    return {}

def trigger_reset():
    try: requests.post(f"{API_URL}/reset", timeout=1)
    except: pass

def generate_response(user_text, context_type="gameplay"):
    try:
        if context_type == "rematch":
            system_msg = (
                "You are deciding if the human wants a rematch. "
                "If YES: Output 'ACTION_RESET'. If NO: Output 'ACTION_QUIT'. "
                "Otherwise ask for clarification."
            )
            context = f"User said: {user_text}"
        else:
            state = fetch_game_state()
            lead = state.get("ai_lead", 0)
            
            system_msg = (
                "You are 'Robo', a cocky, competitive Connect 4 robot. "
                "Keep responses SHORT (1 sentence). "
                "You can trigger actions by ending your sentence with tags: "
                "[DANCE], [DAB], [SNEEZE], [CLAP], [SAD]. "
                "Use [DANCE] if winning big. Use [SAD] if losing."
            )
            context = f"Score Lead: {lead}. User said: {user_text}"

        response = client.responses.create(
            model=OPENAI_MODEL, instructions=system_msg, input=context, max_output_tokens=60
        )
        return response.output_text
    except Exception as e:
        print(f"[Brain] LLM Error: {e}")
        return ""

@inlineCallbacks
def play_sfx(session, category):
    """Plays a random sound from the category using the FULL URL provided."""
    # 1. Chance Check
    if random.random() > SFX_CHANCE:
        return

    # 2. Get list of URLs
    url_list = SOUNDS.get(category, [])
    
    # 3. Filter out empty strings (in case you haven't filled them all yet)
    valid_urls = [u for u in url_list if u.startswith("http")]

    if not valid_urls:
        print(f"[Brain] ⚠️ No valid URLs found for category: {category}")
        return

    # 4. Pick one and play
    url = random.choice(valid_urls)
    print(f"[Brain] 🎵 Playing SFX: {url}")
    
    # sync=False allows it to play over speech/movement
    yield session.call("rom.actuator.audio.stream", url=url, sync=False)

@inlineCallbacks
def perform_complex_reaction(session, text, anim_name, sfx_category=None):
    """
    Sequence: Speak -> (Background SFX) -> Move
    """
    # 1. Speak (Blocking)
    if text:
        print(f"[Brain] 🤖 Speaking: {text}")
        yield session.call("rie.dialogue.say", text=text)
    
    # 2. Sound Effect (Non-blocking)
    if sfx_category:
        yield play_sfx(session, sfx_category)

    # 3. Movement (Blocking, with Probability Check)
    if anim_name:
        if random.random() < BEHAVIOR_CHANCE:
            print(f"[Brain] 🕺 Performing: {anim_name}")
            yield tSleep(0.2) 
            yield session.call("rom.optional.behavior.play", name=anim_name, sync=True)
        else:
            print(f"[Brain] 🎲 Skipped behavior: {anim_name} (Chance check)")

@inlineCallbacks
def game_loop(session):
    global last_turn_index, current_game_state, rematch_mode, is_speaking
    print("[Brain] 🎮 Game Loop Active")
    
    while True:
        try:
            state = yield threads.deferToThread(fetch_game_state)
            if state:
                current_game_state = state
                turn = state.get("turn_index", -1)
                game_over = state.get("game_over", False)
                taunt = state.get("last_taunt", "")
                lead = state.get("ai_lead", 0)
                winner = state.get("winner")

                if turn > last_turn_index:
                    last_turn_index = turn
                    
                    # 1. GAME OVER
                    if game_over and not rematch_mode:
                        print(f"[Brain] 🏁 GAME OVER.")
                        rematch_mode = True
                        
                        if winner == -1: # AI Won
                            yield perform_complex_reaction(
                                session, "I told you I was built different!", 
                                "BlocklyGangnamStyle", "WIN"
                            )
                        elif winner == 1: # Human Won
                            yield perform_complex_reaction(
                                session, "No way... my sensors must be lagging.", 
                                "BlocklyCrouch", "LOSE"
                            )
                        else:
                            yield perform_complex_reaction(
                                session, "Draw game.", 
                                "BlocklyShrug", "ANNOY"
                            )

                        yield tSleep(1.0)
                        yield session.call("rie.dialogue.say", text="Do you want a rematch? Say yes.")
                        
                    # 2. MID-GAME
                    elif not rematch_mode and taunt and not is_speaking:
                        
                        anim = None
                        sfx = None
                        
                        # Logic Matrix
                        if lead >= 6: 
                            anim = random.choice(MOVES["WIN_BIG"])
                            sfx = "WIN"
                        elif lead <= -6: 
                            anim = random.choice(MOVES["LOSE"])
                            sfx = "LOSE"
                        elif lead > 2: 
                            anim = random.choice(MOVES["WIN_SMALL"])
                        elif lead < -2: 
                            anim = "BlocklyShrug"
                        elif random.random() < 0.2: 
                            anim = random.choice(MOVES["ANNOY"])
                            sfx = "ANNOY"

                        yield perform_complex_reaction(session, taunt, anim, sfx)

                if not game_over and rematch_mode:
                    rematch_mode = False

        except Exception as e:
            pass
        yield tSleep(0.5)

def listen_loop(session):
    global is_speaking, rematch_mode
    with sr.Microphone() as source:
        print("[Brain] 🎧 Calibrating mic...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("[Brain] 👂 Listening!")

        while True:
            try:
                audio = recognizer.listen(source, phrase_time_limit=5)
                try:
                    text = recognizer.recognize_google(audio)
                    print(f"[Brain] 🗣️ You: {text}")
                except: continue 

                if is_speaking:
                    reactor.callFromThread(session.call, "rie.dialogue.stop")

                is_speaking = True
                context = "rematch" if rematch_mode else "gameplay"
                reply = generate_response(text, context)

                # Parse Tags
                anim = None
                sfx = None
                
                if "[DANCE]" in reply: 
                    anim = random.choice(MOVES["WIN_BIG"])
                    sfx = "WIN"
                elif "[DAB]" in reply: 
                    anim = "BlocklyDab"
                elif "[SNEEZE]" in reply: 
                    anim = "BlocklySneeze"
                    sfx = "ANNOY"
                elif "[CLAP]" in reply: 
                    anim = "BlocklyApplause"
                elif "[SAD]" in reply: 
                    anim = random.choice(MOVES["LOSE"])
                    sfx = "LOSE"
                
                speech = reply.replace("[DANCE]", "").replace("[DAB]", "").replace("[SNEEZE]", "").replace("[CLAP]", "").replace("[SAD]", "")

                if "ACTION_RESET" in reply:
                    print("[Brain] 🟢 Rematch!")
                    reactor.callFromThread(lambda: perform_complex_reaction(session, "Here we go again!", "BlocklyStand", "WIN"))
                    trigger_reset()
                    rematch_mode = False
                elif "ACTION_QUIT" in reply:
                    print("[Brain] 🔴 Quit.")
                    reactor.callFromThread(lambda: perform_complex_reaction(session, "Fine, bye.", "BlocklyCrouch", "LOSE"))
                else:
                    reactor.callFromThread(lambda: perform_complex_reaction(session, speech, anim, sfx))

                time.sleep(1.0)
                is_speaking = False

            except Exception:
                is_speaking = False

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

wamp = Component(
    transports=[{"url": WAMP_URL, "serializers": ["msgpack"], "max_retries": 0}],
    realm=ROBOT_REALM,
)
wamp.on_join(main)

if __name__ == "__main__":
    run([wamp])