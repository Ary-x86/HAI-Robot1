# IN CONTEXT: Robo Connect-4 – Virtual Robot + OpenAI

**warningh: currently the LLM functionality does not work yet. But we have fallback responses, which will be on  the entire time.**


This repo contains a small Connect-4 game where a **virtual robot** from the  
Robots-in-de-Klas (RoboConneqt) portal plays against a human and talks trash
using an **LLM (OpenAI gpt-5-nano)**.

The project is built for the **Human-Agent Interaction (HAI)** course and is
designed so that anyone in the group can set it up from scratch.

---

## 0. Requirements

- Python **3.11+**
- `pip` (and optionally `virtualenv`)
- A browser
- Internet connection (for OpenAI + Robots-in-de-Klas WAMP)
- **Course keys:**
  - RoboConneqt group code: `HDQN-XXXX-XXXX` (See brightspace for the code)
  - OpenAI API key for the group (request from Joost; models allowed:
    `gpt-5-nano`, `tts-1`, `whisper-1`)

> **Important:**  
> Do **not** commit any API keys (.env file) to GitHub/GitLab. If the key
> leaks, it will be disabled.

---

## 1. Create a RoboConneqt account and virtual robot

1. Go to **<https://portal.robotsindeklas.nl>**.
2. Click **“Maak account / Use code”**.
3. Enter the course key: **`HDQN-XXXX-XXXX`**. (See brightspace for the code)
4. Choose a **group username** and **password**.  
   - One account per group, shared by everyone.
5. In **Organisation**, start typing **“Univ…”** and select  
   **“Univ Leiden”** (or the equivalent Leiden University option).
6. Finish registration and write down the username + password.
7. Next time you can log in from **<https://portal.robotsindeklas.nl/#/home>**
   with:
   - Organisation: **Univ Leiden**
   - Your group username + password. (See discord for our login)

After logging in you can access:

- **Start** – overview of available apps.
- **My apps** – your own programs.
- **Robots** – physical robots (if assigned) + the **Virtual Robot**.

---

## 2. Start the Virtual Robot and get the realm

We mainly use the **Virtual Robot** (3D character in the browser).

1. Log in at **<https://portal.robotsindeklas.nl/#/home>**.
2. Click the **Robots** tab in the top navigation bar.
3. You should see a tile named **“Virtual Robot”** (see screenshot in the repo).
4. Make sure it is **online**:
   - There should be a **green dot** at the top-left of the tile.
   - If not, click the **green power/play button** to start it.
5. Open the **menu** for that robot (hover the tile and use the small icon
   with three horizontal lines / settings / or similar).
6. In that menu, click the **“Copy example code / info”** / clipboard icon.
7. In the popup, scroll to where you see something like:

   ```text
   realm="rie.691ce2fd82c3bec9b226dfc9",
  ```

The part starting with `rie.` is the **realm** of this virtual robot.

8. Copy that value. We’ll call it:

   ```text
   RIDK_REALM = rie.691ce2fd82c3bec9b226dfc9
   ```

For this project we initially use:

```text
rie.691ce2fd82c3bec9b226dfc9
```

If you ever change to another robot or account, repeat the steps and update
the realm everywhere.

---

## 3. Pause the default agent on the virtual robot

The robot usually runs a default “classroom” agent. You **must pause** it,
otherwise it can conflict with our code.

1. On the **Robots** page, open the menu for **Virtual Robot**.
2. Click the **pause / agent stop** icon.
3. The robot (or the virtual robot) should say something like:

   > “Agent is paused”
4. Leave it paused whenever you run this Connect-4 project.

This ensures that only **our application** sends dialogue to the robot.

---

## 4. Local project setup

### 4.1 Clone the repo and install dependencies

```bash
# 1. Clone the repo
git clone <REPO_URL>
cd <REPO_FOLDER>

# 2. (Optional but recommended) create a virtualenv
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\activate       # Windows

# 3. Install Python dependencies
pip install -r requirements.txt
```

### 4.2 Configure environment variables (`.env`)

Create a file called `.env` in the project root (same folder as `app/`):

```env
# === OpenAI ===
OPENAI_API_KEY=sk-...your-course-key-here...
OPENAI_MODEL=gpt-5-nano

# === Robots in de Klas (RIDK) ===
RIDK_REALM=rie.691ce2fd82c3bec9b226dfc9
RIDK_WAMP_URL=wss://wamp.robotsindeklas.nl
```

