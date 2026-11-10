'''UI constants ported from the legacy theme module.'''
ATTACK_STRATEGIES: dict[str, int] = {
    'Sneaky Goblins': 1,
    'Super Minions': 2,
    'Valkyries': 3,
    'Edrags': 4 }
# The Builder Base fight deploys every troop card on the bar, whatever the army: both
# labels run the same routine (Bot._deploy_bb_army).
BUILDER_BASE_ATTACK_STRATEGIES: dict[str, int] = {
    'Baby Dragon': 5,
    'Night Witches': 6 }
BUILDER_BASE_ATTACK_STRATEGIES_UNDER_DEV = ()

