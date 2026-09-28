"""cmdtrace SELinux/AppArmor external detector.

Bret Rusnak
September 2026

Tracks the host's mandatory-access-control state without storing full policy
contents. The detector is intentionally tolerant of systems that have only
SELinux, only AppArmor, both, or neither.

Install into the configured cmdtrace external-module directory, for example:
    /etc/cmdtrace/modules/selinux_apparmor_detector.py
"""

from pathlib import Path
import glob
import hashlib
import json
import os
import subprocess

from cmdtrace import BaseDetector


KEY = "security.mandatory_access_control"
REDACTED = "<unreadable>"


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


def _sha256(path: Path) -> str:
    try:
        if not path.is_file():
            return ""
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ""


def _file_hashes(patterns):
    result = {}
    seen = set()
    for pattern in patterns:
        for raw in glob.glob(pattern):
            path = Path(raw)
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            digest = _sha256(path)
            result[str(path)] = digest if digest else REDACTED
    return dict(sorted(result.items()))


def _parse_kv_lines(text):
    values = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _selinux_state():
    state = {
        "available": False,
        "mode": "",
        "config_mode": "",
        "policy_type": "",
        "booleans": {},
        "config_hash": "",
        "config_exists": False,
    }

    enforce = _run(["getenforce"])
    sestatus = _run(["sestatus"])
    config = Path("/etc/selinux/config")

    if enforce or sestatus or config.exists() or Path("/sys/fs/selinux").exists():
        state["available"] = True

    if enforce:
        state["mode"] = enforce

    status = _parse_kv_lines(sestatus)
    state["policy_type"] = status.get("Loaded policy name", "")

    if config.is_file():
        state["config_exists"] = True
        state["config_hash"] = _sha256(config) or REDACTED
        for line in config.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip().upper()
            value = value.strip()
            if key == "SELINUX":
                state["config_mode"] = value
            elif key == "SELINUXTYPE":
                state["policy_type"] = value

    booleans = _run(["getsebool", "-a"], timeout=10)
    if booleans:
        state["booleans"] = {
            name: value
            for name, value in (
                line.split("-->", 1)
                for line in booleans.splitlines()
                if "-->" in line
            )
            for name, value in [(name.strip(), value.strip())]
        }

    return state


def _apparmor_state():
    state = {
        "available": False,
        "enabled": False,
        "profiles": {},
        "profile_files": {},
        "config_files": {},
    }

    status = _run(["aa-status"], timeout=10)
    parser = _run(["aa-status", "--parser"])
    aa_enabled = Path("/sys/module/apparmor").exists() or Path("/sys/kernel/security/apparmor").exists()
    config_dir = Path("/etc/apparmor.d")

    if status or parser or aa_enabled or config_dir.is_dir():
        state["available"] = True
    state["enabled"] = aa_enabled

    if status:
        current_section = ""
        for raw in status.splitlines():
            line = raw.strip()
            lower = line.lower()
            if lower.startswith("profiles are in enforce mode"):
                current_section = "enforce"
                continue
            if lower.startswith("profiles are in complain mode"):
                current_section = "complain"
                continue
            if lower.startswith("profiles are in kill mode"):
                current_section = "kill"
                continue
            if lower.startswith("processes are in enforce mode"):
                current_section = "process_enforce"
                continue
            if lower.startswith("processes are in complain mode"):
                current_section = "process_complain"
                continue
            if lower.startswith("processes are unconfined"):
                current_section = "process_unconfined"
                continue
            if not line or ":" in line:
                continue
            if current_section in {"enforce", "complain", "kill"}:
                state["profiles"][line] = current_section

    if config_dir.is_dir():
        state["profile_files"] = _file_hashes([
            str(config_dir / "*"),
            str(config_dir / "**" / "*"),
        ])

        state["config_files"] = _file_hashes([
            str(config_dir / "local" / "*"),
            str(config_dir / "tunables" / "*"),
        ])

    return state


def _map_changes(before, after):
    added = sorted(k for k in after if k not in before)
    removed = sorted(k for k in before if k not in after)
    changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    return added, removed, changed


def _dict_diff(before, after):
    added, removed, changed = _map_changes(before, after)
    return {
        "added": [{"name": k, "value": after[k]} for k in added],
        "removed": [{"name": k, "value": before[k]} for k in removed],
        "changed": [
            {"name": key, "before": before[key], "after": after[key]}
            for key in changed
        ],
    }


