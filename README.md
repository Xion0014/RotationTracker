# Rotation Tracker

A small Windows app for following long guild boss rotations turn by turn. Load a rotation, see exactly what each character does this turn, then press **Next turn**.

## Download

Grab **`RotationTracker.exe`** from the [latest release](https://github.com/Xion0014/RotationTracker/releases/latest) and run it. No install or Python needed.

## Updates

The app checks for a new version each time it starts. When one is out, it asks whether to update; say yes and it downloads the new version, replaces itself and restarts. You can also check any time with the **Updates** button.

If you say no, it won't ask again about that version, but the **Updates** button will still offer it.

### Publishing a new version (for maintainers)

1. Make your changes to `rotation_tracker.py`.
2. Raise `APP_VERSION` near the top of the file (for example `"1.0.0"` → `"1.1.0"`).
3. Commit and push to `main`. The commit message becomes the release notes users see.

GitHub Actions then builds the exe and publishes the release (it takes a few minutes; watch the **Actions** tab). Pushes that don't change `APP_VERSION` don't create a release.

## Building the .exe yourself

Only needed if you want to build locally instead of using the releases.

1. Install Python 3 from [python.org](https://www.python.org/downloads/).
   During setup, tick **"Add python.exe to PATH"**.
2. Download this repo (green **Code** button → **Download ZIP**, then unzip it), or clone it.
3. Double-click **`build_exe.bat`**.
4. After a minute or two, **`RotationTracker.exe`** appears in the same folder.

The exe runs on its own, so you can move it anywhere or share it. Python is only needed for building.

> Prefer not to build? Run it directly with `python rotation_tracker.py`.

## Using it

- **Open…** (or `Ctrl+O`) loads a `.json` or `.txt` rotation. You can also drag a rotation file onto the exe.
- **Next turn**: `Space`, `Enter`, `→` or `D`. **Previous turn**: `←` or `A`.
- The dropdown jumps to any turn; **Restart** goes back to the first.
- **Team** (or `T`): every unit's awareness, weapon, cards and notes, plus Wonder's personas and skills.
- **Info**: rotation details, notes and adjustments. It opens automatically when you load a new rotation.
- **Updates** checks for a newer version.
- **On top** keeps the window above the game. **A− / A+** change the text size.
- If you close the app mid-fight, it reopens on the same turn.

## Rotation formats

### JSON

The rotation-builder JSON format (with `setup`, `units`, `elucidator`, `personas` and `turns`) loads as is.

### Shorthand text

The quick style people post in chat works when saved as a `.txt` file:

```
Berry DoD ALL A6R6:

Credits: Misu
13-14 Billion
R6 Cursed Ties

Berry - Perseverance/Sorrow
Kotone - Nativity/Strife
Wonder Personas: Vasuki (Media, Sukukaja), Janosik (Rakunda), Dionysus (Universal Theoria, Cohesion)

T1 Twins Button + Guard, Wonder Guard, Kotone Guard, Berry S1 on Adds
T2 (6) HP Lock, Twins Guard, Berry HL, Wonder Guard, Kotone Guard, Berry S3
T7-8-9 Guard or Heal

Break

B1 (82) Miku S3, Twins S2, Dio Cohesion, Kotone GFBx2, Dio HL, S2, S2
```

- The first line is the title. `13-14 Billion` becomes the score, `R6 Cursed Ties` becomes Wonder's weapon.
- `Name - Card1/Card2` lines and `Wonder Personas:` fill the Team window.
- `T1` is a turn, `B1` is a break turn, `(6)` is the action count, and `T7-8-9` makes three turns.
- Commas separate actions; `+` splits a combo into steps.
- Persona names (or short forms like `Dio`) count as Wonder.
- A bare skill like `S2` goes to the last character who acted (skipping Wonder's HL).
- Miku's songs count as Miku: `Heaven 2` is her S2 with Heaven, `Fire S1` her S1 with Play-With-Fire.
- `F/I HL` and `P/N HL` count as Twins.
- `Action 19 - T4: ...` works as well as `T4 (19) ...`.
- A `-Break-` line before plain `T8`, `T9` turns marks them as Break 1, Break 2, and so on.
- `Weapon - Persona (skills), Persona (skills)` sets Wonder's weapon and personas, `Borrow Xion's Puppet` adds a borrowed unit, and `Twins > Wonder > Kotone > Puppet` records the turn order.

See the [`examples`](examples) folder for complete rotations in each format.

### Structured text

For full control, write one action per line:

```
title: My Rotation
unit: WONDER DGR R3 | weapon: Cursed Ties | Preferably R6
unit: MIKU A1 R0 | cards: Hope / Labor | elucidator
persona: Vasuki - Mediarama, Matarukaja (healing passives)
button: KOTONE Ast = Go for Broke

TURN 1
TWINS: Gd
BERRY: S1 Skulls
note: shown under the turn name
(alt) BERRY: HL
HP: ON
Any other line shows as a highlighted warning.
```

## Button names

Badges show friendlier names: `Gd` → **Guard**, Kotone's `Ast` → **Go for Broke**. Add more in the `BTN_NAMES` and `CHAR_BTN_NAMES` lists near the top of `rotation_tracker.py`.
