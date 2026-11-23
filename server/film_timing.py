"""Frame-exact shot timing for the 24 fps export and its review."""

FPS = 24


def frame_count(shot):
    return (shot["end"] - shot["start"]) * FPS


def camera_tick(frame, count):
    return frame * 71 / max(1, count - 1)
