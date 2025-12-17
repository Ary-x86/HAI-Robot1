# app/main.py

# run: uvicorn app.main:app --reload

# app/main.py

# terminal 1 – web + game
# uvicorn app.main:app --reload

# # terminal 2 – robot brain
# python robot/robot_client.py
# python robot/robot_brain.py


from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
import asyncio


from .game_logic import (
    new_board,
    drop_piece,
    check_winner,
    get_ai_move,
    score_board,
    HUMAN,
    AI,
    ROWS,
    COLS,
)

from .openai_agent import generate_taunt

app = FastAPI(title="HAI – Connect-4 Robot Demo")


class MoveRequest(BaseModel):
    column: int


#global game state (simple in-memory single-game for now)

state = {
    "board": new_board(),
    "current_player": HUMAN,   # human always starts
    "game_over": False,
    "winner": None,           # 1, -1, "draw", or None
    "turn_index": 0,          # increases every change (moves + resets)
    # last line the robot should say about the game
    "last_taunt": (
        "Yo, I'm your connect six seven. uh- i mean connect four robot. Drop your piece brochacho and prepare to lose"
    ),
}


def _snapshot():
    """Return a serializable snapshot of the game state + evaluation."""
    board = state["board"]
    ai_score = score_board(board, AI)
    human_score = score_board(board, HUMAN)
    ai_lead = ai_score - human_score

    return {
        "board": board,
        "current_player": state["current_player"],
        "game_over": state["game_over"],
        "winner": state["winner"],
        "turn_index": state["turn_index"],
        "ai_score": ai_score,
        "human_score": human_score,
        "ai_lead": ai_lead,
        "rows": ROWS,
        "cols": COLS,
        "last_taunt": state.get("last_taunt"),
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def index():
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Robo Connect-4</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {{
      --bg-color: #0f172a;
      --board-color: #1e3a8a;
      --board-shadow: #172554;
      --slot-empty: #1e293b;
      --p1-color: #ef4444; /* Human Red */
      --p1-shadow: #991b1b;
      --p2-color: #fbbf24; /* Robot Yellow */
      --p2-shadow: #b45309;
      --text-color: #f8fafc;
      --accent-green: #22c55e;
    }}

    body {{
      font-family: 'Segoe UI', Roboto, Helvetica, sans-serif;
      background: var(--bg-color);
      color: var(--text-color);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      overflow: hidden; 
    }}

    h1 {{
      font-weight: 800;
      letter-spacing: -1px;
      margin-bottom: 10px;
      text-transform: uppercase;
      background: linear-gradient(to right, #ef4444, #fbbf24);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-top: 0;
    }}

    /* --- Robot Area --- */
    .robot-area {{
      width: 100%;
      max-width: 480px;
      margin-bottom: 15px;
      display: flex;
      flex-direction: column;
      align-items: center;
    }}

    .chat-bubble {{
      background: #334155;
      border: 1px solid #475569;
      padding: 15px 20px;
      border-radius: 20px;
      border-bottom-left-radius: 2px;
      position: relative;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5);
      font-style: italic;
      color: #e2e8f0;
      min-height: 40px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      transition: transform 0.2s;
    }}
    
    .chat-bubble::after {{
      content: '';
      position: absolute;
      bottom: -10px;
      left: 0;
      border-width: 10px 10px 0;
      border-style: solid;
      border-color: #334155 transparent;
      display: block;
      width: 0;
    }}

    /* --- Status & Scoreboard --- */
    .meta-info {{
      display: flex;
      align-items: center;
      gap: 15px;
      margin-top: 15px;
    }}

    .status-badge {{
      font-size: 0.85rem;
      font-weight: bold;
      padding: 4px 12px;
      border-radius: 99px;
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
      transition: all 0.3s ease;
      text-transform: uppercase;
    }}

    .status-badge.active {{
      border-color: var(--accent-green);
      color: var(--accent-green);
      box-shadow: 0 0 10px rgba(34, 197, 94, 0.2);
    }}

    .scoreboard {{
      display: flex;
      gap: 15px;
      font-size: 0.85rem;
      background: rgba(30, 41, 59, 0.5);
      padding: 5px 15px;
      border-radius: 99px;
      border: 1px solid #334155;
      color: #cbd5e1;
    }}

    .score-item span {{
      color: #f8fafc;
      font-weight: bold;
      margin-left: 4px;
    }}

    /* --- The Board --- */
    #game-container {{
      position: relative;
      padding: 10px;
      background: #0f172a; 
      border-radius: 16px;
    }}

    #board {{
      display: grid;
      grid-template-columns: repeat({COLS}, 60px);
      grid-template-rows: repeat({ROWS}, 60px);
      gap: 8px;
      background: var(--board-color);
      padding: 12px;
      border-radius: 16px;
      box-shadow: 
        0 20px 25px -5px rgba(0, 0, 0, 0.5), 
        inset 0 -4px 4px var(--board-shadow);
      position: relative;
      z-index: 10;
    }}

    .cell {{
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: var(--slot-empty);
      box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);
      position: relative;
      overflow: hidden; 
    }}

    .piece {{
      width: 100%;
      height: 100%;
      border-radius: 50%;
      transform: translateY(-450px); 
      opacity: 0;
    }}

    /* Human Piece */
    .cell.p1 .piece {{
      background: radial-gradient(circle at 30% 30%, #fca5a5, var(--p1-color));
      box-shadow: inset 0 -3px 2px var(--p1-shadow);
      opacity: 1;
      transform: translateY(0);
    }}

    /* AI Piece */
    .cell.p-1 .piece {{
      background: radial-gradient(circle at 30% 30%, #fde68a, var(--p2-color));
      box-shadow: inset 0 -3px 2px var(--p2-shadow);
      opacity: 1;
      transform: translateY(0);
    }}

    .drop-anim {{
      animation: dropBounce 0.5s cubic-bezier(0.25, 1.25, 0.5, 1) forwards;
    }}

    @keyframes dropBounce {{
      0% {{ transform: translateY(-400px); opacity: 1; }}
      70% {{ transform: translateY(0px); }}
      85% {{ transform: translateY(-20px); }}
      100% {{ transform: translateY(0); opacity: 1; }}
    }}

    /* --- Interaction Layer --- */
    #interaction-layer {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      display: grid;
      grid-template-columns: repeat({COLS}, 1fr);
      z-index: 20;
      padding: 12px;
      box-sizing: border-box;
      gap: 8px;
    }}

    .col-trigger {{
      height: 100%;
      background: transparent;
      cursor: pointer;
      border-radius: 99px;
      transition: background 0.2s;
      position: relative;
    }}

    .col-trigger:hover::before {{
      content: '';
      position: absolute;
      top: -50px;
      left: 50%;
      transform: translateX(-50%);
      width: 50px;
      height: 50px;
      border-radius: 50%;
      background: var(--p1-color);
      opacity: 0.5;
      box-shadow: 0 0 15px var(--p1-color);
      pointer-events: none;
    }}

    .col-trigger:active {{ background: rgba(255, 255, 255, 0.05); }}
    .col-trigger:disabled {{ cursor: not-allowed; pointer-events: none; }}
    .col-trigger:disabled:hover::before {{ display: none; }}

    /* --- Controls --- */
    .controls {{
      margin-top: 20px;
      display: flex;
      gap: 10px;
    }}

    button.btn-reset {{
      background: transparent;
      border: 2px solid #475569;
      color: #94a3b8;
      padding: 10px 20px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: bold;
      text-transform: uppercase;
      transition: all 0.2s;
    }}

    button.btn-reset:hover {{
      border-color: #ef4444;
      color: #ef4444;
    }}

  </style>
