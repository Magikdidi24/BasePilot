# Deploy mechanics

What BasePilot actually does during a raid, for anyone tuning strategies or reading the code.

For the recommended army and the setup that makes it work, see
[Army setup](../README.md#army-setup) in the README.

## Valkyries, Sneaky Goblins, Super Minions

These three share one routine. Per raid, in order:

1. **Select the troop** in the deploy bar. Abort if its icon isn't there.
2. **Drag-deploy around the perimeter.** One continuous press-and-drag from a randomly chosen
   corner, through four corner segments, then release — this empties the selected slot in a line
   along the base edges. Start corner and direction are randomized every raid (at 16:9 it starts
   left or right; at 16:10 it may also start from the top), and each segment's duration is
   jittered ±10%.
3. **Super Dragon**, if it's in the bar.
4. **Siege machine** — Log Launcher first, else Siege Barracks.
5. **Heroes**, in random order each raid: Queen, Warden, Royal Champion, King, Prince, Dragon
   Duke. Whichever are present get dropped, then clicked a second time to fire their abilities.
6. **Earthquake spells.**

Because step 2 is a drag rather than individual taps, exact troop count matters less than
filling the slot — the drag spreads whatever you're carrying along the edges.

## Earthquake placement

BasePilot clicks **11 earthquake points** per raid, in one of two patterns
(*Settings → Earthquake*):

- **Curve placement** (default) — samples an arc through the left/top/right anchor points with
  ±100px of jitter per point.
- **Random placement** — random points inside the region between that arc and a horizontal line
  40% up the frame. Falls back to curve placement if that region comes out degenerate.
- **Learn (the one that loots more)** — each raid plays one of the two, drawn by Thompson
  sampling (`QuakeLearner` in `app/core/bb_learning.py`) on the share of the base's loot the
  raids took with it so far, per army: the placement that loots more gets played more, the
  other now and then. Both start believed at 50 %, so the first raids try both. The log
  gives each draw and the share each placement is expected to take.

The share is the gold and elixir won (the results screen) over what the base held: the won
plus what it still held as the battle ended (its available loot, read every second during
the battle; the first read counts once the next one agrees with it). For a raid that ends
at once (Sneaky Goblins), the base's loot as the loot filter read it before the battle,
when it is on. On a live raid: 631,119 won, 1,232,794 left, 34 % (35 % against the read
before the battle). Every raid's placement is written down, whichever is picked, so
*Learn* starts from the raids already played. A raid with no Earthquake in the army does
not count.

It clicks all 11 points regardless of how many Earthquakes you're carrying; once you're out, the
remaining clicks land harmlessly.

## Edrags

A different routine: **12 Electro Dragons** placed individually around the diamond perimeter,
0.2s apart, rather than dragged. Heroes and spells follow as above.

## Ending a Home Village raid

The raid goes on while it takes loot. Every second the bot reads the base's available loot
(top left, the panel the loot filter reads before the attack). Once it has not dropped for
12 s and a star is won (End Battle shows), End Battle is tapped; ending at the first star, as
the bot used to, left 1.2M of a base's 2.1M on a live raid. With no star (Surrender shows)
and nothing coming for a minute, the battle is surrendered. A read that does not fit (above
the last one, or under half of it: a digit dropped or misread) is not a drop. A battle that
ends by itself (its timer, or 100 %) goes to its results screen and nothing is tapped. Past
200 s, whichever way out shows is tapped. An event's reward overlay is let expire, then the
battle goes on.

Sneaky Goblins (method 1) still leave as soon as they can: they take the outer storages in
seconds.

Before Return Home, the results screen is read once its count is over (stars; total damage;
the gold, elixir and dark elixir won) and the raid goes to `battles.jsonl` in
`%LOCALAPPDATA%\BasePilot` with its army, its Earthquake placement and the share of the
base's loot it took. A raid whose results screen does not read is written from the HUD
instead (its loot only), as before.

## Builder Base

One strategy, whatever the army (*Your army (auto)* on the Run page;
`app/core/bb_strategy.py`). Before its deploy, each card on the bar is matched to its troop
by the bottom of its portrait: in the second stage, a survivor's health bar covers the top
of its portrait and its card has no swap button. A card still to deploy has a blue
background; it turns green as its troop lands.

Before each stage's deploy the bot scouts the base (`app/core/bb_scout.py`): the map and
the base on it sit somewhere else on the screen in each battle and stage. The floor is
the map's smooth tiled ground (not the forest, the cliffs or the water), the base is what
stands lit on it (buildings, walls), closed over the gaps between them like the game's
no-deploy zone. Troops land in a band just off the base, out of the HUD. Each spot of
that band is scored by the buildings in reach (not the walls) and its distance to the
base's centre; the best spot of each side of the base is an entry, and the attack takes
one of the three best sides at random, so it does not always come from the same place.
If the first troop does not land (a no-deploy spot), it goes again from the next side;
with no base found, from one top edge of the map.

The push enters at the entry; the front runs along the base's edge there. Each troop has
a role, after the play of Builder Base 2.0 guides (tank first, Bombers behind it, flanks
at once, troops spread against splash):

| Troop | Role | Lands | Ability (its card tapped again) |
|---|---|---|---|
| Battle Machine / Copter | tank, first | the entry point | at 20 s, then every 20 s (it charges) |
| Boxer Giant | tank | around the entry, 0.025 screen heights apart | Boxer Block once under 75 % health (2-15 s) |
| Power P.E.K.K.A | tank | around the entry, 0.025 screen heights apart | Overcharge, a one-time blast around her (she lives on), once the defences have her under 70 % health (6-30 s) |
| Drop Ship | tank (flies over the walls) | around the entry | Skeleton Bomb once under 85 % health (4-9 s) |
| Raged Barbarian | flank | a pair per three, up to two pairs, far out on both sides at once (the funnel); the rest behind the tanks | Rage (passive, first 22 s) |
| Sneaky Archer | flank | the same | Cloak (passive, first 11 s) |
| Beta Minion | flank | the same | Power Shot (passive) |
| Bomber | wall breaker, 1 s after | behind the tanks | Bouncing Bomb as it lands (its card tapped again: the first wall), then each time it has recharged; a lost tap goes again at once, first of all under 50 % health |
| Night Witch | support, 1.2 s after | behind the tanks | Bat Swarm once hit, under 90 % (4-10 s) |
| Cannon Cart | support | behind the tanks | none (stays a cart) |
| Baby Dragon | alone | one each side of the push, apart (Tantrum) | Fiery Sneeze once under 85 % health (3-9 s) |
| any other troop | last | behind the tanks | at 10 s |

The flanks land along the base's sides and clear the outer buildings, so the push goes
into the core instead of walking around it. A troop still on the bar after the deploy
(its tap fell off the deploy zone) lands once more at the entry.

An army with Power P.E.K.K.As is played as a P.E.K.K.A push: the Bombers land first and
open the walls with their Bouncing Bomb (fired as they land), the P.E.K.K.As go in right
behind them, the machine follows, then the rest. The attack comes from the side of the
Multi Mortar, whose splash is what stops them: the scouting looks for its four tube
openings (dark, round, a lighter rim each, close together in a fairly regular
quadrilateral), which every level has, from the wooden one to the gold one. With no
Multi Mortar found, the side is picked as above.

The bot learns which way of picking the side wins (`app/core/bb_learning.py`). At the end
of each battle it reads the results screen once its animation is over (stars, gold or
silver; total damage; gold and trophies won) and writes the battle to `battles.jsonl` in
`%LOCALAPPDATA%\BasePilot`. Four plans: **best** (the blend above), **core** (the side
nearest the base's centre), **reach** (the most buildings in reach), **mortar** (the Multi
Mortar's side, for a P.E.K.K.A push). Each battle's plan is drawn by Thompson sampling on
the damage the plans did so far, per army: plans that win are played more, the others now
and then. The P.E.K.K.A push starts with the Multi Mortar first (the player's play) leading,
and yields only to a plan that does clearly better. The log gives each draw and the
damage each plan is expected to do.

Back home after a battle, the elixir cart is collected when full: looked for on the view
as it is, else after a pan once the view has stopped moving. Nothing else is tapped there
(the home village's "empty" point lands on Builder Base walls and obstacles).

Abilities go at the right moment, not all at once. During the fight each card shows its
troop's health bar; an ability fires once its troop is engaged (health under the share
above), never before the first time of its range and at the second at the latest. One tap
per poll, the most hurt troop first, never two of one troop kind within 1.2 s, and none
for a dead troop (its card turns grey). A troop card's background tells its ability's state:
green ready, red recharging, grey used (blue: not deployed yet); it is only tapped while green,
and tapped again if it stays green (a lost tap). Only the machine charges its ability: tapped
too early, the game answers "You need to wait...", so it goes on time. The timings are first
guesses from Builder Base 2.0 guides, to tune on live battles (each ability is logged with
the troop's health).

A battle is never ended early: no End Battle, no Surrender. When troops come back to the bar
for the next stage (a reinforcement's swap button shows), the survivors of the last stage
and the reinforcements are deployed the same way (dead troops' cards turn grey and stay
on the bar), and the bot leaves only from the results screen (Return Home). The speed
button a stage shows for its last minute is tapped while it reads 1x: the minute plays at
4x.
