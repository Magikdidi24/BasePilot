'''Modal dialogs for the Qt UI.'''
from __future__ import annotations
from PySide6.QtWidgets import QMessageBox

def show_error(parent, title, message):
    QMessageBox.critical(parent, title, message)


def show_under_development(parent):
    QMessageBox.information(parent, 'Under development', 'This feature is under development.')


