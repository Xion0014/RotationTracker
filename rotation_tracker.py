#!/usr/bin/env python3
"""
Rotation Tracker - step through guild boss rotations turn by turn.

Open a rotation (.json or .txt), see every action for the current turn,
and press Next (or Space / Right arrow) to move on.

You can also drag a rotation file onto the .exe to open it directly.
"""
import os
import subprocess
import sys


# ----------------------------------------------------------------------------
# Clean start for the packaged exe. This runs before anything else.
#
# A PyInstaller exe unpacks itself into a temporary _MEIxxxx folder. If one copy
# of the exe starts another copy at the same path (which the updater does), the
# new copy inherits the old one's settings and reuses its temp folder, which
# Windows deletes as soon as the old copy closes. Tcl/Tk then fails with
# "couldn't read file .../_tcl_data/auto.tcl".
# ----------------------------------------------------------------------------
def clean_child_env():
    """Environment for starting a fresh, independent copy of the app."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("_PYI_") and k not in ("_MEIPASS2", "TCL_LIBRARY", "TK_LIBRARY")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def _restart_clean_if_needed():
    if not getattr(sys, "frozen", False) or os.environ.get("RT_CLEAN_START"):
        return
    home = getattr(sys, "_MEIPASS", "")
    marker = os.path.join(home, ".rt_owner")
    reused = False
    try:
        # Our own fresh temp folder never has another process's marker in it
        with open(marker, encoding="ascii") as f:
            reused = f.read().strip() != str(os.getpid())
    except OSError:
        pass
    for var, probe in (("TCL_LIBRARY", "init.tcl"), ("TK_LIBRARY", "tk.tcl")):
        d = os.environ.get(var)
        if d and not os.path.isfile(os.path.join(d, probe)):
            reused = True        # the temp folder we were handed is already being deleted
    if reused:
        env = clean_child_env()
        env["RT_CLEAN_START"] = "1"
        try:
            subprocess.Popen([sys.executable] + sys.argv[1:], env=env,
                             cwd=os.path.dirname(sys.executable))
            os._exit(0)
        except OSError:
            pass
    try:
        with open(marker, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


_restart_clean_if_needed()

import json  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_NAME = "Rotation Tracker"

# Bump this and push to main: GitHub Actions builds the exe and publishes a release,
# and everyone's app offers the update.
APP_VERSION = "1.1.1"
GITHUB_REPO = "Xion0014/RotationTracker"
EXE_ASSET = "RotationTracker.exe"
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".rotation_tracker.json")

# ----------------------------------------------------------------------------
# Colors
# ----------------------------------------------------------------------------
BG = "#16181d"
PANEL = "#1f2229"
CARD = "#272b34"
CARD_ALT = "#2a2533"
FG = "#e8eaed"
MUTED = "#9aa0aa"
ACCENT = "#e5484d"
NOTE_FG = "#f5c86b"

BTN_COLORS = {
    "S1": "#3b82f6",
    "S2": "#22c55e",
    "S3": "#a855f7",
    "HL": "#f59e0b",
    "GD": "#6b7280",
    "GUARD": "#6b7280",
    "AST": "#14b8a6",
    "ATK": "#ef4444",
    "ATTACK": "#ef4444",
    "ITEM": "#ec4899",
    "HP": "#e5484d",
    "SKIP": "#4b5563",
}
DEFAULT_BTN_COLOR = "#64748b"

CHAR_PALETTE = [
    "#7dd3fc", "#fca5a5", "#86efac", "#fcd34d",
    "#c4b5fd", "#f9a8d4", "#5eead4", "#fdba74",
]

KNOWN_BTNS = set(BTN_COLORS.keys())

# Character-specific button names: (CHARACTER, BUTTON) -> text shown on the badge.
# Rotation files can add their own with "buttonNames" (JSON) or "button:" lines (text).
CHAR_BTN_NAMES = {
    ("KOTONE", "AST"): "Go for Broke",
}

# Button names used for every character (unless a character-specific name above applies).
BTN_NAMES = {
    "GD": "Guard",
}


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------
def clean(s):
    """Strip markdown bold markers and whitespace."""
    return re.sub(r"\*\*|__", "", str(s if s is not None else "")).strip()


def load_rotation(path):
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read()
    stripped = raw.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return parse_json(json.loads(raw))
        except json.JSONDecodeError as e:
            if path.lower().endswith(".json"):
                raise ValueError(f"This JSON file has a formatting error:\n{e}")
    return parse_text(raw)


def _unit_line(u, prefix=""):
    if not isinstance(u, dict) or not u.get("name"):
        return None
    head = " ".join(x for x in [clean(u.get("name")), clean(u.get("awareness")),
                                clean(u.get("rev"))] if x)
    extras = []
    if u.get("gear"):
        extras.append(clean(u["gear"]))
    cards = " / ".join(x for x in [clean(u.get("space")), clean(u.get("sunsky"))] if x)
    if cards:
        extras.append(cards)
    if u.get("role"):
        extras.append(clean(u["role"]))
    if u.get("companion"):
        extras.append("Companion: " + clean(u["companion"]))
    line = prefix + head
    if extras:
        line += "  |  " + "  |  ".join(extras)
    if u.get("note"):
        line += "\n      - " + clean(u["note"])
    return line


def _unit(u, tag=""):
    """Structured unit info for the Team window."""
    if not isinstance(u, dict) or not clean(u.get("name")):
        return None
    return {
        "name": clean(u.get("name")),
        "tag": tag,
        "awareness": clean(u.get("awareness")),
        "rev": clean(u.get("rev")),
        "weapon": clean(u.get("gear") or u.get("weapon")),
        "cards": [c for c in (clean(u.get("space")), clean(u.get("sunsky"))) if c],
        "role": clean(u.get("role")),
        "companion": clean(u.get("companion")),
        "note": clean(u.get("note")),
    }


def _persona(name, skills, note=""):
    return {"name": clean(name), "skills": [clean(s) for s in skills if clean(s)], "note": clean(note)}


def _btn_names(raw):
    """Turn {"KOTONE Ast": "Go for Broke"} into {("KOTONE","AST"): "Go for Broke"}."""
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            parts = str(k).split()
            if len(parts) >= 2 and clean(v):
                out[(" ".join(parts[:-1]).upper(), parts[-1].upper())] = clean(v)
    return out


def norm_action(a):
    """Turn one raw action into {char, btn, detail, alt, kind}. Returns None if empty."""
    if isinstance(a, str):
        a = a.strip()
        return {"char": "", "btn": "", "detail": a, "alt": False, "kind": "note"} if a else None
    if not isinstance(a, dict):
        return None

    char = clean(a.get("char"))
    btn = clean(a.get("btn"))
    persona = clean(a.get("persona"))
    skill = clean(a.get("skill"))
    song = clean(a.get("song"))
    text = clean(a.get("text"))
    alt = bool(a.get("alt"))

    # HP display toggle row
    hp = clean(a.get("hp"))
    if hp:
        return {"char": "", "btn": "HP", "detail": f"HP LOCK {hp.upper()}",
                "alt": alt, "kind": "toggle"}

    if a.get("hl") and not btn:
        btn = "HL"

    bits = []
    if persona and skill:
        bits.append(f"{persona} \u2192 {skill}")
    elif persona:
        bits.append(persona)
    elif skill:
        bits.append(skill)
    if song:
        bits.append("\u266a " + song)
    if text and text.lower() not in " ".join(bits).lower():
        bits.append(text)
    detail = "   ".join(bits)

    if not char and not btn:
        if not detail:
            return None
        return {"char": "", "btn": "", "detail": detail, "alt": alt, "kind": "note"}

    return {"char": char, "btn": btn, "detail": detail, "alt": alt, "kind": "action"}


def parse_json(data):
    if isinstance(data, list):
        data = {"turns": data}
    setup = data.get("setup") or {}

    title = clean(setup.get("rotationName") or data.get("name") or data.get("title") or "Rotation")
    meta = []
    for key, label in [("boss", "Boss"), ("type", "Mode"), ("patch", "Patch"),
                       ("score", "Score"), ("breaks", "Breaks"), ("side", "Side"),
                       ("credits", "By")]:
        v = clean(setup.get(key))
        if v:
            meta.append(f"{label}: {v}")

    notes = clean(setup.get("notes") or data.get("notes"))
    if data.get("teamNotes"):
        notes = (notes + "\n\n" + clean(data["teamNotes"])).strip()

    units = [x for x in (_unit(u) for u in data.get("units") or []) if x]
    for extra, tag in ((data.get("elucidator"), "Elucidator"), (data.get("backup"), "Backup")):
        x = _unit(extra, tag)
        if x:
            units.append(x)
    personas = [_persona(p.get("name"), p.get("skills") or [], p.get("note"))
                for p in data.get("personas") or [] if isinstance(p, dict) and p.get("name")]

    team = []
    for u in data.get("units") or []:
        line = _unit_line(u)
        if line:
            team.append(line)
    line = _unit_line(data.get("elucidator"), prefix="(Elucidator) ")
    if line:
        team.append(line)
    line = _unit_line(data.get("backup"), prefix="(Backup) ")
    if line:
        team.append(line)
    for p in data.get("personas") or []:
        if isinstance(p, dict) and p.get("name"):
            skills = ", ".join(clean(s) for s in p.get("skills", []) if clean(s))
            pl = f"Persona {clean(p['name'])}" + (f": {skills}" if skills else "")
            if p.get("note"):
                pl += f"  ({clean(p['note'])})"
            team.append(pl)

    turns = []
    for i, t in enumerate(data.get("turns") or []):
        if not isinstance(t, dict):
            continue
        actions = [x for x in (norm_action(a) for a in t.get("actions") or []) if x]
        turns.append({
            "name": clean(t.get("name")) or f"Turn {i + 1}",
            "note": clean(t.get("note")),
            "actions": actions,
        })

    if not turns:
        raise ValueError("No turns were found in this file.")
    return {"title": title, "meta": meta, "notes": notes, "team": team, "turns": turns,
            "units": units, "personas": personas,
            "btn_names": _btn_names(data.get("buttonNames"))}


HEADER_RE = re.compile(
    r"^\s*(?:\[(?P<b>[^\]]+)\]"
    r"|#+\s*(?P<h>.+?)"
    r"|(?P<t>(?:turn|break|phase|wave|round)\s*[\w.\-]*)\s*:?)\s*$",
    re.I,
)
META_RE = re.compile(r"^\s*(title|name|boss|mode|type|patch|score|credits?|by|team|unit|persona|button|notes?)"
                     r"\s*[:=]\s*(.*)$", re.I)


def _text_unit(val):
    """unit: WONDER DGR R3 | weapon: Cursed Ties | cards: A / B | role: X | note: Y | elucidator"""
    segs = [s.strip() for s in val.split("|") if s.strip()]
    if not segs:
        return None
    head = segs[0].split()
    u = {"name": head[0], "tag": "", "awareness": "", "rev": "", "weapon": "", "cards": [],
         "role": "", "companion": "", "note": ""}
    for tok in head[1:]:
        if re.fullmatch(r"R\d+", tok, re.I):
            u["rev"] = tok.upper()
        else:
            u["awareness"] = (u["awareness"] + " " + tok).strip()
    for seg in segs[1:]:
        if ":" in seg:
            k, v = [x.strip() for x in seg.split(":", 1)]
            k = k.lower()
            if k in ("weapon", "gear", "knife"):
                u["weapon"] = v
            elif k in ("cards", "card", "revelation", "revelations"):
                u["cards"] = [c.strip() for c in re.split(r"[/,]", v) if c.strip()]
            elif k in ("role", "companion", "note"):
                u[k] = v
        elif seg.lower() in ("elucidator", "backup"):
            u["tag"] = seg.capitalize()
        else:
            u["note"] = (u["note"] + " " + seg).strip()
    return u


def _text_persona(val):
    """persona: Vasuki - Mediarama, Matarukaja (healing passives)"""
    note = ""
    m = re.search(r"\(([^)]*)\)\s*$", val)
    if m:
        note, val = m.group(1), val[:m.start()]
    val = val.strip()
    name, _, rest = val.partition(" - ") if " - " in val else val.partition(":")
    return _persona(name, re.split(r"\s*,\s*", rest) if rest.strip() else [], note)


# ---- Shorthand format:  "T5 (21) Miku S1, Guard, Vasuki Heal, Berry S3"  /  "B2 ..." ----
COMPACT_RE = re.compile(
    r"^\s*(?:action\s*(?P<act2>\d+)\s*[-:–]?\s*)?"               # optional "Action 19 - " prefix
    r"(?P<kind>turn|t|break|b)\s*(?P<nums>\d+(?:\s*[-–]\s*\d+)*)\s*"
    r"(?:\((?P<act>\d+)\))?\s*[:.\-]?\s*(?P<rest>.*?)\s*$",
    re.I,
)
# "Berry - Perseverance/Sorrow"  or  "Twins - Trust + Power - F/I + P/N"
SHORT_UNIT_RE = re.compile(r"^\s*([A-Za-z][\w.']*(?:\s[A-Za-z][\w.']*){0,2})\s+-\s+(\S.*\S)\s*$")
SHORT_PERSONAS_RE = re.compile(r"^\s*(?:wonder(?:'s)?\s+personas?|personas)\s*:\s*(.+)$", re.I)
BORROW_RE = re.compile(r"^\s*borrow(?:ed)?\s+(?:(\S+?)'s\s+)?([A-Za-z][\w.]*)\s*(.*)$", re.I)
DIVIDER_RE = re.compile(r"^\s*[-=*~_#\s]*\s*(break|breaks|phase\s*2|overdrive)\s*[-=*~_#\s]*$", re.I)
BTN_TOKEN_RE = re.compile(r"^(S[123]|HL|GUARD|GD|AST|GFB|BUTTON)(?:X(\d+))?$")
BTN_CANON = {"GUARD": "Gd", "GD": "Gd", "AST": "Ast", "GFB": "Ast", "BUTTON": "Button"}
SKILL_BTNS = {"S1", "S2", "S3", "HL", "Ast", "Button"}
EVERYONE = {"EVERYONE", "EVERYBODY", "ALL", "TEAM", "OTHERS"}

# Miku's songs: "Heaven 2" / "Miku Fire S1" -> MIKU, S2/S1, ♪ song
MIKU_SONGS = {"HEAVEN": "Heaven", "SPRING": "Spring Storm", "FIRE": "Play-With-Fire",
              "PLAYWITHFIRE": "Play-With-Fire"}
# Twins' highlight elements: "F/I HL" / "P/N HL" -> TWINS
TWINS_ELEMENTS = {"F/I", "P/N", "FIRE/ICE", "PSY/NUKE"}
# Words that never start a character name when guessing characters from the turn lines
NOT_CHARS = {"HP", "GUARD", "GD", "OR", "AND", "THEN", "SKIP", "AUTO"}


def split_top(s, sep):
    """Split on sep, ignoring separators inside parentheses."""
    out, depth, buf = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    out.append(buf)
    return [x.strip() for x in out if x.strip()]


def _short_personas(val):
    """'Vasuki (Media, Sukukaja), Dion (UT + Cohesion), Shark (damage passives)'"""
    out = []
    for part in split_top(val, ","):
        m = re.match(r"^\s*([^(]+?)\s*(?:\((.*)\))?\s*$", part)
        if not m:
            continue
        inner = (m.group(2) or "").strip()
        skills = [s.strip() for s in re.split(r"\s*[,+]\s*", inner) if s.strip()]
        note = ""
        # "(damage passives)" is a description, not a list of skills
        if len(skills) == 1 and " " in skills[0] and skills[0][:1].islower():
            note, skills = skills[0], []
        out.append(_persona(m.group(1), skills, note))
    return out


def _looks_like_persona_list(val):
    parts = split_top(val, ",")
    return len(parts) >= 2 and all(re.match(r"^[A-Za-z][\w.\- ]*\(.*\)$", p) for p in parts)


def _blank_unit(name):
    return {"name": name, "tag": "", "awareness": "", "rev": "", "weapon": "", "cards": [],
            "role": "", "companion": "", "note": ""}


def _turn_numbers(nums):
    ns = [int(x) for x in re.split(r"\s*[-–]\s*", nums)]
    if len(ns) == 2 and ns[1] > ns[0] + 1:
        return list(range(ns[0], ns[1] + 1))
    return ns


def parse_compact_actions(text, chars, personas):
    """Turn 'Miku S1, Guard, Vasuki Heal, Berry HL + Guard' into action dicts."""
    actions = []
    prev = ""
    for part in split_top(text, ","):
        group_char = ""
        for i, sub in enumerate(split_top(part, "+")):
            act = _compact_one(sub, chars, personas)
            if act is None:
                continue
            if not act["char"] and act["kind"] == "action":
                if i > 0 and group_char:              # "Twins Button + Guard" -> Twins guards
                    act["char"] = group_char
                elif act["btn"] in SKILL_BTNS and prev:   # "Dio HL, S2, S2" -> Dio's S2
                    act["char"] = prev
            if act["char"]:
                group_char = act["char"]
                # Wonder's HL is an interrupt: a bare "S2" after "Dio HL" belongs to whoever acted before
                if not (act["char"] == "WONDER" and act["btn"] == "HL") or not prev:
                    prev = act["char"]
            actions.append(act)
    return actions


def _compact_one(t, chars, personas):
    t = t.strip()
    if not t:
        return None
    hp = re.match(r"^hp\s*lock\s*(on|off)?\s*$", t, re.I)
    if hp:
        return {"char": "", "btn": "HP", "detail": f"HP LOCK {(hp.group(1) or 'ON').upper()}",
                "alt": False, "kind": "toggle"}

    words = t.split()
    char, persona, song = "", "", ""
    w0 = re.sub(r"[^\w]", "", words[0]).upper()
    if w0 in EVERYONE:
        char = "EVERYONE"
    elif w0 in chars:
        char = w0
    elif w0 in MIKU_SONGS:
        char, song = "MIKU", MIKU_SONGS[w0]
    elif words[0].upper() in TWINS_ELEMENTS:
        char = "TWINS"
    else:
        for p in personas:
            if len(w0) >= 3 and p.upper().startswith(w0):
                char, persona = "WONDER", p
                break
    rest = words[1:] if char else words
    if song or (char == "TWINS" and words[0].upper() in TWINS_ELEMENTS):
        rest = [words[0]] + rest       # keep the song / element word

    # Miku: "Heaven 2", "Miku Spring 1", "Fire S1"
    if char == "MIKU" and rest:
        r0 = re.sub(r"[^\w]", "", rest[0]).upper()
        if r0 in MIKU_SONGS:
            song = MIKU_SONGS[r0]
            rest = rest[1:]
            if rest and re.fullmatch(r"[123]", rest[0]):
                rest = ["S" + rest[0]] + rest[1:]

    btn = ""
    if not re.search(r"\bor\b", t, re.I):          # "Guard or Heal" stays as plain text
        depth = 0
        for j, tok in enumerate(rest):
            inside = depth > 0 or tok.startswith("(")
            depth += tok.count("(") - tok.count(")")
            if inside:
                continue                       # ignore words inside (...) comments
            m = BTN_TOKEN_RE.match(re.sub(r"[(),.]", "", tok).upper())
            if m:
                btn = BTN_CANON.get(m.group(1), m.group(1))
                rest = rest[:j] + rest[j + 1:]
                if m.group(2):
                    rest = rest + [f"×{m.group(2)}"]
                break
    detail = " ".join(rest)
    detail = re.sub(r"^\s*[xX×]\s*(\d+)\b", r"×\1", detail)    # "GFB x 2" -> "×2"
    detail = re.sub(r"^\s*-\s+", "", detail)                     # "S3 - (4)" -> "(4)"
    if song:
        detail = ("♪ " + song + ("   " + detail if detail else "")).strip()
    if persona:
        detail = f"{persona} → {detail}" if detail and not btn else \
                 (f"{persona}  {detail}".strip())
    return {"char": char, "btn": btn, "detail": detail, "alt": False, "kind": "action"}


NOTE_RE = re.compile(r"^\s*(?:note\s*[:=]|>)\s*(.*)$", re.I)
ACTION_RE = re.compile(r"^\s*(?P<char>[^:]{1,30}?)\s*:\s*(?P<rest>.*)$")
ALT_RE = re.compile(r"^\s*(?:\(alt\)|alt\s*[:\-])\s*", re.I)


def _guess_chars(raw):
    """Names that start actions followed by a button (e.g. 'Puppet S3') in 2+ places."""
    counts = {}
    for line in raw.splitlines():
        cm = COMPACT_RE.match(line)
        if not cm:
            continue
        for part in split_top(cm.group("rest"), ","):
            for sub in split_top(part, "+"):
                w = sub.split()
                if len(w) >= 2 and re.fullmatch(r"[A-Za-z][A-Za-z.']+", w[0]) \
                        and BTN_TOKEN_RE.match(re.sub(r"[(),.]", "", w[1]).upper()):
                    k = w[0].upper()
                    if k not in MIKU_SONGS and k not in NOT_CHARS:
                        counts[k] = counts.get(k, 0) + 1
    return {k for k, c in counts.items() if c >= 2}


def parse_text(raw):
    title = "Rotation"
    meta, notes, team, turns, units, personas = [], [], [], [], [], []
    btn_names = {}
    cur = None
    first = True
    title_set = False
    order_chars = set()
    after_divider = False
    break_no = 0
    guessed = _guess_chars(raw)

    def known_chars():
        pnames = [p["name"].upper() for p in personas]
        guesses = {g for g in guessed if not any(len(g) >= 3 and pn.startswith(g) for pn in pnames)}
        return ({u["name"].upper() for u in units} | order_chars | guesses | {"WONDER"}) - NOT_CHARS

    def unit_named(name):
        u = next((x for x in units if x["name"].upper() == name.upper()), None)
        if u is None:
            u = _blank_unit(name)
            units.append(u)
        return u

    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("//"):
            continue
        is_first, first = first, False

        # "-Break-", "--- Break ---", a bare "Break": divider before the break turns
        if DIVIDER_RE.match(line):
            after_divider = True
            continue

        # Shorthand turn lines: T1 ..., B2 ..., T7-8-9 ..., Turn 3 (11) ..., Action 19 - T4: ...
        cm = COMPACT_RE.match(line)
        if cm:
            is_break = cm.group("kind").lower().startswith("b")
            label = "Break" if is_break else "TURN"
            ns = _turn_numbers(cm.group("nums"))
            group = (("B" if is_break else "T") + "-".join(str(n) for n in ns)) if len(ns) > 1 else ""
            rest = cm.group("rest")
            lead = ""
            lm = re.match(r"^\s*\(([^()]*)\)\s*(.*)$", rest)    # "(Twins Auto S3 must hit an add) ..."
            if lm:
                lead, rest = lm.group(1).strip(), lm.group(2)
            acts = parse_compact_actions(rest, known_chars(), [p["name"] for p in personas]) if rest else []
            act_no = cm.group("act") or cm.group("act2")
            for k, n in enumerate(ns):
                note = []
                if act_no and k == 0:
                    note.append(f"Action {act_no}")
                if lead and k == 0:
                    note.append(lead)
                if group:
                    note.append(f"({group} are the same)")
                name = f"{label} {n}"
                if after_divider and not is_break:          # T8 after "-Break-" -> "Break 1 (T8)"
                    break_no += 1
                    name = f"Break {break_no} (T{n})"
                cur = {"name": name, "note": "  ·  ".join(note),
                       "actions": [dict(a) for a in acts]}
                turns.append(cur)
            continue

        m = HEADER_RE.match(line)
        if m:
            name = (m.group("b") or m.group("h") or m.group("t")).strip()
            if m.group("t") and not re.search(r"\d", name):
                continue          # a bare "Break" line is just a divider
            cur = {"name": name, "note": "", "actions": []}
            turns.append(cur)
            continue

        if cur is None:
            if is_first:
                # "Puppet a6 brr v2 - Credit: ARCTO"
                cr = re.match(r"^(.*?)\s*[-|(]?\s*\b(?:credits?|by)\s*[:\-]\s*([^)]*)\)?\s*$", line, re.I)
                if cr and cr.group(1).strip():
                    title = cr.group(1).strip().rstrip(":-").strip()
                    title_set = True
                    meta.append("By: " + cr.group(2).strip())
                    continue
            pm = SHORT_PERSONAS_RE.match(line)
            if pm:
                personas.extend(_short_personas(pm.group(1)))
                continue
            # "Twins > Wonder > Kotone > Puppet"  (turn order)
            if line.count(">") >= 2:
                names = [x.strip() for x in line.split(">") if x.strip()]
                order_chars.update(re.sub(r"[^\w]", "", x).upper() for x in names)
                meta.append("Order: " + "  >  ".join(names))
                continue
            # "Borrow Xion's Puppet"
            bm = BORROW_RE.match(line)
            if bm:
                u = unit_named(bm.group(2))
                u["tag"] = "Borrow"
                if bm.group(1):
                    u["note"] = (f"Borrow from {bm.group(1)}  " + u["note"]).strip()
                if bm.group(3):
                    u["note"] = (u["note"] + " " + bm.group(3)).strip()
                continue
            um = SHORT_UNIT_RE.match(line)
            if um and not META_RE.match(line) and not is_first:
                head, val = um.group(1).strip(), um.group(2)
                if _looks_like_persona_list(val):
                    # "Ice Age - Shark (passives), Dion (UT + Cohesion), Jiko (Taru + Mataru)"
                    personas.extend(_short_personas(val))
                    w = unit_named("Wonder")
                    if head.upper() != "WONDER":
                        w["weapon"] = w["weapon"] or head
                    continue
                parts = [p.strip() for p in re.split(r"\s+-\s+", val) if p.strip()]
                if " " not in head and parts and ("/" in parts[0] or "+" in parts[0] or len(parts[0].split()) <= 3):
                    u = unit_named(head)
                    u["cards"] = [c.strip() for c in re.split(r"\s*[/+]\s*", parts[0]) if c.strip()]
                    extra = "  ·  ".join(parts[1:])
                    if extra:
                        u["note"] = (u["note"] + "  " + extra).strip()
                    continue
            if re.match(r"^\s*[\d.,]+(?:\s*[-–~]\s*[\d.,]+)?\s*(?:billion|bil|b|million|mil|m)\s*$",
                        line, re.I) and not is_first:
                meta.append("Score: " + line.strip())
                continue
            wm = re.match(r"^\s*(R\d+)\s+([A-Za-z].*?)\s*$", line)
            if wm and not is_first:
                wonder = unit_named("Wonder")
                wonder["rev"], wonder["weapon"] = wm.group(1).upper(), wm.group(2)
                continue
            mm = META_RE.match(line)
            if is_first and not mm:
                title = line.strip().rstrip(":").strip()
                title_set = True
                continue
            if mm:
                key, val = mm.group(1).lower(), mm.group(2).strip()
                if key in ("title", "name") and not (title_set and key == "name"):
                    title = val
                elif key.startswith("note"):
                    notes.append(val)
                elif key == "team":
                    team.append(val)
                elif key == "unit":
                    u = _text_unit(val)
                    if u:
                        units.append(u)
                elif key == "persona":
                    personas.append(_text_persona(val))
                elif key == "button":
                    # button: KOTONE Ast = Go for Broke
                    k, _, v = val.partition("=")
                    btn_names.update(_btn_names({k.strip(): v.strip()}))
                else:
                    meta.append(f"{key.capitalize()}: {val}")
            else:
                notes.append(line.strip())
            continue

        nm = NOTE_RE.match(line)
        if nm:
            cur["note"] = (cur["note"] + " " + nm.group(1).strip()).strip()
            continue

        alt = False
        if ALT_RE.match(line):
            alt = True
            line = ALT_RE.sub("", line, count=1)

        am = ACTION_RE.match(line)
        if am:
            char = am.group("char").strip()
            rest = am.group("rest").strip()
            if char.upper() == "HP":
                cur["actions"].append({"char": "", "btn": "HP", "detail": f"HP LOCK {rest.upper()}",
                                       "alt": alt, "kind": "toggle"})
                continue
            parts = rest.split(None, 1)
            btn, detail = "", rest
            if parts and parts[0].upper() in KNOWN_BTNS:
                btn = parts[0]
                detail = parts[1] if len(parts) > 1 else ""
            kind = "toggle" if btn.upper() == "HP" else "action"
            cur["actions"].append({"char": char, "btn": btn, "detail": detail,
                                   "alt": alt, "kind": kind})
        else:
            cur["actions"].append({"char": "", "btn": "", "detail": line.strip(),
                                   "alt": alt, "kind": "note"})

    if not turns:
        raise ValueError(
            "No turns were found.\n\nIn a text file, start each turn with a line like\n"
            "TURN 1   or   Break 2   or   [Any name]"
        )
    return {"title": title, "meta": meta, "notes": "\n".join(notes), "team": team, "turns": turns,
            "units": units, "personas": personas, "btn_names": btn_names}


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
def load_cfg():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Updates (GitHub Releases)
# ----------------------------------------------------------------------------
def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def _http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": f"RotationTracker/{APP_VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_latest_release():
    """Returns {version, tag, notes, exe_url, page} for the newest release."""
    with _http_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest") as r:
        data = json.loads(r.read().decode("utf-8"))
    exe_url = next((a["browser_download_url"] for a in data.get("assets", [])
                    if a.get("name", "").lower() == EXE_ASSET.lower()), None)
    tag = data.get("tag_name", "")
    return {"version": tag.lstrip("vV"), "tag": tag, "notes": (data.get("body") or "").strip(),
            "exe_url": exe_url, "page": data.get("html_url", "")}


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def install_update(release, progress=None):
    """Download the new version next to the current one and swap it in.
    Returns the command that starts the new version."""
    if is_frozen():
        target = sys.executable
        url = release["exe_url"]
        if not url:
            raise RuntimeError("This release has no RotationTracker.exe attached yet.")
    else:
        target = os.path.abspath(__file__)
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{release['tag']}/rotation_tracker.py"

    tmp = target + ".new"
    with _http_get(url, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)

    # Sanity-check the download before replacing anything
    with open(tmp, "rb") as f:
        head = f.read()
    if is_frozen():
        if not head.startswith(b"MZ") or len(head) < 1_000_000:
            os.remove(tmp)
            raise RuntimeError("The downloaded file doesn't look like a valid exe.")
    else:
        compile(head.decode("utf-8"), target, "exec")

    # A running exe can't be overwritten on Windows, but it can be renamed.
    old = target + ".old"
    try:
        if os.path.exists(old):
            os.remove(old)
    except OSError:
        pass
    os.replace(target, old)
    os.replace(tmp, target)
    return [target] if is_frozen() else [sys.executable, target]


def cleanup_old_version():
    path = (sys.executable if is_frozen() else os.path.abspath(__file__)) + ".old"
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self, start_file=None):
        super().__init__()
        self.title(APP_NAME)
        self.configure(bg=BG)
        self.cfg = load_cfg()
        self.geometry(self.cfg.get("geometry", "600x720"))
        self.minsize(420, 420)
        self.scale = float(self.cfg.get("scale", 1.0))
        self.rot = None
        self.path = None
        self.idx = 0
        self.char_colors = {}
        self.wrap_labels = []
        self.on_top = tk.BooleanVar(value=bool(self.cfg.get("on_top", False)))
        self.attributes("-topmost", self.on_top.get())

        self._style()
        self._build()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.title(f"{APP_NAME} v{APP_VERSION}")
        target = start_file or self.cfg.get("last_file")
        if target and os.path.exists(target):
            self.open_file(target, resume=True)
        else:
            self.render()

        # Remove the previous version left behind by an update, then look for a new one
        cleanup_old_version()
        self.after(4000, cleanup_old_version)
        if self.cfg.get("auto_update_check", True):
            self.after(1500, lambda: self.check_updates(manual=False))

    # ---- fonts ----
    def f(self, size, weight="normal", slant="roman"):
        return ("Segoe UI", max(7, int(round(size * self.scale))), weight, slant)

    def _style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                     foreground=FG, arrowcolor=FG)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)],
               foreground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    def _btn(self, parent, text, cmd, bg=PANEL, fg=FG, size=10, bold=False, padx=10, pady=4):
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=ACCENT, activeforeground="white",
                      relief="flat", bd=0, cursor="hand2",
                      font=self.f(size, "bold" if bold else "normal"),
                      padx=padx, pady=pady)
        return b

    def _build(self):
        # Toolbar
        self.toolbar = tk.Frame(self, bg=BG)
        self.toolbar.pack(fill="x", padx=10, pady=(10, 4))
        self._btn(self.toolbar, "Open\u2026", self.choose_file).pack(side="left")
        self._btn(self.toolbar, "Team", self.show_team).pack(side="left", padx=(6, 0))
        self._btn(self.toolbar, "Info", self.show_info).pack(side="left", padx=(6, 0))
        self._btn(self.toolbar, "Restart", self.restart).pack(side="left", padx=(6, 0))
        self._btn(self.toolbar, "Updates", lambda: self.check_updates(manual=True)).pack(
            side="left", padx=(6, 0))
        tk.Checkbutton(self.toolbar, text="On top", variable=self.on_top,
                       command=self.toggle_top, bg=BG, fg=FG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG,
                       font=self.f(10)).pack(side="right")
        self._btn(self.toolbar, "A+", lambda: self.zoom(0.1)).pack(side="right", padx=(0, 8))
        self._btn(self.toolbar, "A\u2212", lambda: self.zoom(-0.1)).pack(side="right", padx=(0, 4))

        # Header
        self.header = tk.Frame(self, bg=BG)
        self.header.pack(fill="x", padx=12)
        self.title_lbl = tk.Label(self.header, bg=BG, fg=MUTED, anchor="w", justify="left")
        self.title_lbl.pack(fill="x")

        # Turn row
        self.turn_row = tk.Frame(self, bg=BG)
        self.turn_row.pack(fill="x", padx=12, pady=(6, 0))
        self.turn_lbl = tk.Label(self.turn_row, bg=BG, fg=FG, anchor="w")
        self.turn_lbl.pack(side="left")
        self.progress_lbl = tk.Label(self.turn_row, bg=BG, fg=MUTED)
        self.progress_lbl.pack(side="left", padx=(10, 0), pady=(8, 0))
        self.jump = ttk.Combobox(self.turn_row, state="readonly", width=18)
        self.jump.pack(side="right", pady=(6, 0))
        self.jump.bind("<<ComboboxSelected>>", lambda e: self.go(self.jump.current()))

        self.bar = tk.Canvas(self, height=6, bg=PANEL, highlightthickness=0)
        self.bar.pack(fill="x", padx=12, pady=(6, 4))

        self.note_lbl = tk.Label(self, bg=BG, fg=NOTE_FG, anchor="w", justify="left")
        self.note_lbl.pack(fill="x", padx=12)

        # Bottom nav (packed before the list so it stays visible)
        self.nav = tk.Frame(self, bg=BG)
        self.nav.pack(side="bottom", fill="x", padx=10, pady=10)
        self.prev_btn = self._btn(self.nav, "\u25c0  Prev", self.prev, size=13, pady=10)
        self.prev_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.next_btn = self._btn(self.nav, "Next turn  \u25b6", self.next, bg=ACCENT,
                                  fg="white", size=13, bold=True, pady=10)
        self.next_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # Scrollable actions list
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=10, pady=(6, 0))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        self.vsb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list_frame = tk.Frame(self.canvas, bg=BG)
        self.list_win = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.list_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        self.bind("<Configure>", self._on_window_resize)

    def _bind_keys(self):
        for k in ("<Right>", "<space>", "<Return>", "<Next>", "<d>", "<D>"):
            self.bind(k, lambda e: self.next())
        for k in ("<Left>", "<BackSpace>", "<Prior>", "<a>", "<A>"):
            self.bind(k, lambda e: self.prev())
        self.bind("<Home>", lambda e: self.go(0))
        self.bind("<End>", lambda e: self.go(len(self.rot["turns"]) - 1) if self.rot else None)
        self.bind("<Control-o>", lambda e: self.choose_file())
        self.bind("<t>", lambda e: self.show_team())
        self.bind("<T>", lambda e: self.show_team())
        self.bind("<Control-plus>", lambda e: self.zoom(0.1))
        self.bind("<Control-equal>", lambda e: self.zoom(0.1))
        self.bind("<Control-minus>", lambda e: self.zoom(-0.1))

    def _on_wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")

    def _on_canvas_resize(self, e):
        self.canvas.itemconfigure(self.list_win, width=e.width)
        for lbl, extra in self.wrap_labels:
            lbl.configure(wraplength=max(100, e.width - extra))

    def _on_window_resize(self, e):
        if e.widget is self:
            w = max(200, self.winfo_width() - 30)
            self.note_lbl.configure(wraplength=w)
            self.title_lbl.configure(wraplength=w)

    # ---- file handling ----
    def choose_file(self):
        start = os.path.dirname(self.path) if self.path else os.path.expanduser("~")
        path = filedialog.askopenfilename(
            title="Open rotation", initialdir=start,
            filetypes=[("Rotation files", "*.json *.txt"), ("JSON", "*.json"),
                       ("Text", "*.txt"), ("All files", "*.*")])
        if path:
            self.open_file(path)

    def open_file(self, path, resume=False):
        try:
            rot = load_rotation(path)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Couldn't open this rotation:\n\n{e}")
            return
        self.rot = rot
        self.path = os.path.abspath(path)
        self.char_colors = {}
        for u in rot.get("units", []):
            c = u["name"].upper()
            if c not in self.char_colors:
                self.char_colors[c] = CHAR_PALETTE[len(self.char_colors) % len(CHAR_PALETTE)]
        for t in rot["turns"]:
            for a in t["actions"]:
                c = a["char"].upper()
                if c and c not in self.char_colors:
                    self.char_colors[c] = CHAR_PALETTE[len(self.char_colors) % len(CHAR_PALETTE)]
        positions = self.cfg.get("positions", {})
        self.idx = positions.get(self.path, 0) if resume else 0
        self.idx = max(0, min(self.idx, len(rot["turns"]) - 1))
        self.cfg["last_file"] = self.path
        self.title(f"{rot['title']} \u2014 {APP_NAME} v{APP_VERSION}")
        self.jump.configure(values=[f"{i + 1}. {t['name']}" for i, t in enumerate(rot["turns"])])
        self.render()
        if not resume and rot.get("notes"):
            self.show_info()

    # ---- navigation ----
    def go(self, i):
        if not self.rot:
            return
        self.idx = max(0, min(i, len(self.rot["turns"]) - 1))
        self.render()
        self.cfg.setdefault("positions", {})[self.path] = self.idx
        save_cfg(self.cfg)

    def next(self):
        if self.rot:
            self.go(self.idx + 1)

    def prev(self):
        if self.rot:
            self.go(self.idx - 1)

    def restart(self):
        if self.rot:
            self.go(0)

    def zoom(self, d):
        self.scale = max(0.6, min(2.5, round(self.scale + d, 2)))
        self.cfg["scale"] = self.scale
        for w in self.toolbar.winfo_children():
            try:
                w.configure(font=self.f(10))
            except tk.TclError:
                pass
        self.prev_btn.configure(font=self.f(13))
        self.next_btn.configure(font=self.f(13, "bold"))
        self.render()

    def toggle_top(self):
        self.attributes("-topmost", self.on_top.get())
        self.cfg["on_top"] = self.on_top.get()

    # ---- drawing ----
    def render(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.wrap_labels = []
        self.title_lbl.configure(font=self.f(10))
        self.turn_lbl.configure(font=self.f(24, "bold"))
        self.progress_lbl.configure(font=self.f(11))
        self.note_lbl.configure(font=self.f(11, slant="italic"))

        if not self.rot:
            self.title_lbl.configure(text="")
            self.turn_lbl.configure(text="No rotation loaded")
            self.progress_lbl.configure(text="")
            self.note_lbl.configure(text="")
            tk.Label(self.list_frame, text="Click Open\u2026 (or Ctrl+O) to load a .json or .txt rotation.\n\n"
                     "Keys: Space / \u2192 = next turn,  \u2190 = previous turn",
                     bg=BG, fg=MUTED, font=self.f(11), justify="left").pack(anchor="w", pady=20, padx=4)
            self.prev_btn.configure(state="disabled")
            self.next_btn.configure(state="disabled")
            self._draw_bar(0)
            return

        turns = self.rot["turns"]
        t = turns[self.idx]
        sub = self.rot["title"]
        if self.rot["meta"]:
            sub += "   \u00b7   " + "   \u00b7   ".join(self.rot["meta"][:4])
        self.title_lbl.configure(text=sub)
        self.turn_lbl.configure(text=t["name"])
        self.progress_lbl.configure(text=f"{self.idx + 1} / {len(turns)}")
        self.note_lbl.configure(text=t["note"])
        self.jump.current(self.idx)
        self._draw_bar((self.idx + 1) / len(turns))

        if not t["actions"]:
            tk.Label(self.list_frame, text="(No actions listed for this turn)", bg=BG, fg=MUTED,
                     font=self.f(11)).pack(anchor="w", pady=10, padx=4)

        width = max(300, self.canvas.winfo_width())
        step = 0
        for a in t["actions"]:
            if a["kind"] == "note":
                lbl = tk.Label(self.list_frame, text="\u26a0  " + a["detail"], bg=BG, fg=NOTE_FG,
                               font=self.f(11, "bold"), anchor="w", justify="left",
                               wraplength=width - 30)
                lbl.pack(fill="x", padx=4, pady=(4, 6))
                self.wrap_labels.append((lbl, 30))
                continue

            step += 1
            card = tk.Frame(self.list_frame, bg=CARD_ALT if a["alt"] else CARD)
            card.pack(fill="x", pady=3, padx=2)
            cbg = card["bg"]

            tk.Label(card, text=str(step), bg=cbg, fg=MUTED, font=self.f(11),
                     width=3).pack(side="left", padx=(6, 0), pady=8)

            if a["char"]:
                tk.Label(card, text=a["char"].upper(), bg=cbg,
                         fg=self.char_colors.get(a["char"].upper(), FG),
                         font=self.f(14, "bold"), width=9, anchor="w").pack(side="left", padx=(4, 6))

            if a["btn"]:
                color = BTN_COLORS.get(a["btn"].upper(), DEFAULT_BTN_COLOR)
                tk.Label(card, text=self.btn_label(a["char"], a["btn"]), bg=color, fg="white", font=self.f(13, "bold"),
                         padx=10, pady=2).pack(side="left", padx=(0, 10))

            extra = 260
            detail = a["detail"]
            if a["alt"]:
                tk.Label(card, text="ALT", bg="#4c3a66", fg="#e9d5ff", font=self.f(9, "bold"),
                         padx=6).pack(side="left", padx=(0, 8))
                extra += 50
            if detail:
                lbl = tk.Label(card, text=detail, bg=cbg, fg=FG, font=self.f(12), anchor="w",
                               justify="left", wraplength=max(100, width - extra))
                lbl.pack(side="left", fill="x", expand=True, pady=6)
                self.wrap_labels.append((lbl, extra))

        self.canvas.yview_moveto(0)
        last = self.idx >= len(turns) - 1
        self.prev_btn.configure(state="normal" if self.idx > 0 else "disabled")
        self.next_btn.configure(state="disabled" if last else "normal",
                                text="Last turn \u2714" if last else "Next turn  \u25b6")

    def _draw_bar(self, frac):
        self.bar.delete("all")
        self.update_idletasks()
        w = self.bar.winfo_width()
        if frac > 0:
            self.bar.create_rectangle(0, 0, int(w * frac), 6, fill=ACCENT, width=0)

    def btn_label(self, char, btn):
        key = (char.upper(), btn.upper())
        names = dict(CHAR_BTN_NAMES)
        if self.rot:
            names.update(self.rot.get("btn_names", {}))
        return names.get(key) or BTN_NAMES.get(btn.upper(), btn)

    def show_team(self):
        if not self.rot:
            return
        if getattr(self, "team_win", None) and self.team_win.winfo_exists():
            self.team_win.destroy()
        win = self.team_win = tk.Toplevel(self)
        win.title("Team — " + self.rot["title"])
        win.configure(bg=BG)
        win.geometry(self.cfg.get("team_geometry", "520x640"))
        win.attributes("-topmost", self.on_top.get())
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<t>", lambda e: win.destroy())
        win.protocol("WM_DELETE_WINDOW", lambda: (self.cfg.__setitem__("team_geometry", win.geometry()),
                                                  win.destroy()))

        canvas = tk.Canvas(win, bg=BG, highlightthickness=0)
        vsb = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        body = tk.Frame(canvas, bg=BG)
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        wraps = []

        def on_resize(e):
            canvas.itemconfigure(body_win, width=e.width)
            for lbl in wraps:
                lbl.configure(wraplength=max(150, e.width - 50))
        canvas.bind("<Configure>", on_resize)

        def line(parent, label, value, fg=FG, italic=False):
            row = tk.Frame(parent, bg=CARD)
            row.pack(fill="x", padx=12, pady=1)
            if label:
                tk.Label(row, text=label, bg=CARD, fg=MUTED, font=self.f(10), width=9,
                         anchor="w").pack(side="left", anchor="n")
            lbl = tk.Label(row, text=value, bg=CARD, fg=fg, anchor="w", justify="left",
                           font=self.f(11, slant="italic" if italic else "roman"), wraplength=380)
            lbl.pack(side="left", fill="x", expand=True)
            wraps.append(lbl)

        units = self.rot.get("units") or []
        personas = self.rot.get("personas") or []
        has_wonder = any(u["name"].upper() == "WONDER" for u in units)

        if not units and not personas:
            if self.rot.get("team"):
                for t in self.rot["team"]:
                    lbl = tk.Label(body, text=t, bg=BG, fg=FG, font=self.f(11), anchor="w",
                                   justify="left", wraplength=400)
                    lbl.pack(fill="x", padx=4, pady=3)
                    wraps.append(lbl)
            else:
                tk.Label(body, text="This rotation has no team info.", bg=BG, fg=MUTED,
                         font=self.f(11)).pack(anchor="w", padx=4, pady=10)

        def persona_block(parent):
            tk.Label(parent, text="Personas", bg=CARD, fg=ACCENT, font=self.f(11, "bold"),
                     anchor="w").pack(fill="x", padx=12, pady=(8, 2))
            for p in personas:
                prow = tk.Frame(parent, bg=PANEL)
                prow.pack(fill="x", padx=12, pady=2)
                top = tk.Frame(prow, bg=PANEL)
                top.pack(fill="x", padx=8, pady=(5, 3))
                tk.Label(top, text=p["name"], bg=PANEL, fg=FG, font=self.f(12, "bold")).pack(side="left")
                for s in p["skills"]:
                    tk.Label(top, text=s, bg="#334155", fg=FG, font=self.f(10), padx=6,
                             pady=1).pack(side="left", padx=(6, 0))
                if p["note"]:
                    lbl = tk.Label(prow, text=p["note"], bg=PANEL, fg=MUTED, font=self.f(10, slant="italic"),
                                   anchor="w", justify="left", wraplength=380)
                    lbl.pack(fill="x", padx=8, pady=(0, 5))
                    wraps.append(lbl)

        for u in units:
            card = tk.Frame(body, bg=CARD)
            card.pack(fill="x", pady=4, padx=2)
            head = tk.Frame(card, bg=CARD)
            head.pack(fill="x", padx=12, pady=(8, 4))
            tk.Label(head, text=u["name"].upper(), bg=CARD,
                     fg=self.char_colors.get(u["name"].upper(), FG),
                     font=self.f(15, "bold")).pack(side="left")
            if u["tag"]:
                tk.Label(head, text=u["tag"], bg="#4c3a66", fg="#e9d5ff", font=self.f(9, "bold"),
                         padx=6).pack(side="left", padx=(8, 0))
            lvl = "  ".join(x for x in (u["awareness"], u["rev"]) if x)
            if lvl:
                tk.Label(head, text=lvl, bg=CARD, fg=MUTED, font=self.f(11)).pack(side="left", padx=(10, 0))
            if u["role"]:
                tk.Label(head, text=u["role"], bg=CARD, fg=NOTE_FG,
                         font=self.f(10, "bold")).pack(side="right")
            if u["weapon"]:
                line(card, "Weapon", u["weapon"])
            if u["cards"]:
                line(card, "Cards", "  ·  ".join(u["cards"]))
            if u["companion"]:
                line(card, "Companion", u["companion"])
            if u["note"]:
                line(card, "", u["note"], fg=NOTE_FG, italic=True)
            if u["name"].upper() == "WONDER" and personas:
                persona_block(card)
            tk.Frame(card, bg=CARD, height=6).pack(fill="x")

        if personas and not has_wonder:
            card = tk.Frame(body, bg=CARD)
            card.pack(fill="x", pady=4, padx=2)
            persona_block(card)
            tk.Frame(card, bg=CARD, height=6).pack(fill="x")

    def show_info(self):
        if not self.rot:
            return
        win = tk.Toplevel(self)
        win.title(self.rot["title"])
        win.configure(bg=BG)
        win.geometry("560x560")
        win.attributes("-topmost", self.on_top.get())
        txt = tk.Text(win, bg=PANEL, fg=FG, font=self.f(11), wrap="word", relief="flat",
                      padx=12, pady=10, insertbackground=FG)
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.tag_configure("h", font=self.f(13, "bold"), foreground=ACCENT, spacing1=8, spacing3=4)
        txt.insert("end", self.rot["title"] + "\n", "h")
        txt.insert("end", f"{APP_NAME} v{APP_VERSION}\n")
        if self.rot["meta"]:
            txt.insert("end", "\n".join(self.rot["meta"]) + "\n")
        if self.rot["team"]:
            txt.insert("end", "\nTeam\n", "h")
            txt.insert("end", "\n".join(self.rot["team"]) + "\n")
        if self.rot["notes"]:
            txt.insert("end", "\nNotes & adjustments\n", "h")
            txt.insert("end", self.rot["notes"] + "\n")
        txt.configure(state="disabled")
        self._btn(win, "Close", win.destroy).pack(pady=(0, 8))
        win.bind("<Escape>", lambda e: win.destroy())

    # ---- updates ----
    def _in_background(self, work, done):
        """Run work() in a thread, then done(result, error) on the UI thread."""
        box = {}

        def run():
            try:
                box["result"] = work()
            except Exception as e:
                box["error"] = e
            box["finished"] = True

        def poll():
            if box.get("finished"):
                done(box.get("result"), box.get("error"))
            else:
                self.after(100, poll)

        threading.Thread(target=run, daemon=True).start()
        poll()

    def check_updates(self, manual=False):
        if getattr(self, "_checking", False):
            return
        self._checking = True

        def done(rel, err):
            self._checking = False
            if err:
                if manual:
                    messagebox.showerror(APP_NAME, f"Couldn't check for updates:\n\n{err}")
                return
            newer = _ver_tuple(rel["version"]) > _ver_tuple(APP_VERSION)
            if not newer:
                if manual:
                    messagebox.showinfo(APP_NAME, f"You're on the latest version (v{APP_VERSION}).")
                return
            if not manual and self.cfg.get("skip_version") == rel["version"]:
                return
            self.prompt_update(rel, manual)

        self._in_background(fetch_latest_release, done)

    def prompt_update(self, rel, manual):
        notes = rel["notes"]
        if len(notes) > 600:
            notes = notes[:600].rstrip() + "…"
        msg = f"Version {rel['version']} is available (you have {APP_VERSION})."
        if notes:
            msg += f"\n\nWhat's new:\n{notes}"
        msg += "\n\nUpdate now? The app will restart."
        if is_frozen() and not rel["exe_url"]:
            messagebox.showinfo(APP_NAME, f"Version {rel['version']} is being prepared. "
                                          "Try again in a few minutes.")
            return
        ans = messagebox.askyesno(APP_NAME, msg, parent=self)
        if ans:
            self.do_update(rel)
        elif not manual:
            self.cfg["skip_version"] = rel["version"]   # don't nag again for this version
            save_cfg(self.cfg)

    def do_update(self, rel):
        win = tk.Toplevel(self)
        win.title("Updating…")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.transient(self)
        lbl = tk.Label(win, text=f"Downloading v{rel['version']}…", bg=BG, fg=FG,
                       font=self.f(11), padx=30, pady=20)
        lbl.pack()
        state = {"text": lbl["text"]}

        def progress(done, total):
            state["text"] = (f"Downloading v{rel['version']}…  {done * 100 // total}%"
                             if total else f"Downloading v{rel['version']}…  {done // 1024} KB")

        def tick():
            if win.winfo_exists():
                lbl.configure(text=state["text"])
                win.after(150, tick)
        tick()

        def done(cmd, err):
            if err:
                win.destroy()
                messagebox.showerror(APP_NAME, f"The update failed, nothing was changed:\n\n{err}\n\n"
                                               f"You can download it manually from:\n{rel['page']}")
                return
            self.cfg["geometry"] = self.geometry()
            self.cfg.pop("skip_version", None)
            save_cfg(self.cfg)
            try:
                # Clean environment so the new version unpacks into its own temp folder
                subprocess.Popen(cmd + ([self.path] if self.path else []),
                                 cwd=os.path.dirname(cmd[-1]), env=clean_child_env())
            except Exception as e:
                messagebox.showinfo(APP_NAME, f"Updated to v{rel['version']}. Please start the app "
                                              f"again.\n\n({e})")
            self.destroy()

        self._in_background(lambda: install_update(rel, progress), done)

    def on_close(self):
        self.cfg["geometry"] = self.geometry()
        save_cfg(self.cfg)
        self.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    start = sys.argv[1] if len(sys.argv) > 1 else None
    App(start).mainloop()


if __name__ == "__main__":
    main()
