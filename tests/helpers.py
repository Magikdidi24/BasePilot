"""Helpers shared by the tests: live crops of the game (no player name or gem count in them),
pasted back on a black frame where they were taken."""
from pathlib import Path

import numpy as np

from app.config import Config
from app.utils.common import read_image

FIXTURES = Path(__file__).parent / 'fixtures'
GPG = (1227, 767)  # (w, h): the default Google Play Games window, 16:10
WAYDROID = (1920, 1200)  # (w, h): where the October 2026 UI was first measured


def canvas(*crops, size=GPG):
    """A black frame of ``size`` (w, h) with each crop pasted back where it was taken: crops
    are ``(file in tests/fixtures, x, y)``, x and y of the crop's top-left corner. The Config
    is sized for the frame, as for a live capture."""
    (w, h) = size
    frame = np.zeros((h, w, 3), np.uint8)
    for (name, x, y) in crops:
        img = read_image(FIXTURES / name)
        if img is None:
            raise FileNotFoundError(FIXTURES / name)
        frame[y:y + img.shape[0], x:x + img.shape[1]] = img
    Config().set_target_size_from_frame(frame)
    return frame
