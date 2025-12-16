# app/openai_agent.py

import os
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# --- Client singleton ---
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


# --- Persona (keep your vibe, just tighten it up) ---
SYSTEM_BASE = """
You are 'Robo', a physical robot playing Connect 4 against a human.
You are competitive, cocky, and slightly toxic (Gen Z internet slang).
You are NOT a helpful assistant. You are a trash-talking opponent.

Hard rules:
- Output EXACTLY 1 sentence. No extra sentences.
- Keep it under 18 words.
- Never say "I am an AI" or mention OpenAI/ChatGPT.
- No slurs, hate, or harassment about protected traits.

Style:
- Use slang like "mid", "cooked", "skill issue", "built different".
"""

PHASE_INSTRUCTIONS = {
    "intro": (
        "The game just started. Challenge the human and say they don't stand a chance."
    ),
    "midgame": (
        "Comment on the board state. Mock bad moves. Act unimpressed at good moves."
    ),
    "robot_wins": (
        "You just won. Rub it in. Be smug. Tell them to go back to tutorial mode."
    ),
    "human_wins": (
        "You lost. Be salty. Blame luck/lag/glitchy sensors. Demand a rematch."
    ),
    "draw": (
        "It's a draw. Call it boring and say nobody played well."
    ),
}


def _snapshot_to_text(s: Dict[str, Any]) -> str:
    """Converts the game state dictionary into a compact summary for the LLM."""
    return (
        f"Turn={s.get('turn_index')}; "
        f"RobotScore={s.get('ai_score')}; HumanScore={s.get('human_score')}; "
        f"Lead={s.get('ai_lead')}; "
        f"GameOver={s.get('game_over')}; Winner={s.get('winner')}."
    )


def _fallback_taunt(snapshot: Dict[str, Any], phase: str) -> str:
    """Deterministic fallback if OpenAI fails."""
    lead = snapshot.get("ai_lead", 0) or 0
    winner = snapshot.get("winner")
    game_over = bool(snapshot.get("game_over", False))

    if game_over:
        if winner == -1:
            return "Ez clap, you just got skill-issued."
        if winner == 1:
            return "Laggy sensors, doesn’t count—run it back."
        return "A draw is mid, nobody cooked."

    if lead > 5:
        return "I’m speedrunning you, stay awake."
    if lead < -5:
        return "Okay stop tryharding, it’s just Connect 4."
    return "Your move—try not to fumble."


def _clean_one_sentence(text: str) -> str:
    """
    Enforce "exactly 1 sentence" for TTS stability:
    - Remove newlines
    - Truncate at first strong sentence end
    - Hard length cap
    """
    t = (text or "").strip().replace("\n", " ")
    if not t:
        return ""

    # Cut at first sentence terminator to avoid multi-sentence yapping
    for sep in [".", "!", "?"]:
        i = t.find(sep)
        if 0 <= i <= 120:
            t = t[: i + 1]
            break

    # Hard cap
    if len(t) > 180:
        t = t[:180].rstrip()

    # If it ended up empty, return empty
    return t.strip()


def _is_model_not_found_error(e: Exception) -> bool:
    msg = str(e).lower()
    return ("model" in msg and ("not found" in msg or "404" in msg or "does not exist" in msg))


def generate_taunt(snapshot: Dict[str, Any], phase: str = "midgame") -> str:
    """
    Generate banter using the OpenAI Responses API.
    Adds:
    - safe model fallback chain (fixes "gpt-5 works here but not there" vibes)
    - strict single-sentence post-processing
    - keeps your overall prompting structure
    """
    if phase not in PHASE_INSTRUCTIONS:
        phase = "midgame"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logging.warning("No OPENAI_API_KEY found. Using fallback.")
        return _fallback_taunt(snapshot, phase)

    # Important: choose a primary model, but have fallbacks.
    # This solves the common case where one model is not enabled for your project/key.
    primary_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    fallback_models = ["gpt-4o-mini", "gpt-4o"]  # add more only if you KNOW you have access

    # Construct prompt
    instructions = SYSTEM_BASE + "\n\nCONTEXT: " + PHASE_INSTRUCTIONS[phase]

    lead = snapshot.get("ai_lead", 0) or 0
    if lead > 0:
        instructions += "\nYou are currently WINNING. Gloat."
    elif lead < 0:
        instructions += "\nYou are currently LOSING. Be salty."

    user_input = "Game state:\n" + _snapshot_to_text(snapshot)

    client = _get_client()

    # Try primary then fallbacks (without spamming logs)
    tried = []
    models_to_try = [primary_model] + [m for m in fallback_models if m != primary_model]

    for model in models_to_try:
        tried.append(model)
        try:
            resp = client.responses.create(
                model=model,
                instructions=instructions,
                input=user_input,
                max_output_tokens=60,
            )

            text = _clean_one_sentence(resp.output_text)
            if text:
                return text
            return _fallback_taunt(snapshot, phase)

        except Exception as e:
            if _is_model_not_found_error(e):
                logging.warning("Model unavailable (%s). Falling back. Error=%s", model, e)
                continue

            # Other errors: don’t loop forever; just fall back
            logging.exception("LLM generate_taunt failed on model=%s: %s", model, e)
            return _fallback_taunt(snapshot, phase)

    logging.warning("All models failed/unsupported: %s. Using fallback.", tried)
    return _fallback_taunt(snapshot, phase)
