"""Which upgrade the policy starts, on the cards of a live Build panel (GPG 1227x767)."""
import unittest

from app.core.upgrade_menu import RESOURCE_DARK, RESOURCE_ELIXIR, RESOURCE_GOLD, UpgradeRow
from app.core.upgrade_policy import (ORDER_CHEAPEST, ORDER_PRICIEST, MODE_MAXER, MODE_RUSHER, UpgradePolicy,
                                     can_pay, choose_upgrade)


def card(label, cost, resource):
    return UpgradeRow(label=label, section='', cost=cost, resource=resource, affordable=True, center=(900, 100))


HUD = (12122547, 10365793, 168213)  # gold, elixir, dark elixir on that frame
PANEL = [card('Royal Champion', 4000, RESOURCE_DARK), card('Blacksmith', 2480000, RESOURCE_ELIXIR),
         card('Elixir Storage', 1120000, RESOURCE_GOLD), card('Town Hall', 9000000, RESOURCE_GOLD)]


def pick(order=ORDER_PRICIEST, mode=MODE_MAXER, rows=PANEL, hud=HUD):
    choice = choose_upgrade(rows, hud, 1, UpgradePolicy(mode=mode, reserve_builders=0, order=order))
    return choice.label if choice else None


class PolicyTests(unittest.TestCase):
    def test_priciest_whatever_the_resource_and_never_the_town_hall(self):
        self.assertEqual(pick(), 'Blacksmith')  # not the hall at 9M, not the hero for dark elixir

    def test_cheapest_first(self):
        self.assertEqual(pick(ORDER_CHEAPEST), 'Royal Champion')

    def test_rusher_takes_the_town_hall(self):
        self.assertEqual(pick(mode=MODE_RUSHER), 'Town Hall')

    def test_only_what_the_storages_cover(self):
        # 2 480 000 elixir with 2 000 000 in the bank: the next priciest is started
        self.assertEqual(pick(hud=(12122547, 2000000, 168213)), 'Elixir Storage')
        # gold keeps the Find a Match buffer: 1 120 000 gold is not payable with 1 150 000
        self.assertFalse(can_pay(PANEL[2], (1150000, 0, 0), UpgradePolicy()))

    def test_no_free_builder_means_nothing(self):
        self.assertIsNone(choose_upgrade(PANEL, HUD, 0, UpgradePolicy(reserve_builders=0)))
        self.assertIsNone(choose_upgrade(PANEL, HUD, None, UpgradePolicy(reserve_builders=0)))


if __name__ == '__main__':
    unittest.main()
