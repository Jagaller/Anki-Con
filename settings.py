"""Config load/save: per-layout button maps, colours, and defaults."""

from __future__ import annotations

from typing import Dict, Iterable, List

from aqt import mw

from . import art
from .joycon import protocol as P

ADDON = __name__.split(".")[0]

# --------------------------------------------------------------------------
# Layouts
#
# How you hold the hardware changes which buttons your fingers can actually
# reach, so each grip keeps its own complete map rather than sharing one.
# --------------------------------------------------------------------------

LAYOUT_DUAL = "dual"
LAYOUT_SINGLE_H = "single_h"
LAYOUT_SINGLE_V = "single_v"

LAYOUTS = [LAYOUT_DUAL, LAYOUT_SINGLE_H, LAYOUT_SINGLE_V]

LAYOUT_LABELS = {
    LAYOUT_DUAL: "Dual-Controller Grip",
    LAYOUT_SINGLE_H: "Horizontal",
    LAYOUT_SINGLE_V: "Handheld (Vertical)",
}

# Face buttons and the D-pad keep the same meaning in every grip -- muscle
# memory for Again/Hard/Good/Easy shouldn't move around. What does change is
# the shoulders and rail, which is where reachability actually differs.
_FACE = {
    "R:A": "good", "R:B": "again", "R:X": "easy", "R:Y": "hard",
    "L:Right": "good", "L:Down": "again", "L:Up": "easy", "L:Left": "hard",
}

_COMMON = {
    "R:Plus": "more_menu", "R:Home": "auto_advance", "R:RStick": "mark_note",
    "L:Minus": "more_menu", "L:Capture": "mark_note", "L:LStick": "flag_1",

    "R:StickUp": "replay_audio", "R:StickDown": "bury_card",
    "R:StickLeft": "audio_back", "R:StickRight": "audio_forward",
    "L:StickUp": "replay_audio", "L:StickDown": "bury_card",
    "L:StickLeft": "audio_back", "L:StickRight": "audio_forward",
}

_LAYOUT_SPECIFIC = {
    # Both halves in a grip: SL/SR are physically covered, so leave them unbound
    # rather than hiding actions behind plastic.
    LAYOUT_DUAL: {
        "R:R": "show_answer", "R:ZR": "replay_audio",
        "L:L": "undo", "L:ZL": "pause_audio",
        "R:SL": "none", "R:SR": "none", "L:SL": "none", "L:SR": "none",
    },
    # Held sideways the rail buttons become the shoulders, right under your
    # index finger -- the best place for Show Answer.
    LAYOUT_SINGLE_H: {
        "R:SR": "show_answer", "R:SL": "undo",
        "L:SR": "show_answer", "L:SL": "undo",
        "R:R": "replay_audio", "R:ZR": "pause_audio",
        "L:L": "replay_audio", "L:ZL": "pause_audio",
    },
    # Upright in one hand: the real shoulders are back under your index finger
    # and the rail faces away from you.
    LAYOUT_SINGLE_V: {
        "R:R": "show_answer", "R:ZR": "replay_audio",
        "L:L": "show_answer", "L:ZL": "replay_audio",
        "R:SL": "audio_back", "R:SR": "audio_forward",
        "L:SL": "audio_back", "L:SR": "audio_forward",
    },
}


def all_binding_ids() -> List[str]:
    return P.buttons_for_side(P.SIDE_LEFT) + P.buttons_for_side(P.SIDE_RIGHT)


def default_layout(layout: str) -> Dict[str, str]:
    """A complete map for one grip: every id present, unbound ones as "none"."""
    out = {b: "none" for b in all_binding_ids()}
    out.update(_FACE)
    out.update(_COMMON)
    out.update(_LAYOUT_SPECIFIC.get(layout, {}))
    return out


def default_layouts() -> Dict[str, Dict[str, str]]:
    return {name: default_layout(name) for name in LAYOUTS}


# --------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------

def default_colors() -> dict:
    return {
        "shell": {"left": art.DEFAULT_SHELL_LEFT, "right": art.DEFAULT_SHELL_RIGHT},
        # sparse: only buttons the user actually recoloured are stored
        "buttons": {},
    }


