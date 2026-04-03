"""
roblox_manifest.py — game.json manifest read/write helpers for the Roblox Agent.
Tracks game state, file registry, RemoteEvents, DataStores, and economy config.
"""

import json
import os
from datetime import datetime

DEFAULT_MANIFEST = {
    "game_name": "Untitled",
    "genre": "unknown",
    "project_root": "",
    "systems": [],
    "files": [],
    "remote_events": [],
    "remote_functions": [],
    "datastores": [],
    "economy": {
        "currency": "Coins",
        "items": []
    },
    "last_updated": "",
}


def get_manifest(project_root: str) -> dict:
    """Read game.json from project_root, creating it with defaults if missing."""
    if not project_root:
        manifest = DEFAULT_MANIFEST.copy()
        manifest["project_root"] = ""
        return manifest

    path = os.path.join(project_root, "game.json")
    if not os.path.exists(path):
        manifest = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULT_MANIFEST.items()}
        manifest["project_root"] = project_root
        save_manifest(project_root, manifest)
        return manifest

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        manifest = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULT_MANIFEST.items()}
        manifest["project_root"] = project_root
        return manifest


def save_manifest(project_root: str, manifest: dict):
    """Write manifest to game.json, updating last_updated timestamp."""
    if not project_root:
        return
    manifest["last_updated"] = datetime.now().isoformat()
    path = os.path.join(project_root, "game.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except Exception:
        pass


def register_file(project_root: str, filepath: str, system: str = ""):
    """Register a new file path and optional system name in the manifest."""
    manifest = get_manifest(project_root)
    if filepath not in manifest["files"]:
        manifest["files"].append(filepath)
    if system and system not in manifest["systems"]:
        manifest["systems"].append(system)
    save_manifest(project_root, manifest)


def register_remote_event(project_root: str, name: str, event_type: str = "RemoteEvent"):
    """Register a RemoteEvent or RemoteFunction in the manifest."""
    manifest = get_manifest(project_root)
    key = "remote_events" if event_type == "RemoteEvent" else "remote_functions"
    if name not in manifest[key]:
        manifest[key].append(name)
    save_manifest(project_root, manifest)
