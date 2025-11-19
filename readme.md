# 🤖 Robo Connect 4 – HAI Project

**warningh: currently the LLM functionality does not work yet. But we have fallback responses, which will be on  the entire time.**

sry m hg

This project is a **Human–Agent Interaction** demo:  
a web-based **Connect 4** game where a cocky robot opponent (“Robo”) plays against a human and throws short Gen-Z style taunts powered by an OpenAI model.

The stack:

- **Frontend**: simple web UI (HTML/JS) served by FastAPI
- **Backend**: Python 3.13, FastAPI, game logic & OpenAI integration
- **LLM**: `gpt-5-nano` via the **OpenAI Python SDK v2.x** (`openai` package)
- **Deployment target**: university “Realm” environment (or local dev)

This README explains:

1. How to run everything **locally**
2. How to **log into the Realm**, copy the project, and run it there
3. How the **robot conversation flow** works
4. Where and how the **LLM taunts** are generated

---

## 1. Repository Structure

(Exact filenames may differ slightly, but this is the intended architecture.)

```text
HAI-Project/
├── app/
│   ├── main.py           # FastAPI app: routes /, /state, /move, /reset
│   ├── game_engine.py    # Connect 4 board, rules, scoring, snapshots
│   ├── openai_agent.py   # LLM taunt generation ("Robo")
│   └── __init__.py
├── static/
│   └── index.html        # Frontend UI (board + buttons, JS)
├── requirements.txt
├── .env.example          # Example environment variables
└── README.md             # This file

2. Prerequisites

You’ll need:

    Python ≥ 3.9 (we use 3.13 in the venv)

    pip / venv

    An OpenAI API key

    Access to your uni’s Realm (or similar deployment environment)

3. Local Setup (Development)
3.1 Clone the project

git clone <YOUR_REPO_URL> HAI-Project
cd HAI-Project

3.2 Create & activate a virtual environment

python3 -m venv .venv
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows PowerShell

3.3 Install Python dependencies

Make sure openai 2.x is installed:

pip install -r requirements.txt
# or if needed:
pip install "openai>=2.8.1"

3.4 Configure environment variables (.env)

Create a .env file in the project root:

cp .env.example .env

Open .env and set at least:

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-nano

    If OPENAI_API_KEY is missing, the code falls back to hardcoded taunts and will log that it’s using the fallback.

4. Running the Game Locally

From the project root (with the venv active):

uvicorn app.main:app --reload

You should see something like:

Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)

Now open a browser:

    http://127.0.0.1:8000/

You should see:

    The Connect 4 board

    A way to drop pieces

    Robo’s taunts appearing when:

        A new game starts (intro)

        During mid-game moves

        When the game ends (win/lose/draw)

The game UI periodically calls:

    GET /state – get the current board + scores + last taunt

    POST /move – send the human move (column)

    POST /reset – start a new game

You already saw these in the logs:

GET /state
POST /move
POST /reset

5. Realm Setup (Course Deployment)

    Note: exact names may differ depending on your university’s system (“Realm”, “WebLab Realm”, etc.). Adjust the URL and labels to match your course instructions.

5.1 Log in to the Realm

    Go to the Realm URL provided by the course
    (e.g. https://realm.<university-domain>/ or a link in Brightspace).

    Click Log in / Sign in with university account.

    Use your university credentials (same as email / Brightspace).

5.2 Create or copy the project Realm

You usually have two options:

    Option A – Import from Git

        In Realm, click New Project / Import from Git.

        Paste your repository URL:
        https://github.com/<your-org>/HAI-Project.git

        Select Python / FastAPI or a generic web app template.

        Confirm and create.

    Option B – Copy provided Realm

        If the teacher gave a template Realm link, open it.

        Click Copy Realm / Fork / Duplicate.

        You now have your own Realm instance.

5.3 Configure environment variables in Realm

In the Realm UI:

    Open Settings → Environment variables (or similar).

    Add:

        OPENAI_API_KEY → your real key

        OPENAI_MODEL → gpt-5-nano

    Save & redeploy / restart the Realm.

5.4 Configure the run command

In Realm’s project settings, set the run/start command to:

uvicorn app.main:app --host 0.0.0.0 --port 8000

Sometimes the environment expects:

    a Procfile with
    web: uvicorn app.main:app --host 0.0.0.0 --port $PORT

    or a “Start command” field in the UI.

Whatever the platform uses, the important part is:

    Python entrypoint: app.main:app

    Use Uvicorn

    Bind to 0.0.0.0 and the provided port

5.5 Open the deployed game

Once Realm says the app is running:

    Click Open in browser or Visit site

    You should see the same Connect 4 UI as locally

    Confirm:

        You can make moves

        The robot taunts appear in the UI (if API key is set)

6. LLM Integration (Robo’s Taunts)
6.1 High-level

The LLM is used in exactly one place:
app/openai_agent.py → generate_taunt(snapshot, phase)

It takes:

    a snapshot of the game state (scores, winner, etc.)

    a phase label describing where we are in the conversation

and returns:

    one short English sentence of banter.

Phases:

    "intro" – start of a new game

    "midgame" – game in progress

    "robot_wins" – robot just won

    "human_wins" – human just won

    "draw" – game ended in a draw

If anything goes wrong (wrong key, no internet, API error),
we fall back to _fallback_taunt, a deterministic rule-based taunt generator.
6.2 Snapshot format

The snapshot is compressed into text like:

Turn_index=5, ai_score=2, human_score=1, ai_lead=1, game_over=False, winner=None.

6.3 System + phase instructions

System base prompt (simplified):

You are 'Robo', an English-speaking robot playing Connect 4 against a human.
You are cocky and slightly annoying, but never rude or profane.
You use short, casual Gen Z-ish internet tone.
You ALWAYS answer with ONE single sentence, no quotes, no bullet points.
Max ~140 characters. Classroom-safe. No swearing, slurs, politics or sex.
You talk directly to the human opponent, not about them in third person.

Per-phase instructions (examples):

    intro: “Invite the human to start a new game, confident & teasing.”

    midgame: “Comment on who’s ahead based on scores; light trash talk.”

    robot_wins: “Robot smug win; lightly roast human.”

    human_wins: “Salty but respectful; admit defeat, suggest rematch.”

    draw: “Call it mid / no one clutched.”

These are glued together with the snapshot into one prompt_text.
6.4 Using the Responses API (correct OpenAI v2 style)

The important part: we use client.responses.create with model="gpt-5-nano".

Core logic (clean, up-to-date pattern):

# app/openai_agent.py

from typing import Dict, Any
import os, logging
from openai import OpenAI

_client = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def generate_taunt(snapshot: Dict[str, Any], phase: str = "midgame") -> str:
    phase = phase if phase in PHASE_INSTRUCTIONS else "midgame"
    model = os.getenv("OPENAI_MODEL", "gpt-5-nano")

    # If no key => fallback
    if not os.getenv("OPENAI_API_KEY"):
        return _fallback_taunt(snapshot, phase)

    prompt_text = (
        SYSTEM_BASE
        + "\n"
        + PHASE_INSTRUCTIONS[phase]
        + "\n\nCurrent Connect 4 snapshot:\n"
        + _snapshot_to_text(snapshot)
    )

    try:
        client = _get_client()
        resp = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt_text},
                    ],
                }
            ],
            max_output_tokens=64,
        )

        # Safest way with the new API: use output_text helper
        text = (resp.output_text or "").strip().replace("\n", " ")

        if not text:
            # If for some reason the model returns empty output
            return _fallback_taunt(snapshot, phase)

        # Safety: enforce short length
        if len(text) > 180:
            text = text[:180]

        return text
    except Exception as e:
        logging.exception("LLM generate_taunt failed, falling back: %s", e)
        return _fallback_taunt(snapshot, phase)

Key points (to avoid the bugs you saw):

    Use resp.output_text instead of indexing resp.output[0].content[...]

    Do not send temperature for gpt-5-nano (it only supports the default)

    Use max_output_tokens, not max_completion_tokens

    Always have a fallback if the response is empty or exceptions occur

7. Conversation & Interaction Flow
7.1 High-level Architecture

[Human Player]
     |
     v
[Browser UI: Connect 4 board]
     |
     |  (click column)
     v
POST /move  (FastAPI)
     |
     v
[Game Engine]
     |
     |  create snapshot + phase
     v
generate_taunt(snapshot, phase)
     |
     +--> [OpenAI Responses API]
     |        |
     |        v
     |   one-sentence taunt text
     |
     v
[Game Engine updates state: last_taunt=...]
     |
     v
GET /state  (Frontend polling after each move)
     |
     v
[Browser UI shows board + Robo's taunt bubble]

7.2 Conversation phases (finite-state sketch)

                    +-----------------+
                    |  START / INTRO  |
                    +-----------------+
                             |
             new game / POST /reset
                             |
                             v
                  phase = "intro"
                generate_taunt(...)
                             |
                             v
                   +----------------+
                   |   MIDGAME      |
                   | (human & robot |
                   |   take turns)  |
                   +----------------+
                       ^        |
    human move /POST   |        |  game_over?
          /move        |        |
                       |        v
                       |  +----------------+
                       |  |   END STATES   |
                       |  +----------------+
                       |   winner = -1   -> phase="robot_wins"
                       |   winner =  1   -> phase="human_wins"
                       |   winner="draw" -> phase="draw"
                       |
                       +-----------------------------+

7.3 When is the LLM called?

    On new game:

        Backend sets phase="intro"

        generate_taunt(snapshot, "intro")

    On each move (optional, depending on your implementation):

        While game_over=False, phase="midgame"

        generate_taunt(snapshot, "midgame")

    On game over:

        If robot wins → phase="robot_wins"

        If human wins → phase="human_wins"

        If draw → phase="draw"

If OpenAI fails at any point → _fallback_taunt(snapshot, phase)
So the UI always gets some taunt string to show.
8. How to Actually Play (Step-by-Step For Teammates)

    Get access

        Clone the repo locally or

        Open the team Realm project if it’s already set up.

    Set your API key

        Locally → .env

        Realm → project settings → env vars

    Run the server

        Locally: uvicorn app.main:app --reload

        Realm: click Run / Deploy (platform-dependent)

    Open the game in a browser

        Local: http://127.0.0.1:8000/

        Realm: use the Public URL / “Open in browser” button

    Start a game

        Click “New game” / “Reset” if needed

        You should see an intro taunt from Robo

    Play

        Click on a column to drop your piece

        Robot responds with moves + taunts

        At the end, it will roast you or be salty, depending on who wins

9. Debugging Checklist

If Robo is silent or you only see fallback taunts:

    Check the logs

    You should see entries like:

INFO:  127.0.0.1:XXXXX - "POST /move HTTP/1.1" 200 OK
ERROR:root:LLM generate_taunt failed, falling back: ...

If you see “LLM generate_taunt failed, falling back”, the LLM call is breaking.

Common issues

    No API key

        Fix: set OPENAI_API_KEY in .env or Realm env vars

    Wrong model / unsupported parameter

        Ensure OPENAI_MODEL=gpt-5-nano (or another valid model)

        Do not pass temperature for gpt-5-nano

        Use max_output_tokens, not max_completion_tokens

    Response object indexing

        Use resp.output_text instead of deep indexing fields

Test LLM call in isolation

From a Python shell in the venv:

    from openai import OpenAI
    import os

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    resp = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5-nano"),
        input="Say 'this is a test taunt' in one short sentence."
    )

    print(resp.output_text)

    If this fails, your API setup is wrong. Fix that first.

10. Summary

    This repo is a Connect 4 HAI demo with a taunting LLM-powered robot.

    You run it via FastAPI + Uvicorn (uvicorn app.main:app).

    The LLM taunts live in openai_agent.py → generate_taunt.

    The Responses API is used with the modern OpenAI Python SDK.

    If anything fails, a deterministic fallback taunt keeps the game playable.

    This README is meant so any teammate can:

        log into the Realm,

        configure env vars,

        run the app,

        and understand how the whole conversation flow works end-to-end.

