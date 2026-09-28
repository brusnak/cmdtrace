"""cmdtrace update-alternatives/symlink external detector.

Bret Rusnak
September 2026

Monitors update-alternatives state changes and direct command symlink creations,
deletions, and target switches across standard PATH locations and /etc/alternatives.

Install into the configured cmdtrace external-module directory, for example:
    /etc/cmdtrace/modules/alternatives_detector.py
"""

from pathlib import Path
import os
import subprocess

from cmdtrace import BaseDetector


KEY = "system.alternatives"

SYMLINK_DIRS = [
    Path("/etc/alternatives"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/usr/local/sbin"),
    Path("/usr/sbin"),
    Path("/bin"),
    Path("/sbin"),
    Path("/tmp"),
]


def _run(cmd, timeout=5):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _get_monitored_dirs():
    """Builds a comprehensive set of target directories including system PATH."""
    dirs = {
        Path("/etc/alternatives"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/usr/local/sbin"),
        Path("/usr/sbin"),
        Path("/bin"),
        Path("/sbin"),
        Path("/tmp"),
    }
    
    # Add any directories defined in the environment PATH
    path_env = os.environ.get("PATH", "")
    for entry in path_env.split(os.pathsep):
        if entry:
            try:
                resolved = Path(entry).resolve()
                if resolved.is_dir():
                    dirs.add(resolved)
            except OSError:
                pass

    return sorted(dirs)


def _scan_symlinks():
    """Scans all monitored directories for active symlinks and their targets."""
    symlinks = {}
    for directory in _get_monitored_dirs():
        try:
            for entry in directory.iterdir():
                try:
                    # Catch all symlinks, even broken/dangling ones
                    if entry.is_symlink():
                        # Resolve relative path string representation cleanly
                        symlinks[str(entry.resolve())] = os.readlink(entry)
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            continue
    return symlinks


def _parse_alternatives_db():
    """Reads status files from /var/lib/dpkg/alternatives or /var/lib/alternatives."""
    db_dirs = [
        Path("/var/lib/dpkg/alternatives"),
        Path("/var/lib/alternatives"),
    ]
    info = {}

    for db_dir in db_dirs:
        if not db_dir.is_dir():
            continue
        try:
            for entry in db_dir.iterdir():
                if not entry.is_file():
                    continue
                name = entry.name
                lines = entry.read_text(errors="replace").splitlines()
                if len(lines) >= 2:
                    info[name] = {
                        "mode": lines[0].strip(),  # 'auto' or 'manual'
                        "master_link": lines[1].strip(),  # e.g. '/usr/bin/java'
                    }
        except (OSError, PermissionError):
            pass
    return info


def _collect_state():
    symlinks = _scan_symlinks()
    db_info = _parse_alternatives_db()

    return {
        "available": bool(symlinks or db_info or Path("/etc/alternatives").exists()),
        "symlinks": symlinks,
        "alternatives_db": db_info,
    }


class AlternativesDetector(BaseDetector):
    key = KEY
    name = "Update Alternatives & Command Symlinks"
    description = "Tracks update-alternatives mode changes, target switches, and command symlink creation/deletion"

    def collect(self) -> dict:
        return _collect_state()

    def diff(self, start: dict, stop: dict, meta_start: dict, meta_stop: dict) -> dict:
        links_a = start.get("symlinks", {})
        links_b = stop.get("symlinks", {})

        db_a = start.get("alternatives_db", {})
        db_b = stop.get("alternatives_db", {})

        # 1. Symlink level diff
        symlinks_created = [
            {"path": path, "target": links_b[path]}
            for path in sorted(links_b.keys() - links_a.keys())
        ]
        symlinks_removed = [
            {"path": path, "target": links_a[path]}
            for path in sorted(links_a.keys() - links_b.keys())
        ]
        symlinks_changed = [
            {"path": path, "before": links_a[path], "after": links_b[path]}
            for path in sorted(links_a.keys() & links_b.keys())
            if links_a[path] != links_b[path]
        ]

        # 2. update-alternatives DB mode diff (auto <-> manual)
        db_changed = []
        all_db_keys = set(db_a.keys()) | set(db_b.keys())
        for name in sorted(all_db_keys):
            a_item = db_a.get(name, {})
            b_item = db_b.get(name, {})
            if a_item.get("mode") != b_item.get("mode"):
                db_changed.append({
                    "name": name,
                    "master_link": b_item.get("master_link") or a_item.get("master_link", ""),
                    "before": a_item.get("mode", "unknown"),
                    "after": b_item.get("mode", "unknown"),
                })

        return {
            "available_changed": start.get("available") != stop.get("available"),
            "symlinks_created": symlinks_created,
            "symlinks_removed": symlinks_removed,
            "symlinks_changed": symlinks_changed,
            "db_mode_changed": db_changed,
        }

    def render(self, diff_data: dict) -> None:
        created = diff_data.get("symlinks_created", [])
        removed = diff_data.get("symlinks_removed", [])
        changed = diff_data.get("symlinks_changed", [])
        modes = diff_data.get("db_mode_changed", [])

        if not (created or removed or changed or modes or diff_data.get("available_changed")):
            return

        print("UPDATE ALTERNATIVES & COMMAND SYMLINKS")

        for item in created:
            print(f"    + Symlink created: {item['path']} → {item['target']}")

        for item in removed:
            print(f"    - Symlink removed: {item['path']} (was → {item['target']})")

        for item in changed:
            print(f"    ~ Symlink changed: {item['path']}: {item['before']} → {item['after']}")

        for item in modes:
            link_ctx = f" ({item['master_link']})" if item.get("master_link") else ""
            print(f"    ~ Alternative mode '{item['name']}'{link_ctx}: {item['before']} → {item['after']}")

        print()

    def summary_metrics(self, diff_data: dict) -> dict:
        created = diff_data.get("symlinks_created", [])
        removed = diff_data.get("symlinks_removed", [])
        changed = diff_data.get("symlinks_changed", [])
        modes = diff_data.get("db_mode_changed", [])
        return {
            "Symlinks Created": len(created),
            "Symlinks Removed": len(removed),
            "Symlinks Changed": len(changed),
            "Alternatives Mode Switches": len(modes),
        }