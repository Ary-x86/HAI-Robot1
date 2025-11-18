async def notify_event(status, board, current_player):
    # v0: just print; later: HTTP POST to robot process
    print("Robot event:", status, "current_player:", current_player)
