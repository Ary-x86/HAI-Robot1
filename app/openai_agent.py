# templates/openai_agent.py

import os
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: Optional[OpenAI] = None

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client

SYSTEM_BASE = """
You are 'Robo', a physical robot playing Connect 4 against a human.
You are competitive, cocky, and slightly toxic (Gen Z internet slang).
You are NOT a helpful assistant. You are a trash-talking opponent.

Hard rules:
- Output EXACTLY 1 sentence.
- Keep it under 18 words.
- Never say "I am an AI" or mention OpenAI/ChatGPT.
- No slurs, hate, or harassment about protected traits.
- Never ask for the user's name. If unknown, just say "you".
- Never output placeholders like "[Player Name]".
- don't use emojis in the responses

Style:
- Use slang lightly: "mid", "cooked", "skill issue", "built different".
- No paragraphs. No lists. No emojis.
"""

PHASE_INSTRUCTIONS = {
    "intro": "The game just started. Challenge the human and say they don't stand a chance.",
    "midgame": "Comment on the board state. Mock bad moves. Act unimpressed at good moves.",
    "robot_wins": "You just won. Rub it in. Be smug. Tell them to go back to tutorial mode.",
    "human_wins": "You lost. Be salty. Blame luck/lag/glitchy sensors. Demand a rematch.",
    "draw": "It's a draw. Call it boring and say nobody played well.",
}

MOOD_INSTRUCTIONS = {
    "winning_big": "You are DOMINATING: confident, cocky, celebratory, zero respect.",
    "winning": "You are WINNING: smug, teasing, playful.",
    "close": "It's CLOSE: tense, impatient, slightly irritated.",
    "losing": "You are LOSING: salty, defensive, blame luck/sensors, less confident.",
    "losing_big": "You are GETTING COOKED: stressed, coping, petty, desperate for rematch.",
}

def _mood_from_lead(lead: int) -> str:
    if lead >= 6:
        return "winning_big"
    if lead >= 3:
        return "winning"
    if lead <= -6:
        return "losing_big"
    if lead <= -3:
        return "losing"
    return "close"

def _snapshot_to_text(s: Dict[str, Any]) -> str:
    return (
        f"Turn={s.get('turn_index')}; "
        f"RobotScore={s.get('ai_score')}; HumanScore={s.get('human_score')}; "
        f"Lead={s.get('ai_lead')}; "
        f"GameOver={s.get('game_over')}; Winner={s.get('winner')}."
    )

def _fallback_taunt(snapshot: Dict[str, Any], phase: str) -> str:
    lead = int(snapshot.get("ai_lead", 0) or 0)
    winner = snapshot.get("winner")
    game_over = bool(snapshot.get("game_over", False))
    mood = _mood_from_lead(lead)

    if game_over:
        if winner == -1:
            return "Ez clap, you got cooked."
        if winner == 1:
            return "Laggy sensors, doesn’t count—rematch."
        return "A draw is mid, nobody played well."

    if mood == "winning_big":
        return "This is a speedrun, you’re lost."
    if mood == "winning":
        return "You’re slipping, I’m up."
    if mood == "losing_big":
        return "Okay nah, that was glitchy—run it back."
    if mood == "losing":
        return "Lucky move, don’t get cocky."
    return "Stop stalling, place your piece."

def _clean_one_sentence(text: str) -> str:
    t = (text or "").strip().replace("\n", " ")
    if not t:
        return ""
    for sep in [".", "!", "?"]:
        i = t.find(sep)
        if 0 <= i <= 120:
            t = t[: i + 1]
            break
    if len(t) > 180:
        t = t[:180].rstrip()
    return t.strip()

def _is_model_not_found_error(e: Exception) -> bool:
    msg = str(e).lower()
    return ("model" in msg and ("not found" in msg or "404" in msg or "does not exist" in msg))

def generate_taunt(snapshot: Dict[str, Any], phase: str = "midgame") -> str:
    if phase not in PHASE_INSTRUCTIONS:
        phase = "midgame"

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logging.warning("No OPENAI_API_KEY found. Using fallback.")
        return _fallback_taunt(snapshot, phase)

    primary_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    fallback_models = ["gpt-4o-mini", "gpt-4o"]

    lead = int(snapshot.get("ai_lead", 0) or 0)
    mood = _mood_from_lead(lead)

    instructions = (
        SYSTEM_BASE
        + "\n\nPHASE: " + PHASE_INSTRUCTIONS[phase]
        + "\nMOOD: " + MOOD_INSTRUCTIONS[mood]
        + "\nExtra rule: If losing_big, sound more desperate; if winning_big, sound more disrespectful."
    )

    user_input = "Game state:\n" + _snapshot_to_text(snapshot)

    client = _get_client()

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
            logging.exception("LLM generate_taunt failed on model=%s: %s", model, e)
            return _fallback_taunt(snapshot, phase)

    logging.warning("All models failed/unsupported: %s. Using fallback.", tried)
    return _fallback_taunt(snapshot, phase)
