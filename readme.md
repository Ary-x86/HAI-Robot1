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
