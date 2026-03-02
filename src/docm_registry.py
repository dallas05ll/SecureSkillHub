"""
Documentation Manager (DocM) File Registry.

Persistent file tracking so PM can operate autonomously across sessions.
Registry lives in memory files (local only, not committed).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

MEMORY_DIR = Path.home() / ".claude" / "projects" / "-Users-liendallas-Desktop-Projects-SecureSkillHub" / "memory"
REGISTRY_FILE = MEMORY_DIR / "docm-file-registry.json"
AUDIT_LOG_FILE = MEMORY_DIR / "docm-audit-log.json"


def _load_registry() -> dict:
    """Load the file registry from disk."""
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 1, "files": {}}


def _save_registry(registry: dict) -> None:
    """Write the file registry to disk."""
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def register_file(
    path: str,
    brief: str,
    owner: str = "unknown",
    category: str = "other",
) -> None:
    """Register a new file in the DocM registry.

    Args:
        path: Relative path from project root (e.g. "src/build/build_json.py")
        brief: One-line description of the file's purpose
        owner: Which role/workstream owns this file
        category: File category (role, script, source, doc, config, data, site, ci)
    """
    registry = _load_registry()
    registry["files"][path] = {
        "brief": brief,
        "owner": owner,
        "category": category,
        "registered_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_registry(registry)
    log_to_docm("register", {"path": path, "brief": brief, "owner": owner})


def move_file(old_path: str, new_path: str, reason: str = "") -> None:
    """Record a file move in the registry. Updates the path key.

    Args:
        old_path: Previous relative path
        new_path: New relative path
        reason: Why the file was moved
    """
    registry = _load_registry()
    entry = registry["files"].pop(old_path, None)
    if entry:
        entry["moved_from"] = old_path
        entry["moved_at"] = datetime.now(timezone.utc).isoformat()
        registry["files"][new_path] = entry
    else:
        registry["files"][new_path] = {
            "brief": f"Moved from {old_path}",
            "owner": "unknown",
            "category": "other",
            "moved_from": old_path,
            "moved_at": datetime.now(timezone.utc).isoformat(),
        }
    _save_registry(registry)
    log_to_docm("move", {"old_path": old_path, "new_path": new_path, "reason": reason})


def remove_file(path: str, reason: str = "") -> None:
    """Remove a file from the registry.

    Args:
        path: Relative path to remove
        reason: Why the file was removed
    """
    registry = _load_registry()
    removed = registry["files"].pop(path, None)
    _save_registry(registry)
    log_to_docm("remove", {"path": path, "had_entry": removed is not None, "reason": reason})


def validate_registry() -> dict:
    """Validate that all registered files actually exist on disk.

    Returns:
        {"total": int, "valid": int, "missing": list[str], "extra": list[str]}
        - missing: registered but not on disk
        - extra: on disk but not registered (checks key project files only)
    """
    project_root = Path(__file__).resolve().parent.parent
    registry = _load_registry()

    total = len(registry["files"])
    missing = []
    valid = 0

    for path in registry["files"]:
        full_path = project_root / path
        if full_path.exists():
            valid += 1
        else:
            missing.append(path)

    return {
        "total": total,
        "valid": valid,
        "missing": missing,
    }


def log_to_docm(action: str, details: dict) -> None:
    """Append an entry to the DocM audit log.

    Args:
        action: One of "register", "move", "remove", "validate"
        details: Action-specific details dict
    """
    log_data = {"version": 1, "entries": []}
    if AUDIT_LOG_FILE.exists():
        try:
            log_data = json.loads(AUDIT_LOG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log_data = {"version": 1, "entries": []}

    log_data.setdefault("entries", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details,
    })

    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_LOG_FILE.write_text(
        json.dumps(log_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def get_file_info(path: str) -> dict | None:
    """Look up a file's registry entry.

    Args:
        path: Relative path from project root

    Returns:
        Registry entry dict or None if not registered
    """
    registry = _load_registry()
    return registry["files"].get(path)


def list_files(category: str | None = None, owner: str | None = None) -> dict[str, dict]:
    """List registered files, optionally filtered.

    Args:
        category: Filter by category (role, script, source, doc, config, data, site, ci)
        owner: Filter by owner (PM, SM, VM, SecM, DocM, AXM, DeployM, FrontendM, WS1-WS8)

    Returns:
        Dict of path -> entry for matching files
    """
    registry = _load_registry()
    files = registry["files"]

    if category:
        files = {k: v for k, v in files.items() if v.get("category") == category}
    if owner:
        files = {k: v for k, v in files.items() if v.get("owner") == owner}

    return files