Notes:

* `OPENAI_API_KEY` – ask Joost for your group key.
* `OPENAI_MODEL` – must be one of the allowed models; we use `gpt-5-nano`.
* `RIDK_REALM` – copy from the portal as described above.
* `RIDK_WAMP_URL` – standard WAMP endpoint for Robots-in-de-Klas.

The backend reads these via `python-dotenv` at startup.

---

## 5. Running the Connect-4 app

### 5.1 Start backend + frontend

From the project root:

```bash
uvicorn app.main:app --reload
```

You should see something like:

```text
Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Open a browser and go to:

> [http://127.0.0.1:8000](http://127.0.0.1:8000)

You should see:

* A **Connect-4 board**.
* A score / status area.
* A text area where the robot’s latest **taunt** is shown.

### 5.2 Ensure robot connection

As you play:

* The **backend** will compute each move.
* For each turn, it will generate a taunt via OpenAI and send it to the robot.
* The **virtual robot** in the portal should speak those lines out loud.

If the robot doesn’t talk but the game UI works, check:

* Did you pause the default agent in the portal?
* Is the **realm** correct in `.env`?
* Is your device online (WAMP + OpenAI need internet)?
* Is the OpenAI key valid?

---

## 6. Optional: Connectivity sanity check (`robot_ping.py`)

If you want to validate the robot connection without running the whole app,
you can create a small script `robot_ping.py` (if not already present):

```python
import os
from autobahn.twisted.component import Component, run
from twisted.internet.defer import inlineCallbacks

REALM = os.getenv("RIDK_REALM", "rie.691ce2fd82c3bec9b226dfc9")
WAMP_URL = os.getenv("RIDK_WAMP_URL", "wss://wamp.robotsindeklas.nl")

component = Component(
    transports=[{"url": WAMP_URL, "serializers": ["msgpack"]}],
    realm=REALM,
)

@component.on_join
@inlineCallbacks
def joined(session, details):
    # Simple one-shot test
    yield session.call("rie.dialogue.say", text="Hello from the Connect four project!")
    session.leave()

if __name__ == "__main__":
    run([component])
```

Run:

```bash
python robot_ping.py
```

Expected behaviour:

* The virtual robot in the portal says
  **“Hello from the Connect four project!”** and then stops.
* If this works, your WAMP realm + URL are correct.

---

## 7. System architecture

### 7.1 Components

* **Human player**

  * Clicks columns in the browser.
* **Browser frontend**

  * Renders the Connect-4 board and shows the latest taunt as text.
  * Uses:

    * `POST /move` – send a move.
    * `GET /state` – poll the current game state.
* **FastAPI backend (`app.main`)**

  * Maintains the game state.
  * Chooses robot moves.
  * Calls the **LLM** to generate taunts.
  * Sends taunts to the robot via the **RIDK WAMP API**.
* **OpenAI Responses API (Python `openai` client)**

  * Model: `gpt-5-nano`.
  * Generates short, cocky, classroom-safe one-liners.
* **Robots-in-de-Klas WAMP server**

  * Exposes RPC calls like `rie.dialogue.say`.
  * Routes our calls to the actual (virtual or physical) robot.
* **Virtual Robot**

  * Receives text and speaks it via TTS.
  * Can perform animations (not heavily used in this project yet).

---

### 7.2 Data flow (overview)

```text
[Human player]
      |
      |  (click column)
      v
[Browser JS frontend]
      |
      |  POST /move  (column index)
      v
[FastAPI backend]
      |
      | 1. Update Connect-4 board
      | 2. Compute snapshot (scores, ai_lead, winner, etc.)
      | 3. Determine phase (intro / midgame / robot_wins / human_wins / draw)
      | 4. generate_taunt(snapshot, phase) via OpenAI
      | 5. Send text to RIDK: rie.dialogue.say(text=taunt)
      v
[RIDK WAMP server]
      |
      v
[Virtual Robot]
  (speaks the taunt)

In parallel:

[Browser JS frontend] <-- GET /state (polling)
      ^
      |  returns JSON:
      |   - board
      |   - whose_turn
      |   - scores
      |   - game_over / winner
      |   - last_taunt (same as robot said)
      |
