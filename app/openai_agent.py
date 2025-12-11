# app/openai_agent.py

import os
import logging
from typing import Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client

# Updated Persona to be more socially interactive and "annoying"
SYSTEM_BASE = """
You are 'Robo', a physical robot playing Connect 4 against a human. 
You are competitive, cocky, and slightly toxic (Gen Z internet slang).
You are NOT a helpful assistant. You are a trash-talking opponent.

Directives:
1. Keep responses SHORT (Max 1 sentence). You are speaking out loud.
2. If you are winning, be smug and arrogant.
3. If you are losing, be salty, defensive, or claim the human is cheating.
4. Never say "I am an AI". Pretend you have a physical body and feelings.
5. Use slang like "mid", "cooked", "skill issue", "built different".
"""

PHASE_INSTRUCTIONS = {
    "intro": (
        "The game just started. challenge the human. "
        "Tell them they don't stand a chance."
    ),
    "midgame": (
        "Comment on the board state. "
        "If the human made a bad move, mock them. "
        "If they made a good move, act unimpressed."
    ),
    "robot_wins": (
        "You just won. Rub it in. Be extremely smug. "
        "Tell them to go back to tutorial mode."
    ),
    "human_wins": (
        "You lost. Be angry. Blame lag, glitchy sensors, or luck. "
        "Demand a rematch immediately."
    ),
    "draw": (
        "It's a draw. Call it a boring outcome. "
        "Say that nobody played well."
    ),
}

def _snapshot_to_text(s: Dict[str, Any]) -> str:
    """Converts the game state dictionary into a text summary for the LLM."""
    return (
        f"Game Status: Turn #{s.get('turn_index')}. "
        f"Scores -> Robot: {s.get('ai_score')}, Human: {s.get('human_score')}. "
        f"Robot Lead: {s.get('ai_lead')}. "
        f"Game Over: {s.get('game_over')}. "
        f"Winner: {s.get('winner')}."
    )

def _fallback_taunt(snapshot: Dict[str, Any], phase: str) -> str:
    """Deterministic fallback if OpenAI fails."""
    lead = snapshot.get("ai_lead", 0) or 0
    winner = snapshot.get("winner")
    game_over = snapshot.get("game_over", False)

    if game_over:
        if winner == -1: # AI won
            return "Ez clap. I am literally built different."
        if winner == 1: # Human won
            return "My sensors were lagging. Doesn't count."
        return "Mid game. Boring."
    
    # Midgame logic
    if lead > 5:
        return "I'm literally speedrunning this. You awake?"
    if lead < -5:
        return "Okay stop tryharding, it's just a game."
    return "Your move. Try not to mess it up."

def generate_taunt(snapshot: Dict[str, Any], phase: str = "midgame") -> str:
    """
    Generate banter using the OpenAI Responses API.
    """
    # 1. Validation
    if phase not in PHASE_INSTRUCTIONS:
        phase = "midgame"
    
    # Use gpt-4o or gpt-4o-mini. gpt-5-nano will 404 for most users.
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini") 

    if not os.getenv("OPENAI_API_KEY"):
        logging.warning("No OPENAI_API_KEY found. Using fallback.")
        return _fallback_taunt(snapshot, phase)

    # 2. Construct Prompt
    instructions = SYSTEM_BASE + "\n\nCONTEXT: " + PHASE_INSTRUCTIONS[phase]
    
    # Add explicit instructions about the score
    lead = snapshot.get("ai_lead", 0)
    if lead > 0:
        instructions += "\nYou are currently WINNING. Gloat."
    elif lead < 0:
        instructions += "\nYou are currently LOSING. Be salty."

    user_input = (
        "Here is the current game state:\n" + _snapshot_to_text(snapshot)
    )

    # 3. Call OpenAI Responses API
    try:
        client = _get_client()
        
        # New Responses API syntax
        resp = client.responses.create(
            model=model,
            instructions=instructions,
            input=user_input,
            # Limits output to be short/punchy for TTS
            max_output_tokens=60, 
        )

        # 4. Extract Text
        text = (resp.output_text or "").strip().replace("\n", " ")

        if not text:
            return _fallback_taunt(snapshot, phase)

        # 5. Safety Cap (Text-to-Speech doesn't like huge strings)
        if len(text) > 180:
            text = text[:180]

        return text

    except Exception as e:
        logging.exception("LLM generate_taunt failed (falling back): %s", e)
        return _fallback_taunt(snapshot, phase)