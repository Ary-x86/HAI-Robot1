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


SYSTEM_BASE = """
You are 'Robo', an English-speaking robot playing Connect 4 against a human.
You are cocky and slightly annoying, but never rude or profane.
You use short, casual Gen Z-ish internet tone.
You ALWAYS answer with ONE single sentence, no quotes, no bullet points.
Max ~140 characters. Classroom-safe. No swearing, slurs, politics or sex.
You talk directly to the human opponent, not about them in third person.
"""

PHASE_INSTRUCTIONS = {
    "intro": (
        "You are inviting the human to start a new Connect 4 game. "
        "Sound confident and teasing, but friendly. Mention starting the game."
    ),
    "midgame": (
        "The game is ongoing. Comment on who's ahead based on the scores. "
        "Light trash talk, but keep it fun and playful."
    ),
    "robot_wins": (
        "The robot just won the game. Be smug, slightly toxic but still playful. "
        "Congratulate yourself, lightly roast the human."
    ),
    "human_wins": (
        "The human just won the game. Be salty but respectful. "
        "Admit defeat and hint at a rematch."
    ),
    "draw": (
        "The game ended in a draw. Call it a 'mid' ending or joke that no one clutched."
    ),
}


def _snapshot_to_text(s: Dict[str, Any]) -> str:
    return (
        f"Turn_index={s.get('turn_index')}, "
        f"ai_score={s.get('ai_score')}, human_score={s.get('human_score')}, "
        f"ai_lead={s.get('ai_lead')}, game_over={s.get('game_over')}, "
        f"winner={s.get('winner')}."
    )


def _fallback_taunt(snapshot: Dict[str, Any], phase: str) -> str:
    lead = snapshot.get("ai_lead", 0) or 0
    winner = snapshot.get("winner")
    game_over = snapshot.get("game_over", False)

    if game_over:
        if winner == -1:
            return "GG, I told you I was built different."
        if winner == 1:
            return "Alright, you got me this time, respect."
        if winner == "draw":
            return "Draw game, kinda mid for both of us."
        return "Game over, that was wild."
    else:
        if phase == "intro":
            return "Yo, I’m your Connect 4 robot, drop a piece and let’s see if you can survive."
        if lead > 10:
            return "I’m lowkey speedrunning you right now."
        if lead > 4:
            return "I’m kinda ahead, you sure about that strategy?"
        if lead < -10:
            return "Okay, chill, you’re actually stomping me. ts pmo brochacho"
        if lead < -4:
            return "You’re up right now, but don’t get comfy."
        return "Close game so far, one bad move and you’re cooked."


def generate_taunt(snapshot: Dict[str, Any], phase: str = "midgame") -> str:
    """
    Generate one-sentence banter using the new Responses API.

    Uses:
        model = $OPENAI_MODEL or "gpt-5-nano"
    """
    phase = phase if phase in PHASE_INSTRUCTIONS else "midgame"
    model = os.getenv("OPENAI_MODEL", "gpt-5-nano")

    # No key? Just return deterministic text.
    if not os.getenv("OPENAI_API_KEY"):
        return _fallback_taunt(snapshot, phase)

    instructions = SYSTEM_BASE + "\n" + PHASE_INSTRUCTIONS[phase]

    # Short user input, game state goes here
    user_input = (
        "Based on this game state, say ONE sentence of banter.\n"
        + _snapshot_to_text(snapshot)
    )

    try:
        client = _get_client()
        resp = client.responses.create(
            model=model,
            instructions=instructions,
            input=user_input,
            max_output_tokens=64,  # correct param name for Responses API
        )

        # Use the helper instead of digging into resp.output[...]
        text = (resp.output_text or "").strip().replace("\n", " ")

        # If somehow empty, fall back so the robot still says something
        if not text:
            return _fallback_taunt(snapshot, phase)

        # Hard cap length
        if len(text) > 180:
            text = text[:180]

        return text

    except Exception as e:
        logging.exception("LLM generate_taunt failed, falling back: %s", e)
        return _fallback_taunt(snapshot, phase)