class SELinuxAppArmorDetector(BaseDetector):
    key = KEY
    name = "SELinux / AppArmor"
    description = "Tracks SELinux/AppArmor enforcement state, profiles, booleans, and policy configuration"

    def collect(self) -> dict:
        return {
            "selinux": _selinux_state(),
            "apparmor": _apparmor_state(),
        }

    def diff(self, start: dict, stop: dict, meta_start: dict, meta_stop: dict) -> dict:
        sel_a = start.get("selinux", {})
        sel_b = stop.get("selinux", {})
        aa_a = start.get("apparmor", {})
        aa_b = stop.get("apparmor", {})

        sel_booleans = _dict_diff(sel_a.get("booleans", {}), sel_b.get("booleans", {}))
        aa_profiles = _dict_diff(aa_a.get("profiles", {}), aa_b.get("profiles", {}))

        return {
            "selinux_available_changed": sel_a.get("available") != sel_b.get("available"),
            "selinux_mode_changed": (
                sel_a.get("mode") != sel_b.get("mode")
                or sel_a.get("config_mode") != sel_b.get("config_mode")
            ),
            "selinux_mode_before": sel_a.get("mode", ""),
            "selinux_mode_after": sel_b.get("mode", ""),
            "selinux_config_mode_before": sel_a.get("config_mode", ""),
            "selinux_config_mode_after": sel_b.get("config_mode", ""),
            "selinux_policy_changed": sel_a.get("policy_type") != sel_b.get("policy_type"),
            "selinux_policy_type_before": sel_a.get("policy_type", ""),
            "selinux_policy_type_after": sel_b.get("policy_type", ""),
            "selinux_booleans": sel_booleans,
            "selinux_config_changed": sel_a.get("config_hash") != sel_b.get("config_hash"),
            "apparmor_available_changed": aa_a.get("available") != aa_b.get("available"),
            "apparmor_enabled_changed": aa_a.get("enabled") != aa_b.get("enabled"),
            "apparmor_enabled_before": aa_a.get("enabled"),
            "apparmor_enabled_after": aa_b.get("enabled"),
            "apparmor_profiles": aa_profiles,
            "apparmor_profile_files_changed": aa_a.get("profile_files", {}) != aa_b.get("profile_files", {}),
            "apparmor_config_files_changed": aa_a.get("config_files", {}) != aa_b.get("config_files", {}),
        }

    def render(self, diff_data: dict) -> None:
        sel_boolean = diff_data.get("selinux_booleans", {})
        aa_profiles = diff_data.get("apparmor_profiles", {})

        sel_added = sel_boolean.get("added", [])
        sel_removed = sel_boolean.get("removed", [])
        sel_changed = sel_boolean.get("changed", [])

        aa_added = aa_profiles.get("added", [])
        aa_removed = aa_profiles.get("removed", [])
        aa_changed = aa_profiles.get("changed", [])

        has_selinux_changes = (
            diff_data.get("selinux_mode_changed")
            or diff_data.get("selinux_policy_changed")
            or diff_data.get("selinux_config_changed")
            or bool(sel_added or sel_removed or sel_changed)
        )

        has_apparmor_changes = (
            diff_data.get("apparmor_available_changed")
            or diff_data.get("apparmor_enabled_changed")
            or diff_data.get("apparmor_profile_files_changed")
            or diff_data.get("apparmor_config_files_changed")
            or bool(aa_added or aa_removed or aa_changed)
        )

        if not (has_selinux_changes or has_apparmor_changes):
            return

        print("MANDATORY ACCESS CONTROL")

        if has_selinux_changes:
            print("  SELinux:")

            if diff_data.get("selinux_mode_changed"):
                print(
                    f"    ~ Enforcement mode: "
                    f"{diff_data.get('selinux_mode_before') or 'unknown'} → "
                    f"{diff_data.get('selinux_mode_after') or 'unknown'}"
                )
                if diff_data.get("selinux_config_mode_before") != diff_data.get("selinux_config_mode_after"):
                    print(
                        f"    ~ Persistent mode: "
                        f"{diff_data.get('selinux_config_mode_before') or 'unknown'} → "
                        f"{diff_data.get('selinux_config_mode_after') or 'unknown'}"
                    )

            if diff_data.get("selinux_policy_changed"):
                print(
                    f"    ~ Policy type: "
                    f"{diff_data.get('selinux_policy_type_before') or 'previous'} → "
                    f"{diff_data.get('selinux_policy_type_after') or 'current'}"
                )

            for item in sel_added:
                print(f"    + Boolean added: {item['name']} = {item['value']}")
            for item in sel_removed:
                print(f"    - Boolean removed: {item['name']} (was {item['value']})")
            for item in sel_changed:
                print(f"    ~ Boolean: {item['name']}: {item['before']} → {item['after']}")

            if diff_data.get("selinux_config_changed"):
                print("    ~ /etc/selinux/config changed")

        if has_apparmor_changes:
            print("  AppArmor:")

            if diff_data.get("apparmor_enabled_changed"):
                before_str = "enabled" if diff_data.get("apparmor_enabled_before") else "disabled"
                after_str = "enabled" if diff_data.get("apparmor_enabled_after") else "disabled"
                print(f"    ~ Status: {before_str} → {after_str}")

            for item in aa_added:
                print(f"    + Profile loaded: {item['name']} ({item['value']})")
            for item in aa_removed:
                print(f"    - Profile unloaded: {item['name']} (was {item['value']})")
            for item in aa_changed:
                print(f"    ~ Profile: {item['name']}: {item['before']} → {item['after']}")

            if diff_data.get("apparmor_profile_files_changed"):
                print("    ~ /etc/apparmor.d profile/configuration files changed")
            if diff_data.get("apparmor_config_files_changed"):
                print("    ~ AppArmor local/tunable configuration changed")
            if diff_data.get("apparmor_available_changed"):
                print("    ~ AppArmor availability changed")

        print()

    def summary_metrics(self, diff_data: dict) -> dict:
        booleans = diff_data.get("selinux_booleans", {})
        profiles = diff_data.get("apparmor_profiles", {})
        bool_added = booleans.get("added", [])
        bool_removed = booleans.get("removed", [])
        bool_changed = booleans.get("changed", [])
        prof_added = profiles.get("added", [])
        prof_removed = profiles.get("removed", [])
        prof_changed = profiles.get("changed", [])
        return {
            "SELinux Changes": int(
                diff_data.get("selinux_mode_changed", False)
                or diff_data.get("selinux_policy_changed", False)
                or diff_data.get("selinux_config_changed", False)
                or bool(bool_added or bool_removed or bool_changed)
            ),
            "SELinux Boolean Changes": len(bool_added) + len(bool_removed) + len(bool_changed),
            "AppArmor Profile Changes": len(prof_added) + len(prof_removed) + len(prof_changed),
            "AppArmor Config Changes": int(
                diff_data.get("apparmor_profile_files_changed", False)
                or diff_data.get("apparmor_config_files_changed", False)
            ),
        }