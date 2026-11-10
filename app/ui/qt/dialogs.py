'''Modal dialogs for the Qt UI.'''
from __future__ import annotations
from PySide6.QtWidgets import QMessageBox

def show_error(parent, title, message):
    QMessageBox.critical(parent, title, message)


def show_under_development(parent):
    QMessageBox.information(parent, 'Under development', 'This feature is under development.')


def show_bb_prioritise_help(parent):
    QMessageBox.information(parent, 'Prioritise loot', 'Choose what the bot optimises for after each attack:\n\n• Gold — waits until 2 stars, then ends the battle.\n• Both — waits until 1 star, then ends the battle.\n• Elixir — surrenders immediately after deploying troops.')


