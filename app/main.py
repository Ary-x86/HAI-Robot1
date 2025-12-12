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
async def index():
    # (this is exactly your HTML, unchanged)
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Connect-4 vs Robot</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      background: #0f172a;
      color: #e5e7eb;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 20px;
    }}
    h1 {{
      margin-bottom: 0.2rem;
    }}
    #status {{
      margin-bottom: 1rem;
    }}
    #board {{
      display: grid;
      grid-template-columns: repeat({COLS}, 60px);
      grid-template-rows: repeat({ROWS}, 60px);
      gap: 6px;
      background: #1e293b;
      padding: 8px;
      border-radius: 12px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.4);
    }}
    .cell {{
      width: 60px;
      height: 60px;
      border-radius: 999px;
      background: #020617;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: inset 0 0 10px rgba(0,0,0,0.7);
    }}
    .cell.red {{
      background: #ef4444;
    }}
    .cell.yellow {{
      background: #facc15;
    }}
    button.col-btn {{
      margin: 2px;
      padding: 4px 8px;
      border-radius: 6px;
      border: none;
      background: #22c55e;
      color: #0f172a;
      cursor: pointer;
      font-size: 0.8rem;
    }}
    button.col-btn:disabled {{
      opacity: 0.4;
      cursor: default;
    }}
  </style>
</head>
<body>
  <h1>Connect-4 vs Robot</h1>
  <p id="status">Loading game…</p>

  <div id="col-buttons"></div>
  <div id="board"></div>

  <script>
    const ROWS = {ROWS};
    const COLS = {COLS};

    let currentState = null;

    function createBoard() {{
      const boardEl = document.getElementById("board");
      boardEl.innerHTML = "";
      for (let r = 0; r < ROWS; r++) {{
        for (let c = 0; c < COLS; c++) {{
          const cell = document.createElement("div");
          cell.id = `cell-${{r}}-${{c}}`;
          cell.className = "cell";
          boardEl.appendChild(cell);
        }}
      }}
    }}

    function createColumnButtons() {{
      const btnContainer = document.getElementById("col-buttons");
      btnContainer.innerHTML = "";
      for (let c = 0; c < COLS; c++) {{
        const btn = document.createElement("button");
        btn.textContent = c + 1;
        btn.className = "col-btn";
        btn.onclick = () => playMove(c);
        btn.id = `col-btn-${{c}}`;
        btnContainer.appendChild(btn);
      }}
    }}

    function updateBoard(board) {{
      for (let r = 0; r < ROWS; r++) {{
        for (let c = 0; c < COLS; c++) {{
          const cell = document.getElementById(`cell-${{r}}-${{c}}`);
          const value = board[r][c];
          cell.className = "cell";
          if (value === 1) {{
            cell.classList.add("red");
          }} else if (value === -1) {{
            cell.classList.add("yellow");
          }}
        }}
      }}
    }}

    function updateStatus(state) {{
      const status = document.getElementById("status");
      const humanScore = state.human_score;
      const aiScore = state.ai_score;
      const lead = state.ai_lead;

      let txt = "";
      if (state.game_over) {{
        if (state.winner === 1) {{
          txt = "You WON 🎉 (human)";
        }} else if (state.winner === -1) {{
          txt = "ToxicBot won 😈";
        }} else {{
          txt = "Draw 🤝";
        }}
      }} else {{
        txt = state.current_player === 1 ? "Your turn (red)" : "AI thinking…";
      }}
      txt += ` — score human: ${{humanScore}}, AI: ${{aiScore}}, AI lead: ${{lead}}`;
      status.textContent = txt;

      // disable buttons if game over or AI turn
      for (let c = 0; c < COLS; c++) {{
        const btn = document.getElementById(`col-btn-${{c}}`);
        if (!btn) continue;
        btn.disabled = state.game_over || state.current_player !== 1;
      }}
    }}

    async function fetchState() {{
      const res = await fetch("/state");
      const data = await res.json();
      currentState = data;
      updateBoard(data.board);
      updateStatus(data);
    }}

    async function playMove(col) {{
      if (!currentState || currentState.game_over) return;
      if (currentState.current_player !== 1) return;

      const res = await fetch("/move", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ column: col }}),
      }});

      if (!res.ok) {{
        const err = await res.json();
        alert("Error: " + (err.detail || "unknown"));
        return;
      }}

      const data = await res.json();
      currentState = data;
      updateBoard(data.board);
      updateStatus(data);
    }}

    // init
    createBoard();
    createColumnButtons();
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