</head>
<body>

  <h1>Robo Connect-4</h1>

  <div class="robot-area">
    <div class="chat-bubble" id="robot-text">
      "Initializing connection... prepare to lose."
    </div>
    
    <div class="meta-info">
      <div id="status-badge" class="status-badge">Connecting...</div>
      
      <div class="scoreboard">
        <div class="score-item">You: <span id="score-human">0</span></div>
        <div class="score-item">Bot: <span id="score-ai">0</span></div>
        <div class="score-item">Lead: <span id="score-lead">0</span></div>
      </div>
    </div>
  </div>

  <div id="game-container">
    <div id="board"></div>
    <div id="interaction-layer"></div>
  </div>

  <div class="controls">
    <button class="btn-reset" onclick="resetGame()">Restart Game</button>
  </div>

  <script>
    const ROWS = {ROWS};
    const COLS = {COLS};

    let localBoard = Array(ROWS).fill().map(() => Array(COLS).fill(0));

    function init() {{
        const boardEl = document.getElementById("board");
        const interactEl = document.getElementById("interaction-layer");

        for (let r = 0; r < ROWS; r++) {{
            for (let c = 0; c < COLS; c++) {{
                const cell = document.createElement("div");
                cell.className = "cell";
                cell.id = `cell-${{r}}-${{c}}`;
                
                const piece = document.createElement("div");
                piece.className = "piece";
                piece.id = `piece-${{r}}-${{c}}`;
                cell.appendChild(piece);
                
                boardEl.appendChild(cell);
            }}
        }}

        for (let c = 0; c < COLS; c++) {{
            const trigger = document.createElement("div");
            trigger.className = "col-trigger";
            trigger.id = `col-${{c}}`;
            trigger.onclick = () => playMove(c);
            interactEl.appendChild(trigger);
        }}
    }}

    function updateDisplay(state) {{
        const robotText = document.getElementById("robot-text");
        const statusBadge = document.getElementById("status-badge");
        
        // --- UPDATE SCORES ---
        document.getElementById("score-human").textContent = state.human_score;
        document.getElementById("score-ai").textContent = state.ai_score;
        document.getElementById("score-lead").textContent = state.ai_lead;

        // Update Text
        if (state.last_taunt) {{
            robotText.textContent = `"${{state.last_taunt}}"`;
        }}

        // Update Status Badge
        if (state.game_over) {{
            if (state.winner === 1) statusBadge.textContent = "YOU WIN!";
            else if (state.winner === -1) statusBadge.textContent = "ROBOT WINS";
            else statusBadge.textContent = "DRAW";
            statusBadge.classList.remove("active");
            disableInput(true);
        }} else {{
            if (state.current_player === 1) {{
                statusBadge.textContent = "YOUR TURN";
                statusBadge.classList.add("active");
                disableInput(false);
            }} else {{
                statusBadge.textContent = "ROBOT THINKING...";
                statusBadge.classList.remove("active");
                disableInput(true);
            }}
        }}

        // Update Board
        for (let r = 0; r < ROWS; r++) {{
            for (let c = 0; c < COLS; c++) {{
                const newVal = state.board[r][c];
                const oldVal = localBoard[r][c];
                const cell = document.getElementById(`cell-${{r}}-${{c}}`);
                const piece = document.getElementById(`piece-${{r}}-${{c}}`);

                if (newVal !== 0) {{
                    cell.className = newVal === 1 ? "cell p1" : "cell p-1";
                    
                    if (oldVal === 0) {{
                        piece.classList.remove("drop-anim");
                        void piece.offsetWidth; 
                        piece.classList.add("drop-anim");
                    }} else {{
                         piece.style.transform = "translateY(0)";
                         piece.style.opacity = "1";
                    }}
                }} else {{
                    cell.className = "cell";
                    piece.style.opacity = "0";
                    piece.classList.remove("drop-anim");
                }}
            }}
        }}
        localBoard = JSON.parse(JSON.stringify(state.board));
    }}

    function disableInput(disabled) {{
        for (let c = 0; c < COLS; c++) {{
            const btn = document.getElementById(`col-${{c}}`);
            if(disabled) btn.setAttribute("disabled", "true");
            else btn.removeAttribute("disabled");
        }}
    }}

    async function fetchState() {{
        try {{
            const res = await fetch("/state");
            const data = await res.json();
            updateDisplay(data);
            
            if (!data.game_over && data.current_player === -1) {{
                setTimeout(fetchState, 1000);
            }} else if (!data.game_over) {{
                setTimeout(fetchState, 3000);
            }}
        }} catch (e) {{ console.error(e); }}
    }}

    async function playMove(col) {{
        disableInput(true); 
        try {{
            const res = await fetch("/move", {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{ column: col }}),
            }});
            
            if (!res.ok) {{
                const err = await res.json();
                alert(err.detail);
                disableInput(false);
                return;
            }}
            
            const data = await res.json();
            updateDisplay(data);
            
            if (!data.game_over && data.current_player === -1) {{
                fetchState();
            }}
        }} catch (e) {{
            console.error(e);
            disableInput(false);
        }}
    }}

    async function resetGame() {{
        const res = await fetch("/reset", {{ method: "POST" }});
        const data = await res.json();
        localBoard = Array(ROWS).fill().map(() => Array(COLS).fill(0));
        updateDisplay(data);
    }}

    init();
    fetchState();

  </script>
