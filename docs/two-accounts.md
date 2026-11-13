# Farming two accounts

Two accounts, two ways: **one after the other** on one client (works today, hands-off),
or **both at once**, which needs a second Android client and is where the real limit sits.

## One after the other — multi-run

Already built. The **Players** page holds your Supercell account names; tick *Run* on the
ones you want and start a session. BasePilot farms the first account for the session
length, then opens *Settings → Change user*, OCRs the account list, picks the next name
and farms that one — for as many accounts as you have listed. Since the October 2026 UI,
Settings sit in the profile: the bot taps the profile badge (top left), then the profile
window's *Settings* tab, read by OCR (its tabs: My Profile, Social, Inbox, Settings), and
looks for the Supercell ID switch button there (`changeuser.png`). This path comes from
Supercell's notes on the new UI and has not run on a live switch yet: when a step does
not show, the switch fails for that account (the log says which step), the windows are
closed, and a frame of the screen goes to `%LOCALAPPDATA%\BasePilot\debug`.

Each account starts its session with a clan visit due rather than inheriting the previous
one's clocks, because they sit in different clans.

This is the option to take unless you have a reason to need both accounts running at the
same moment. It costs no extra CPU, needs no second client, and is unattended.

Its limits: only one account is farming at any moment, and the account switch itself is
OCR on the username list, so an account whose name reads badly can fail the switch (the
log says which name it could not find). Names numbered alike (`Farm_1` / `Farm_2`, `Farm 1` /
`Farm 2`) are told apart by their number: a name whose number does not read fails the switch
rather than picking the other account. What cannot be told apart is a name that is a word, or
part of a word, of another one (`Farm` / `Farm 2`, `Bob` / `King Bob`, `Bob` / `KingBob`), names
with the same letters and digits (`Farm_1` / `Farm 1`), or names a letter apart (`KingBob` /
`KingRob`): give each account a name that no other one contains and that differs from the
others by more than a letter.

## Both at once — profiles

Two BasePilot windows can run side by side. Each needs its own **profile**, or they
overwrite each other's settings, fight over one game window, and write into one log:

```bash
python main.py --profile main
```

```bash
python main.py --profile second
```

Or with the released exe:

```bash
BasePilot.exe --profile second
```

A profile gets its own directory under `%LOCALAPPDATA%\BasePilot\profiles\<name>\`,
holding everything a run reads or writes:

| | |
| --- | --- |
| `settings.json` | every knob on the Settings page |
| `window.json` | which game window this session drives |
| `player_list.json` | the Players page |
| `basepilot.log` | its own log, so two runs don't interleave |
| `debug/` | its own debug frames |
| `scouting/` | the Builder Base bases it attacked, as scouted before each stage's deploy (the newest 400) |
| `templates/` | its own captured art |

A brand-new profile starts as a copy of your main settings, so you are not setting every
option again — **except the window pin**, which it never inherits. That one is the whole
point: each session has to be pointed at its own client, so the second window opens
unpinned and asks you to choose (*Settings → Game window*). Templates you captured on the
main profile are still found, so there is nothing to re-capture. The Run page's choices and its
scheduled start times are kept per profile too: a new profile's Run page starts as a copy of the
main one's, scheduled times included (change them if the two accounts should not start
together), then keeps its own; the loot minimums follow the settings it copied.

The window title carries the profile (`BasePilot — second`) so you can tell the two
windows apart on the taskbar. No profile means the main directory, exactly as before, so
nothing changes for a single-account setup.

## The part that isn't solved: a second client

Profiles are the easy half. Running two accounts at once also needs **two Android clients
on screen at the same time**, and that is where it stops today:

- **Google Play Games on PC runs one instance**, signed into one Google account. There is
  no second window to give the second profile.
- **BasePilot captures and clicks a Google Play Games surface.** It looks for a window
  with a `CROSVM*` render surface, captures it with `PrintWindow`, and injects clicks
  straight into it with `SendMessage` — which is why it works on a window that is behind
  others or minimized. Another emulator (LDPlayer, BlueStacks, MuMu — all of which do run
  several instances) draws into a different surface class, so BasePilot will not even list
  it in *Settings → Game window*, and its input path would have to be checked separately:
  several emulators ignore injected messages and need real input or ADB.

So the honest position: the bot side is ready for two sessions, the client side is not.
Supporting a second emulator means teaching the window service to accept a non-CROSVM
surface and verifying capture and click injection against that emulator — worth doing, but
it is a porting job, not a setting.

Two smaller things to know if you get there:

- **Give the two clients different window titles.** The window pin records a title and a
  window class, so two identically-titled emulator instances cannot be told apart and both
  profiles would drive the first one. BasePilot logs a warning when a pin matches more than
  one window rather than picking silently.
- **Two clients cost twice the machine.** Each one is a full Android VM; the OCR and
  template matching in each BasePilot add to that. On a machine that struggles, both
  sessions get slower and clicks start landing on animations.

## Command line

```
--profile NAME     run under a named profile (its own settings, window pin, log)
--autostart        start a run on launch
--minutes N        session length; 0 = endless
--walls            wall upgrades
--upgrades MODE    off | dry | maxer | rusher
--donate           clan donations
--request          reinforcement requests
```

They combine, so a second account can be launched straight into a run:

```
BasePilot.exe --profile second --autostart --minutes 0 --walls --donate
```
