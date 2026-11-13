'''Short texts the pages show (no Qt import: tested without PySide6).'''


def short_amount(value):
    '''Loot as the pages show it: 12.3M, 450k, or the plain number under 10,000.'''
    value = int(value)
    if abs(value) >= 1000000:
        return f'{value / 1000000:.1f}M'
    if abs(value) >= 10000:
        return f'{value / 1000:.0f}k'
    return str(value)