[FastAPI backend]
```

So the taunt reaches the player **twice**:

1. As spoken output from the **robot**.
2. As text in the **web UI** (from `/state`).

---

## 8. Game snapshot + conversation phases

The backend compresses the game state into a **snapshot** before calling
the LLM:

```python
{
  "turn_index": int,        # how many moves played
  "ai_score": int,          # heuristic evaluation for AI
  "human_score": int,       # heuristic evaluation for human
  "ai_lead": int,           # ai_score - human_score
  "game_over": bool,
  "winner": -1 | 0 | 1 | "draw" | None
}
```

This snapshot is converted into a small string, for example:

```text
Turn_index=12, ai_score=5, human_score=2, ai_lead=3, game_over=False, winner=None.
```

Then the backend chooses a **phase**:

* `intro`

  * Used at the start of a new game (or first taunt).
  * Purpose: invite the player, explain we’re playing Connect-4, light teasing.
* `midgame`

  * Used during normal play while `game_over == False` and `turn_index > 0`.
  * Purpose: reactive comments, cocky but safe trash talk.
  * Uses `ai_lead` to decide tone (behind, ahead, close game).
* `robot_wins`

  * Used when `game_over == True` and `winner == -1` (AI player).
  * Purpose: smug “I won” while still respectful and non-toxic.
* `human_wins`

  * Used when `game_over == True` and `winner == 1`.
  * Purpose: salty but respectful defeat, invite rematch.
* `draw`

  * Used when the game ends in a draw.
  * Purpose: “mid” / joke that nobody clutched.

For each phase there is a **phase-specific instruction** that gets appended to
the **system prompt** describing the persona:

```text
You are 'Robo', an English-speaking robot playing Connect 4 against a human.
You are cocky and slightly annoying, but never rude or profane.
You use short, casual Gen Z-ish internet tone.
You ALWAYS answer with ONE single sentence, no quotes, no bullet points.
Max ~140 characters. Classroom-safe. No swearing, slurs, politics or sex.
You talk directly to the human opponent, not about them in third person.
```

Example prompt fragment sent to OpenAI (simplified):

```text
[System]  (persona above + phase-specific instruction)
[User]    Here is the current Connect 4 game summary as JSON-ish text:
          Turn_index=12, ai_score=5, human_score=2, ai_lead=3,
          game_over=False, winner=None.
```

The model returns **a single sentence**, which we:

1. Truncate if it exceeds a hard limit (safety).
2. Store as `last_taunt` in the backend state.
3. Send to the robot with `rie.dialogue.say`.
4. Expose through `GET /state` so the frontend can show it.

---

## 9. Fallback behaviour (no internet / API issues)

If anything goes wrong with the OpenAI call (no key, network error,
empty response, etc.), the backend calls `_fallback_taunt(snapshot, phase)`.

This function is deterministic and uses simple rules:

* If `game_over`:

  * `winner == -1` → “GG, I told you I was built different.”
  * `winner == 1`  → “Alright, you got me this time, respect.”
  * `winner == "draw"` → “Draw game, kinda mid for both of us.”
* Else (midgame):

  * Very large positive `ai_lead` → “I’m lowkey speedrunning you right now.”
  * Moderate positive `ai_lead`  → “I’m kinda ahead, you sure about that strategy?”
  * Very negative `ai_lead`      → “Okay, chill, you’re actually stomping me.”
  * Moderate negative `ai_lead`  → “You’re up right now, but don’t get comfy.”
  * Otherwise                    → “Close game so far, one bad move and you’re cooked.”

So the robot **always** has something to say, even without the LLM.

---

## 10. Example end-to-end interaction

**1. Start**

* Group logs into RoboConneqt, starts the **Virtual Robot**, pauses the
  default agent.

* They run:

  ```bash
  uvicorn app.main:app --reload
  ```

* They open [http://127.0.0.1:8000](http://127.0.0.1:8000).

* Backend calls `generate_taunt` with `phase="intro"`.

* Robot says something like:

  > “Yo, I’m your Connect 4 robot, drop a piece and let’s see if you can survive.”

**2. Human move**

* Player clicks a column.
* Browser sends `POST /move` with column index.
* Backend updates board, checks for a winner, calculates new snapshot.

**3. Robot response**

* Backend chooses AI’s column and applies it.
* Snapshot shows AI slightly ahead → `phase="midgame"`.
* OpenAI returns e.g.:

  > “I’m kinda ahead, you sure that last move was the plan?”
* Backend:

  * Calls `rie.dialogue.say(text=...)`.
  * Stores the taunt and returns new state.
* Browser:

  * Polls `GET /state`.
  * Updates board + taunt text under/near the robot.

**4. Game end**

* Eventually `game_over=True`.
* If AI wins → `phase="robot_wins"`.
* OpenAI returns:

  > “Told you, I’m built for this grid life.”
* Robot speaks; UI shows final board + message.
* Player can refresh / reset for a new game (which triggers `intro` again).

This defines the full multimodal interaction loop:

* **Visual** – Connect-4 board and UI in the browser.
* **Verbal** – speech from the virtual robot driven by the LLM.
* **Input** – mouse clicks (or touch) from the human.

---

## 11. Troubleshooting checklist

If something is off, check in this order:

1. **Portal**

   * Are you logged into the correct **group account**?
   * Is **Virtual Robot** online (green dot)?
   * Is the **default agent paused**?

2. **Realm / WAMP**

   * Did you copy the exact `rie.*` realm into `.env`?
   * Is `RIDK_WAMP_URL` set to `wss://wamp.robotsindeklas.nl`?

