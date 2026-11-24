#!/usr/bin/env python3
"""
Build ankicon.ankiaddon, and regenerate config.json from settings.defaults()
so the shipped defaults can never drift from the code.

Run from the repo root:  python3 build.py
"""

from __future__ import annotations

import json
import os
import sys
import types
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "ankicon"

MANIFEST = {
    "package": PACKAGE,
    "name": "Anki-Con",
    "mod": 0,
    "conflicts": [],
    "min_point_version": 50,
    "max_point_version": 0,
    "human_version": "1.1.0",
}

INCLUDE = [
    "__init__.py", "actions.py", "art.py", "controller.py", "dialog.py",
    "joycon_view.py", "profiles.py", "settings.py", "style.py",
    "config.json", "config.md", "manifest.json", "README.md",
    "joycon/__init__.py", "joycon/backend_hidapi.py", "joycon/backend_macos.py",
    "joycon/device.py", "joycon/hub.py", "joycon/protocol.py",
]


def _import_settings():
    """Load settings.py without Anki or Qt present, so this runs anywhere.

    The real __init__.py installs menus and imports Qt on import, so a synthetic
    package is stood up here instead: settings.py's relative imports (art,
    joycon.protocol) resolve against it, and none of those touch Qt.
    """
    import importlib.util

    aqt = types.ModuleType("aqt")
    aqt.mw = None
    sys.modules.setdefault("aqt", aqt)

    pkg = types.ModuleType("_ankicon_build")
    pkg.__path__ = [ROOT]
    sys.modules["_ankicon_build"] = pkg

    spec = importlib.util.spec_from_file_location(
        "_ankicon_build.settings", os.path.join(ROOT, "settings.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def write_config() -> dict:
    cfg = _import_settings().defaults()
    for key in ("active_profile", "window_size"):
        cfg.pop(key, None)               # per-install, not a shipped default
    path = os.path.join(ROOT, "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return cfg


def write_manifest() -> None:
    with open(os.path.join(ROOT, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(MANIFEST, fh, indent=2)
        fh.write("\n")


def build() -> str:
    write_manifest()
    write_config()
    out = os.path.join(ROOT, f"{PACKAGE}.ankiaddon")
    missing = [f for f in INCLUDE if not os.path.exists(os.path.join(ROOT, f))]
    if missing:
        raise SystemExit(f"missing files: {missing}")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in INCLUDE:
            z.write(os.path.join(ROOT, name), name)
        # user_files must exist in the archive so Anki creates it on install;
        # profiles the user saves then survive add-on updates.
        z.writestr("user_files/profiles/.keep", "")
    return out


if __name__ == "__main__":
    print("wrote", build())
