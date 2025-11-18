import openai

def generate_taunt(game_status, score, last_move, player_name="player"):
    prompt = f"""
    You are an annoying but still playful robot playing Connect 4 against a human.
    Game status: {game_status}
    Heuristic score from robot POV: {score}
    Last human move: column {last_move}

    Respond with ONE short sentence, no profanity, but clearly teasing them.
    Use casual Gen Z-ish internet tone, but keep it safe for a classroom.
    """
    # call gpt-5-nano or whatever model Joost allows
    ...
