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

It clicks all 11 points regardless of how many Earthquakes you're carrying; once you're out, the
remaining clicks land harmlessly.

## Edrags

A different routine: **12 Electro Dragons** placed individually around the diamond perimeter,
0.2s apart, rather than dragged. Heroes and spells follow as above.

## Builder Base

One strategy, whatever the army (*Your army (auto)* on the Run page;
`app/core/bb_strategy.py`). Before its deploy, each card on the bar is matched to its troop
by the bottom of its portrait: in the second stage, a survivor's health bar covers the top
of its portrait and its card has no swap button. A card still to deploy has a blue
background; it turns green as its troop lands.

The front is one of the two top edges of the map, picked at random (the bottom ones run
into the troop bar), clear of its corner and of the top HUD; the push enters near its
middle. Each troop has a role, after the play of Builder Base 2.0 guides (tank first,
Bombers behind it, flanks at once, troops spread against splash):

| Troop | Role | Lands | Ability (its card tapped again) |
|---|---|---|---|
| Battle Machine / Copter | tank, first | the entry point | at 20 s, then every 20 s (it charges) |
| Boxer Giant | tank | around the entry, 0.025 screen heights apart | Boxer Block once under 75 % health (2-15 s) |
| Power P.E.K.K.A | tank | around the entry, 0.025 screen heights apart | Overcharge once under 60 % health (4-16 s) |
| Drop Ship | tank (flies over the walls) | around the entry | Skeleton Bomb once under 85 % health (4-9 s) |
| Raged Barbarian | flank | a pair per three, up to two pairs, far out on both sides at once (the funnel); the rest behind the tanks | Rage (passive, first 22 s) |
| Sneaky Archer | flank | the same | Cloak (passive, first 11 s) |
| Beta Minion | flank | the same | Power Shot (passive) |
| Bomber | wall breaker, 1 s after | behind the tanks | Bouncing Bomb at 3 s, then each time it has recharged |
| Night Witch | support, 1.2 s after | behind the tanks | Bat Swarm once hit, under 90 % (4-10 s) |
| Cannon Cart | support | behind the tanks | none (stays a cart) |
| Baby Dragon | alone | one each side of the push, apart (Tantrum) | Fiery Sneeze once under 85 % health (3-9 s) |
| any other troop | last | behind the tanks | at 10 s |

The flanks clear the outer buildings, so the push goes into the core instead of walking
around it. A troop still on the bar after the deploy (its tap fell off the deploy zone)
lands once more, mid-front.

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
