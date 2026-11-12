'''The live capture shown by the point picker and the template capture dialogs.'''
import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from app.config import aspect_label

NO_CAPTURE = 'Could not capture the game window. Open Clash of Clans (and check Settings → Game window), then press Refresh.'


def frame_pixmap(frame, max_width, max_height):
    '''BGR numpy frame -> QPixmap scaled to fit ``max_width`` x ``max_height``.'''
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    (h, w) = rgb.shape[:2]
    # .copy() detaches the QImage from the numpy buffer, which Qt would otherwise
    # keep referencing after this function returns.
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image).scaled(max_width, max_height, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)


def capture_line(w, h, aspect_key, then):
    '''"Capture WxH (aspect). ``then``": the line under the preview.'''
    return f'''Capture {w}x{h} ({aspect_label(aspect_key, 'unsupported aspect')}). {then}'''
