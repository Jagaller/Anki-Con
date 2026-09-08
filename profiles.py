"""
Controller profiles: named bundles of bindings + colours, one JSON file each.

They live in the add-on's ``user_files`` directory, which Anki preserves across
add-on updates, so a profile is a real file the user can back up or hand to
someone else.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import List, Optional

from . import settings

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "user_files", "profiles")

SUFFIX = ".ankicon.json"

# Only the parts of the config that describe the controller; options like
# rumble strength and logging stay session-wide and are deliberately excluded.
PROFILE_KEYS = ("layouts", "colors", "orientation")


def _dir() -> str:
    os.makedirs(_DIR, exist_ok=True)
    return _DIR


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .-_")
    return slug or "profile"


def _path(name: str) -> str:
    return os.path.join(_dir(), _slug(name) + SUFFIX)


# --------------------------------------------------------------------------

def to_payload(cfg: dict, name: str) -> dict:
    return {
        "ankicon_profile": 1,
        "name": name,
        "saved": time.strftime("%Y-%m-%d %H:%M"),
        **{k: cfg.get(k) for k in PROFILE_KEYS},
    }


def apply_payload(cfg: dict, payload: dict) -> dict:
    """Merge a profile into a live config, leaving non-profile options alone."""
    merged = dict(cfg)
    for key in PROFILE_KEYS:
        if payload.get(key) is not None:
            merged[key] = payload[key]
    # Back through normalise so a hand-edited or older file can't leave the
    # config half-populated; it keeps the non-profile options untouched.
    return settings.normalise(merged)


# --------------------------------------------------------------------------

def names() -> List[str]:
    try:
        files = os.listdir(_dir())
    except OSError:
        return []
    out = []
    for f in sorted(files):
        if not f.endswith(SUFFIX):
            continue
        payload = _read(os.path.join(_dir(), f))
        if payload:
            out.append(payload.get("name") or f[: -len(SUFFIX)])
    return sorted(out, key=str.lower)


def _read(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: str, payload: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def exists(name: str) -> bool:
    return os.path.exists(_path(name))


def save(name: str, cfg: dict) -> str:
    path = _path(name)
    _write(path, to_payload(cfg, name))
    return path


def load(name: str) -> Optional[dict]:
    return _read(_path(name))


def delete(name: str) -> bool:
    try:
        os.remove(_path(name))
        return True
    except OSError:
        return False


def export_to(path: str, cfg: dict, name: str) -> None:
    _write(path, to_payload(cfg, name))


def import_from(path: str) -> Optional[dict]:
    """Read an exported file and copy it into the profile directory."""
    payload = _read(path)
    if not payload or not any(k in payload for k in PROFILE_KEYS):
        return None
    name = payload.get("name") or os.path.basename(path).split(".")[0]
    base = name
    n = 2
    while exists(name):
        name = f"{base} ({n})"
        n += 1
    payload["name"] = name
    _write(_path(name), payload)
    return payload