3. **OpenAI**

   * Does `.env` contain a valid `OPENAI_API_KEY`?
   * Is `OPENAI_MODEL=gpt-5-nano`?

4. **Backend logs**

   * In the terminal running `uvicorn`, check for:

     * Exceptions from OpenAI calls.
     * Exceptions from the RIDK WAMP client.
   * If the LLM fails you should still see the fallback taunts.

5. **Network**

   * Is the machine online (no VPN/firewall blocking WAMP or OpenAI)?






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
````

---

## 2. Prerequisites

You’ll need:

* **Python** ≥ 3.9 (we use 3.13 in the venv)
* `pip` / `venv`
* An **OpenAI API key**
* Access to your uni’s **Realm** (or similar deployment environment)

---

## 3. Local Setup (Development)

### 3.1 Clone the project

```bash
git clone <YOUR_REPO_URL> HAI-Project
cd HAI-Project
```

### 3.2 Create & activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows PowerShell
```

### 3.3 Install Python dependencies

Make sure `openai` 2.x is installed:

```bash
pip install -r requirements.txt
# or if needed:
pip install "openai>=2.8.1"
```

### 3.4 Configure environment variables (`.env`)

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Open `.env` and set at least:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-nano
```

> If `OPENAI_API_KEY` is missing, the code falls back to **hardcoded taunts** and will log that it’s using the fallback.

---

## 4. Running the Game Locally

From the project root (with the venv active):

```bash
uvicorn app.main:app --reload
```

You should see something like:

