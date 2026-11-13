'''Upgrade policy for the auto-maxer: which upgrade to start, given the Build panel's
cards, OCR'd resources, and free builders.

Maxer and rusher are one engine with different rules — not two bots:
- maxer: never touches the hall (Town Hall, Builder Hall); spends on everything else,
  priciest first by default (``order``).
- rusher: takes the hall the moment it is affordable; otherwise the same order.

Shared invariants: keep ``reserve_builders`` free (walls are the overflow sink for
the reserved builder — the existing wall flow handles those), and keep a gold buffer
so the Find a Match entry fee is never spent away.
'''
from dataclasses import dataclass

from app.core.upgrade_menu import (
    RESOURCE_DARK,
    RESOURCE_ELIXIR,
    RESOURCE_GOLD,
    SECTION_IN_PROGRESS,
    is_town_hall_row,
    is_wall_row,
)
from app.utils.logger import setup_logger
from app.utils.profile_settings_store import UPGRADE_ORDER_CHEAPEST, UPGRADE_ORDER_PRICIEST

logger = setup_logger('UpgradePolicy')

MODE_MAXER = 'maxer'
MODE_RUSHER = 'rusher'
MODE_OFF = 'off'
MODE_DRY = 'dry'  # open the Build panel and log the pick, start nothing
AUTO_UPGRADE_MODES = (MODE_OFF, MODE_DRY, MODE_MAXER, MODE_RUSHER)
LIVE_UPGRADE_MODES = (MODE_MAXER, MODE_RUSHER)

ORDER_PRICIEST = UPGRADE_ORDER_PRICIEST  # the strings settings.json stores
ORDER_CHEAPEST = UPGRADE_ORDER_CHEAPEST


@dataclass(frozen = True)
class UpgradePolicy:
    mode: str = MODE_MAXER
    reserve_builders: int = 1
    gold_attack_buffer: int = 50000  # Find a Match entry fee is ~1300; keep a margin
    # 'priciest' (default): a bot-farmed account is builder-limited, not loot-limited —
    # each builder should soak the biggest job available (also drains full storages
    # hardest, which is what unblocks farming). 'cheapest' spreads builders across
    # many small jobs instead.
    order: str = ORDER_PRICIEST


def _available_for(resource, resources, policy):
    (gold, elixir, dark) = resources
    if resource == RESOURCE_GOLD:
        return max(0, gold - policy.gold_attack_buffer)
    if resource == RESOURCE_ELIXIR:
        return elixir
    if resource == RESOURCE_DARK:
        return dark
    return 0


def can_pay(row, resources, policy):
    '''True when the row has a parsed cost/resource and the OCR'd resources cover it
    (after the gold attack buffer).'''
    if row.cost is None or row.resource is None:
        return False
    return row.cost <= _available_for(row.resource, resources, policy)


def choose_upgrade(rows, resources, free_builders, policy):
    '''Pick the upgrade to start now, or ``None``.

    ``rows``: the :class:`UpgradeRow` cards read from the Build panel.
    ``resources``: OCR'd ``(gold, elixir, dark)`` HUD triplet.
    ``free_builders``: from the builder chip; ``None`` means unknown → do nothing.
    '''
    if free_builders is None or free_builders <= policy.reserve_builders:
        return None
    # A running upgrade never carries a parsed cost (it shows the time left), so the
    # cost and affordability gates below already exclude it; the section check only
    # rejects one explicitly.
    candidates = [
        r for r in rows
        if r.section != SECTION_IN_PROGRESS
        and r.affordable
        and not is_wall_row(r)  # walls belong to the wall flow (one at a time, the overflow sink)
        and can_pay(r, resources, policy)
    ]
    if not candidates:
        return None
    th_rows = [r for r in candidates if is_town_hall_row(r)]
    if policy.mode == MODE_RUSHER and th_rows:
        pick = min(th_rows, key = (lambda r: r.cost))
        logger.info('Policy(rusher): Town Hall affordable — picking it (%s, cost %s)', pick.label, pick.cost)
        return pick
    if policy.mode != MODE_RUSHER:
        candidates = [r for r in candidates if not is_town_hall_row(r)]
    if not candidates:
        return None
    # Raw cost decides, whatever the resource: dark elixir rows no longer get first claim
    # (the user's choice), so a hero row is picked only when it is the priciest left.
    chooser = min if policy.order == ORDER_CHEAPEST else max
    pick = chooser(candidates, key = (lambda r: r.cost))
    logger.info('Policy(%s/%s): picking %s (cost %s %s)', policy.mode, policy.order, pick.label, pick.cost, pick.resource)
    return pick