</body>
</html>
"""
    return HTMLResponse(html)

@app.get("/state")
async def get_state():
    return _snapshot()

@app.post("/reset")
async def reset_game():
    state["board"] = new_board()
    state["current_player"] = HUMAN
    state["game_over"] = False
    state["winner"] = None
    state["last_taunt"] = "New game, same robot. Drop your first chip if you’re ready to lose again."
    # IMPORTANT: Increment AFTER setting text
    state["turn_index"] += 1 
    return _snapshot()

@app.post("/move")
async def play_move(req: MoveRequest):
    if state["game_over"]:
        raise HTTPException(status_code=400, detail="Game finished")
    if state["current_player"] != HUMAN:
        raise HTTPException(status_code=400, detail="Not your turn")

    board = state["board"]

    # 1) Human move
    try:
        drop_piece(board, req.column, HUMAN)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    event_type = "midgame"
    winner = check_winner(board)
    
    if winner is not None:
        state["game_over"] = True
        state["winner"] = winner
        event_type = "human_wins" if winner == HUMAN else "robot_wins" if winner == AI else "draw"
    else:
        # 2) AI move
        ai_col = get_ai_move(board)
        drop_piece(board, ai_col, AI)
        winner2 = check_winner(board)
        if winner2 is not None:
            state["game_over"] = True
            state["winner"] = winner2
            event_type = "robot_wins" if winner2 == AI else "human_wins" if winner2 == HUMAN else "draw"

    state["current_player"] = HUMAN

    # 3) Generate Taunt FIRST
    snap_for_llm = _snapshot()
    snap_for_llm.pop("last_taunt", None)

    try:
        new_taunt = await run_in_threadpool(generate_taunt, snap_for_llm, event_type)
        state["last_taunt"] = new_taunt
    except Exception as e:
        print("LLM error:", e)
        # Fallback if LLM fails
        state["last_taunt"] = "..." 

    # 4) Increment turn index LAST
    # This prevents the robot from reading the state before the new text is ready
    state["turn_index"] += 1

    return _snapshot()