def button_color(cfg: dict, side: str, element_id: str) -> str:
    key = art.binding_id(side, element_id)
    override = (cfg.get("colors") or {}).get("buttons", {}).get(key)
    return override or art.default_button_color(side, element_id)


def shell_color(cfg: dict, side: str) -> str:
    shell = (cfg.get("colors") or {}).get("shell", {})
    key = "left" if side == P.SIDE_LEFT else "right"
    return shell.get(key) or (art.DEFAULT_SHELL_LEFT if key == "left"
                              else art.DEFAULT_SHELL_RIGHT)


# --------------------------------------------------------------------------
# Defaults + load/save
# --------------------------------------------------------------------------

def defaults() -> dict:
    return {
        "enabled": True,
        "layouts": default_layouts(),
        # which single-Joy-Con grip to assume when only one is connected
        "orientation": LAYOUT_SINGLE_H,
        "colors": default_colors(),
        "active_profile": "",
        "window_size": None,
        "rumble_on_answer": False,
        "rumble_strength": 0.35,
        "player_leds": True,
        "stick_deadzone": 0.5,
        # Take the controller away from macOS's own Joy-Con driver. Needed when
        # the system grabs it first and our HID open gets refused.
        "seize_device": False,
        "ease_reveals_answer": True,
        "show_tooltip_on_action": False,
        "verbose_log": False,
    }


DEFAULTS = defaults()


def normalise(raw: dict) -> dict:
    """Fold stored config onto a full default, tolerating older schemas."""
    cfg = defaults()
    raw = raw or {}

    # v1 stored a single flat "bindings" map with no notion of grip. Seed every
    # layout from it so an upgrade keeps the mapping the user already tuned.
    legacy = raw.get("bindings")
    if isinstance(legacy, dict) and legacy:
        for name in LAYOUTS:
            cfg["layouts"][name].update(
                {k: v for k, v in legacy.items() if isinstance(v, str)})

    stored = raw.get("layouts")
    if isinstance(stored, dict):
        for name in LAYOUTS:
            got = stored.get(name)
            if isinstance(got, dict):
                cfg["layouts"][name].update(
                    {k: v for k, v in got.items() if isinstance(v, str)})

    colors = raw.get("colors")
    if isinstance(colors, dict):
        if isinstance(colors.get("shell"), dict):
            cfg["colors"]["shell"].update(
                {k: v for k, v in colors["shell"].items() if isinstance(v, str)})
        if isinstance(colors.get("buttons"), dict):
            cfg["colors"]["buttons"] = {
                k: v for k, v in colors["buttons"].items() if isinstance(v, str)}

    if raw.get("orientation") in (LAYOUT_SINGLE_H, LAYOUT_SINGLE_V):
        cfg["orientation"] = raw["orientation"]

    for key in ("enabled", "rumble_on_answer", "rumble_strength", "player_leds",
                "stick_deadzone", "seize_device", "ease_reveals_answer",
                "show_tooltip_on_action", "verbose_log", "active_profile",
                "window_size"):
        if key in raw:
            cfg[key] = raw[key]

    return cfg


def get() -> dict:
    return normalise(mw.addonManager.getConfig(ADDON) or {})


def save(cfg: dict) -> None:
    mw.addonManager.writeConfig(ADDON, cfg)


# --------------------------------------------------------------------------
# Which layout is live right now
# --------------------------------------------------------------------------

def active_layout(sides: Iterable[str], orientation: str) -> str:
    """Pick the grip from what's actually connected.

    Two halves (or a Pro Controller, which reports both) means every button is
    reachable, so the dual map wins and the orientation choice doesn't apply.
    """
    sides = set(sides or ())
    if P.SIDE_PRO in sides:
        return LAYOUT_DUAL
    if P.SIDE_LEFT in sides and P.SIDE_RIGHT in sides:
        return LAYOUT_DUAL
    if sides:
        return orientation if orientation in (LAYOUT_SINGLE_H, LAYOUT_SINGLE_V) \
            else LAYOUT_SINGLE_H
    return LAYOUT_DUAL


def bindings_for(cfg: dict, layout: str) -> Dict[str, str]:
    return cfg.get("layouts", {}).get(layout) or default_layout(layout)


def reset_layout(cfg: dict, layout: str) -> None:
    cfg.setdefault("layouts", {})[layout] = default_layout(layout)
