'''UI constants ported from the legacy theme module.'''
ATTACK_STRATEGIES: dict[str, int] = {
    'Sneaky Goblins': 1,
    'Super Minions': 2,
    'Valkyries': 3,
    'Edrags': 4 }
# The Builder Base fight reads the troops on the bar and plays each with its own profile
# (app.core.bb_strategy): one strategy, whatever the army.
BUILDER_BASE_ATTACK_STRATEGIES: dict[str, int] = {
    'Your army (auto)': 5 }
