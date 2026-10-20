"""Per-repository settings: `.memcode/config.json` (in the shared store directory) and the on/off switches.

A switch is decided by its environment variable if set (1/true/on or 0/false/off), else by the repo's config file
(`memcode config KEY on|off`), else by its default. `memcode config` with no key prints them all.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ON, OFF = ("1", "true", "on"), ("0", "false", "off")


def path(root) -> Path:
    from .store import memdir
    return memdir(root) / "config.json"


def read(root) -> dict:
    try:
        cfg = json.loads(path(root).read_text())
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def write(root, **kv) -> dict:
    cfg = read(root)
    cfg.update(kv)
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg


def switch(root, env: str, key: str, default: bool) -> bool:
    """env var (if set) > the repo's config key (if set) > default."""
    v = os.environ.get(env, "").lower()
    if v in ON:
        return True
    if v in OFF:
        return False
    stored = read(root).get(key)
    return default if stored is None else bool(stored)
