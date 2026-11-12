"""The real "Connection lost" dialog, on GPG's 1227x767 window (its default on a 1920x1200 screen)."""
import unittest

import cv2
import numpy as np

from app.core.bot import reconnect_button
from app.services.vision import VisionService
from tests.helpers import canvas

DIALOG = ('gpg767_dialog_connection_lost.png', 180, 280)  # its box: x 322-905, y 296-469
LIGHT_BLUE = (230, 210, 140)  # BGR, game art that passes the button's cyan test
DARK = (20, 20, 20)


def on_try_again(point, dy=0):
    """The label's ink spans x 347-422, y 431-444 (dy rows lower under a taller body)."""
    return point is not None and abs(point[0] - 385) <= 30 and abs(point[1] - 437 - dy) <= 8


class ConnectionLostTests(unittest.TestCase):
    def test_try_again_beside_cyan_game_art(self):
        # over a lab dialog: the light-blue Clone spell art left of the dialog box is cyan too
        point = reconnect_button(VisionService, canvas(DIALOG))
        self.assertTrue(on_try_again(point), point)

    def test_cyan_outside_the_dialog_box_is_never_tapped(self):
        frame = canvas(DIALOG)
        frame[425:450, 340:430] = frame[455, 600]  # TRY AGAIN painted over with the box's colour
        self.assertIsNone(reconnect_button(VisionService, frame))

    def test_art_in_a_thin_dark_outline_touching_the_box(self):
        # light-blue art larger than the label; its outline touches the box's left edge
        frame = canvas(DIALOG)
        cv2.circle(frame, (305, 400), 17, DARK, -1)
        cv2.circle(frame, (305, 400), 15, LIGHT_BLUE, -1)
        point = reconnect_button(VisionService, frame)
        self.assertTrue(on_try_again(point), point)

    def test_specks_in_dark_art_joined_to_the_box(self):
        # thick dark art joined to the box's bottom edge, with light specks in it (the Builder
        # Base's night trees and their fireflies)
        frame = canvas(DIALOG)
        frame[470:480, 330:400] = DARK
        for x in (345, 365, 385):
            frame[474:476, x:x + 2] = LIGHT_BLUE
        point = reconnect_button(VisionService, frame)
        self.assertTrue(on_try_again(point), point)

    def test_try_again_under_a_taller_body(self):
        # 20 more box rows above the button (one more body line): it ends 0.17 H under the title
        frame = canvas(DIALOG)
        frame = np.concatenate((frame[:420], frame[400:420], frame[420:-20]))
        point = reconnect_button(VisionService, frame)
        self.assertTrue(on_try_again(point, dy=20), point)


if __name__ == '__main__':
    unittest.main()