```text
Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Now open a browser:

> [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

You should see:

* The **Connect 4 board**
* A way to **drop pieces**
* Robo’s **taunts** appearing when:

  * A new game starts (intro)
  * During mid-game moves
  * When the game ends (win/lose/draw)

The game UI periodically calls:

* `GET /state` – get the current board + scores + last taunt
* `POST /move` – send the human move (column)
* `POST /reset` – start a new game

You already saw these in the logs:

```text
GET /state
POST /move
POST /reset
```

---

## 5. 
---

## 6. LLM Integration (Robo’s Taunts)

### 6.1 High-level

The LLM is used in **exactly one place**:
`app/openai_agent.py → generate_taunt(snapshot, phase)`

It takes:

* a **snapshot** of the game state (scores, winner, etc.)
* a **phase** label describing where we are in the conversation

and returns:

* **one short English sentence** of banter.

Phases:

* `"intro"` – start of a new game
* `"midgame"` – game in progress
* `"robot_wins"` – robot just won
* `"human_wins"` – human just won
* `"draw"` – game ended in a draw

If **anything goes wrong** (wrong key, no internet, API error),
we fall back to `_fallback_taunt`, a deterministic rule-based taunt generator.

### 6.2 Snapshot format

The snapshot is compressed into text like:

```text
Turn_index=5, ai_score=2, human_score=1, ai_lead=1, game_over=False, winner=None.
```

### 6.3 System + phase instructions

System base prompt (simplified):

```text
You are 'Robo', an English-speaking robot playing Connect 4 against a human.
You are cocky and slightly annoying, but never rude or profane.
You use short, casual Gen Z-ish internet tone.
You ALWAYS answer with ONE single sentence, no quotes, no bullet points.
Max ~140 characters. Classroom-safe. No swearing, slurs, politics or sex.
You talk directly to the human opponent, not about them in third person.
```

Per-phase instructions (examples):

* `intro`: “Invite the human to start a new game, confident & teasing.”
* `midgame`: “Comment on who’s ahead based on scores; light trash talk.”
* `robot_wins`: “Robot smug win; lightly roast human.”
* `human_wins`: “Salty but respectful; admit defeat, suggest rematch.”
* `draw`: “Call it mid / no one clutched.”

These are glued together with the snapshot into one **prompt_text**.

### 6.4 Using the **Responses API** (correct OpenAI v2 style)

The important part: we use **`client.responses.create`** with `model="gpt-5-nano"`.

Core logic (clean, up-to-date pattern):

```python
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
```

Key points (to avoid the bugs you saw):

* Use **`resp.output_text`** instead of indexing `resp.output[0].content[...]`
* Do **not** send `temperature` for `gpt-5-nano` (it only supports the default)
* Use `max_output_tokens`, **not** `max_completion_tokens`
* Always have a **fallback** if the response is empty or exceptions occur

---

## 7. Conversation & Interaction Flow

### 7.1 High-level Architecture

```text
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
```

### 7.2 Conversation phases (finite-state sketch)

```text
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
```

### 7.3 When is the LLM called?

* On **new game**:

  * Backend sets `phase="intro"`
  * `generate_taunt(snapshot, "intro")`

* On **each move** (optional, depending on your implementation):

  * While `game_over=False`, `phase="midgame"`
  * `generate_taunt(snapshot, "midgame")`

* On **game over**:

  * If robot wins → `phase="robot_wins"`
  * If human wins → `phase="human_wins"`
  * If draw → `phase="draw"`

If OpenAI fails at any point → `_fallback_taunt(snapshot, phase)`
So the UI **always** gets some taunt string to show.

---

## 8. How to Actually Play (Step-by-Step For Teammates)

1. **Get access**

   * Clone the repo locally **or**
   * Open the team Realm project if it’s already set up.

2. **Set your API key**

   * Locally → `.env`
   * Realm → project settings → env vars

3. **Run the server**

   * Locally: `uvicorn app.main:app --reload`
   * Realm: click **Run / Deploy** (platform-dependent)

4. **Open the game in a browser**

   * Local: `http://127.0.0.1:8000/`
   * Realm: use the **Public URL** / “Open in browser” button

5. **Start a game**

   * Click “New game” / “Reset” if needed
   * You should see an intro taunt from Robo

6. **Play**

   * Click on a column to drop your piece
   * Robot responds with moves + taunts
   * At the end, it will roast you or be salty, depending on who wins

---

## 9. Debugging Checklist

If **Robo is silent** or you only see fallback taunts:

1. **Check the logs**

   You should see entries like:

   ```text
   INFO:  127.0.0.1:XXXXX - "POST /move HTTP/1.1" 200 OK
   ERROR:root:LLM generate_taunt failed, falling back: ...
   ```

   If you see “LLM generate_taunt failed, falling back”, the LLM call is breaking.

2. **Common issues**

   * **No API key**

     * Fix: set `OPENAI_API_KEY` in `.env` or Realm env vars

   * **Wrong model / unsupported parameter**

     * Ensure `OPENAI_MODEL=gpt-5-nano` (or another valid model)
     * Do **not** pass `temperature` for `gpt-5-nano`
     * Use `max_output_tokens`, not `max_completion_tokens`

   * **Response object indexing**

     * Use `resp.output_text` instead of deep indexing fields

3. **Test LLM call in isolation**

   From a Python shell in the venv:

   ```python
   from openai import OpenAI
   import os

   client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

   resp = client.responses.create(
       model=os.getenv("OPENAI_MODEL", "gpt-5-nano"),
       input="Say 'this is a test taunt' in one short sentence."
   )

   print(resp.output_text)
   ```

   If this fails, your API setup is wrong. Fix that first.

---

## 10. Summary

* This repo is a **Connect 4 HAI demo** with a taunting LLM-powered robot.
* You run it via **FastAPI + Uvicorn** (`uvicorn app.main:app`).
* The **LLM taunts** live in `openai_agent.py → generate_taunt`.
* The **Responses API** is used with the **modern OpenAI Python SDK**.
* If anything fails, a deterministic **fallback taunt** keeps the game playable.
* This README is meant so **any teammate** can:

  * log into the Realm,
  * configure env vars,
  * run the app,
  * and understand **how the whole conversation flow works** end-to-end.



---


