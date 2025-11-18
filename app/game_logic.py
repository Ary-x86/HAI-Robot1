# app/game_logic.py

import math

ROWS = 6
COLS = 7

# Players
HUMAN = 1     # you (red, for example)
AI = -1       # robot / computer


def new_board():
    """Create an empty 6x7 board (0 = empty)."""
    return [[0 for _ in range(COLS)] for _ in range(ROWS)]


def drop_piece(board, col, player):
    """
    Drop a piece into column `col` for `player` (1 or -1).
    Returns (row, col) where the piece landed.
    Raises ValueError if column is invalid or full.
    """
    if col < 0 or col >= COLS:
        raise ValueError("Invalid column")

    # column full?
    if board[0][col] != 0:
        raise ValueError("Column full")

    # find lowest free row
    for r in range(ROWS - 1, -1, -1):
        if board[r][col] == 0:
            board[r][col] = player
            return r, col

    # should never reach here if we checked column full above
    raise ValueError("Column full")


def check_winner(board):
    """
    Return:
      HUMAN (1)  if you win,
      AI (-1)    if AI wins,
      'draw'     if board full and no winner,
      None       otherwise.
    """
    # horizontal
    for r in range(ROWS):
        for c in range(COLS - 3):
            window = [board[r][c + i] for i in range(4)]
            if window[0] != 0 and all(x == window[0] for x in window):
                return window[0]

    # vertical
    for c in range(COLS):
        for r in range(ROWS - 3):
            window = [board[r + i][c] for i in range(4)]
            if window[0] != 0 and all(x == window[0] for x in window):
                return window[0]

    # diagonal down-right
    for r in range(ROWS - 3):
        for c in range(COLS - 3):
            window = [board[r + i][c + i] for i in range(4)]
            if window[0] != 0 and all(x == window[0] for x in window):
                return window[0]

    # diagonal up-right
    for r in range(3, ROWS):
        for c in range(COLS - 3):
            window = [board[r - i][c + i] for i in range(4)]
            if window[0] != 0 and all(x == window[0] for x in window):
                return window[0]

    # draw?
    if all(board[0][c] != 0 for c in range(COLS)):
        return "draw"

    return None


def get_valid_columns(board):
    return [c for c in range(COLS) if board[0][c] == 0]


def _evaluate_window(window, player):
    """
    Heuristic score for a 4-cell window relative to `player`.
    """
    score = 0
    opp = HUMAN if player == AI else AI

    if window.count(player) == 4:
        score += 100
    elif window.count(player) == 3 and window.count(0) == 1:
        score += 5
    elif window.count(player) == 2 and window.count(0) == 2:
        score += 2

    # block opponent
    if window.count(opp) == 3 and window.count(0) == 1:
        score -= 4

    return score


def score_board(board, player):
    """
    Overall heuristic score of the board for `player`.
    Positive = good for player, negative = bad.
    """
    score = 0

    # center column preference (encourage central play)
    center_col = COLS // 2
    center_array = [board[r][center_col] for r in range(ROWS)]
    score += center_array.count(player) * 3

    # horizontal
    for r in range(ROWS):
        row = [board[r][c] for c in range(COLS)]
        for c in range(COLS - 3):
            window = row[c:c+4]
            score += _evaluate_window(window, player)

    # vertical
    for c in range(COLS):
        col = [board[r][c] for r in range(ROWS)]
        for r in range(ROWS - 3):
            window = col[r:r+4]
            score += _evaluate_window(window, player)

    # diagonal down-right
    for r in range(ROWS - 3):
        for c in range(COLS - 3):
            window = [board[r + i][c + i] for i in range(4)]
            score += _evaluate_window(window, player)

    # diagonal up-right
    for r in range(ROWS - 3):
        for c in range(COLS - 3):
            window = [board[r + 3 - i][c + i] for i in range(4)]
            score += _evaluate_window(window, player)

    return score


def _minimax(board, depth, alpha, beta, maximizing):
    """
    Minimax with alpha-beta pruning.
    AI is the maximizing player.
    """
    winner = check_winner(board)
    if depth == 0 or winner is not None:
        if winner == AI:
            return None, 10_000
        elif winner == HUMAN:
            return None, -10_000
        elif winner == "draw":
            return None, 0
        else:
            return None, score_board(board, AI)

    valid_cols = get_valid_columns(board)
    if not valid_cols:
        return None, 0

    if maximizing:
        value = -math.inf
        best_col = valid_cols[0]
        for col in valid_cols:
            temp = [row[:] for row in board]
            drop_piece(temp, col, AI)
            _, new_score = _minimax(temp, depth - 1, alpha, beta, False)
            if new_score > value:
                value = new_score
                best_col = col
            alpha = max(alpha, value)
            if alpha >= beta:
                break
        return best_col, value
    else:
        value = math.inf
        best_col = valid_cols[0]
        for col in valid_cols:
            temp = [row[:] for row in board]
            drop_piece(temp, col, HUMAN)
            _, new_score = _minimax(temp, depth - 1, alpha, beta, True)
            if new_score < value:
                value = new_score
                best_col = col
            beta = min(beta, value)
            if alpha >= beta:
                break
        return best_col, value


def get_ai_move(board, depth: int = 4) -> int:
    """Return best column for AI with given search depth."""
    col, _ = _minimax(board, depth, -math.inf, math.inf, True)
    return col
