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
`app/core/bb_strategy.py`). Before the first deploy, each card on the bar is matched to its
troop (the green swap buttons under the cards are only there until then). Each troop has a
profile:

| Troop | Order | Lands | Ability (its card tapped again) |
|---|---|---|---|
| Battle Machine / Copter | first, the tank | the entry point | from 8 s, at 18 s at the latest (it charges) |
| Boxer Giant | right behind | the entry point | Boxer Block once under 75 % health (2-15 s) |
| Power P.E.K.K.A | right behind | the entry point | Overcharge once under 60 % health (4-16 s) |
| Raged Barbarian | behind the tanks | the entry point | Rage (passive, first 22 s) |
| Bomber | 1.5 s later, behind the tanks | the entry point | Bouncing Bomb at 3 s, then every 12 s |
| Cannon Cart | behind the tanks | the entry point | none (stays a cart) |
| Sneaky Archer | support | the entry point | Cloak (passive, first 11 s) |
| Drop Ship | support | the entry point | Skeleton Bomb once under 85 % health (4-9 s) |
| Beta Minion | support | the entry point | Power Shot (passive) |
| Night Witch | 2 s later, behind the tanks | the entry point | Bat Swarm once hit, under 90 % (4-10 s) |
| Baby Dragon | support | apart, a slot each along the front (Tantrum) | Fiery Sneeze once under 85 % health (3-9 s) |
| any other troop | last | a slot of its own along the front | at 10 s |

The entry point is one of three spots along the top edges of the diamond (the bottom edges
run into the troop bar), with a little jitter per card, so the groups push together.

Abilities go at the right moment, not all at once. During the fight each card shows its
troop's health bar; an ability fires once its troop is engaged (health under the share
above), never before the first time of its range and at the second at the latest. One tap
per poll, the most hurt troop first, never two of one troop kind within 1.2 s, and none
for a dead troop (its card turns grey). The timings are first guesses from Builder Base 2.0
guides, to tune on live battles.

A battle is never ended early: no End Battle, no Surrender. When troops come back to the bar
for the next stage (a reinforcement's swap button shows), the troops still in colour on the
bar (survivors carry no swap button; dead troops' cards turn grey) are deployed the same way,
and the bot leaves only from the results screen (Return Home).
