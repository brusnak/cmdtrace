#!/usr/bin/env python3
#
# Bret Rusnak
# September 2026
#
# cmdtrace external detector: shell command history changes.
#
# The detector tracks common shell history files and installs a lightweight
# shell hook that asks supported shells to flush their in-memory history to the
# configured history file at each prompt.  This makes commands entered during a
#cmdtrace session visible without requiring the user to remember ``history -a``.

# Important limitation: an external cmdtrace process cannot modify the already-
# running parent shell's environment.  The hook is therefore installed into the
# user's shell startup file and becomes active in the current shell only if that
# shell subsequently sources the startup file (normally on the next shell
# launch).  The detector reports this state once so the limitation is visible.
#
# This is not an audit/provenance mechanism. Shell history can be disabled,
# delayed, rewritten, deduplicated, or manually modified.
#
# ==============================================================================

from pathlib import Path
import hashlib
import json
import os
import re
import shlex

from cmdtrace import BaseDetector, SENSITIVE_ENV_NAME_PATTERN

HOME_ROOTS = (Path("/root"), Path("/home"))
HISTORY_NAMES = (".bash_history", ".zsh_history", ".ksh_history", ".fish_history")
HOOK_MARKER = "# >>> cmdtrace command-history hook >>>"
HOOK_END_MARKER = "# <<< cmdtrace command-history hook <<<"
HOOK_STATE_DIR = Path.home() / ".config" / "cmdtrace"
HOOK_STATE_FILE = HOOK_STATE_DIR / "command_history_hook.json"

# Common command-line forms where a following token is likely to contain a
# secret. The variable-name pattern remains the primary heuristic.
SENSITIVE_OPTION_PATTERN = re.compile(
    r"^(?:--?|/)?(?:password|passwd|pass|pwd|token|secret|credential|cred|username|user|api[-_]?key|access[-_]?key|private[-_]?key|client[-_]?secret)(?:=|$)",
    re.IGNORECASE,
)
# Common short-option conventions used by database, API, and administration
# tools.  These are intentionally explicit rather than treating every short
# option as sensitive (for example, -P often means password in custom tools,
# while other programs may use it for a non-secret value).
SHORT_USERNAME_OPTION = re.compile(r"^-(?:U|u)(?:$|.+)")
SHORT_PASSWORD_OPTION = re.compile(r"^-(?:P|p)(?:$|.+)")
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
AWS_ACCESS_KEY_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
AUTH_HEADER_PATTERN = re.compile(r"(?i)(\bAuthorization\s*:\s*(?:Bearer|Basic)\s+)[^\s\"']+")
REDACTED = "**redacted**"


class CommandHistoryDetector(BaseDetector):
    key = "module.command_history"
    name = "User Command History"
    description = "Tracks shell history changes and displays sanitized command text"

    # ------------------------------------------------------------------
    # Shell hook support
    # ------------------------------------------------------------------

    @staticmethod
    def _shell_name() -> str:
        shell = os.environ.get("SHELL", "")
        return Path(shell).name.lower() if shell else ""

    @classmethod
    def _startup_file(cls) -> Path | None:
        shell = cls._shell_name()
        home = Path.home()
        if shell == "bash":
            return home / ".bashrc"
        if shell == "zsh":
            return home / ".zshrc"
        # We intentionally don't edit arbitrary shell startup files. The
        # history-file detector still works for ksh/fish where supported.
        return None

    @classmethod
    def _hook_text(cls) -> str:
        shell = cls._shell_name()
        if shell == "bash":
            return f'''{HOOK_MARKER}
# Flush Bash history before the next prompt so cmdtrace can see recent commands.
__cmdtrace_history_flush() {{
    builtin history -a 2>/dev/null
}}
case ";${{PROMPT_COMMAND:-}};" in
    *";__cmdtrace_history_flush;"*) ;;
    *) PROMPT_COMMAND="${{PROMPT_COMMAND:+$PROMPT_COMMAND; }}__cmdtrace_history_flush" ;;
esac
{HOOK_END_MARKER}
'''
        if shell == "zsh":
            return f'''{HOOK_MARKER}
# Flush zsh history before the next prompt so cmdtrace can see recent commands.
if [[ -z "${{precmd_functions[(r)__cmdtrace_history_flush]}}" ]]; then
    function __cmdtrace_history_flush() {{ fc -AI 2>/dev/null }}
    precmd_functions+=(__cmdtrace_history_flush)
fi
{HOOK_END_MARKER}
'''
        return ""

    @classmethod
    def _install_shell_hook(cls) -> dict:
        """Install the hook once and return status information.

        The operation is deliberately idempotent and only edits the user's
        own startup file. Existing content is preserved.
        """
        startup = cls._startup_file()
        shell = cls._shell_name()
        result = {
            "shell": shell or "unknown",
            "startup_file": str(startup) if startup else None,
            "supported": bool(startup),
            "installed": False,
            "already_present": False,
            "warning": None,
        }

        if startup is None:
            result["warning"] = (
                "Shell hook is not supported for the current shell; "
                "history-file tracking remains enabled."
            )
            return result

        hook = cls._hook_text()
        try:
            startup.parent.mkdir(parents=True, exist_ok=True)
            existing = startup.read_text(encoding="utf-8", errors="replace") if startup.exists() else ""
        except OSError as exc:
            result["warning"] = f"Unable to inspect {startup}: {exc}"
            return result

        if HOOK_MARKER in existing and HOOK_END_MARKER in existing:
            result["already_present"] = True
            return result

        try:
            # Preserve the user's file exactly and append our isolated block.
            prefix = "" if not existing or existing.endswith("\n") else "\n"
            with startup.open("a", encoding="utf-8") as fh:
                fh.write(prefix + "\n" + hook)
        except OSError as exc:
            result["warning"] = f"Unable to install shell hook in {startup}: {exc}"
            return result

        result["installed"] = True
        result["warning"] = (
            f"Installed cmdtrace shell history hook in {startup}. "
            "It will become active when this shell next sources its startup file."
            "Please stop cmdtrace, restart your shell, and then re-run cmdtrace to capture history changes."
        )
        return result

    @classmethod
    def _save_hook_state(cls, status: dict) -> None:
        try:
            HOOK_STATE_DIR.mkdir(parents=True, exist_ok=True)
            HOOK_STATE_FILE.write_text(
                json.dumps(status, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    @classmethod
    def _ensure_shell_hook(cls) -> dict:
        """Verify/install the shell hook without warning on normal repeats."""
        status = cls._install_shell_hook()
        cls._save_hook_state(status)
        return status

    # ------------------------------------------------------------------
    # History discovery and collection
    # ------------------------------------------------------------------

    def _history_files(self) -> list[Path]:
        files = set()

        for root in HOME_ROOTS:
            if not root.exists():
                continue
            try:
                homes = [root] if root == Path("/root") else [p for p in root.iterdir() if p.is_dir()]
            except OSError:
                continue

            for home in homes:
                for name in HISTORY_NAMES:
                    path = home / name
                    try:
                        # Include known paths even when they don't exist yet so
                        # creation during a trace is detectable.
                        if path.is_file() or path.exists() is False:
                            files.add(path)
                    except OSError:
                        pass

        # Add the current user's HISTFILE when it is explicitly configured.
        histfile = os.environ.get("HISTFILE", "").strip()
        if histfile:
            try:
                files.add(Path(os.path.expandvars(os.path.expanduser(histfile))).resolve())
            except OSError:
                files.add(Path(os.path.expandvars(os.path.expanduser(histfile))))

        return sorted(files, key=str)

    @staticmethod
    def _read_history(path: Path) -> list[str]:
        try:
            if not path.is_file():
                return []
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, UnicodeError):
            return []

    # ------------------------------------------------------------------
    # Sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def _redact_sensitive_assignments(command: str) -> str:
        assignment = re.compile(
            rf"(?P<name>[A-Za-z_][A-Za-z0-9_-]*?(?:{SENSITIVE_ENV_NAME_PATTERN.pattern[1:-1]}))"
            rf"(?P<sep>\s*=\s*)"
            rf"(?P<value>[^\s;&|]+)",
            re.IGNORECASE,
        )
        command = assignment.sub(lambda m: f"{m.group('name')}{m.group('sep')}{REDACTED}", command)

        option_assignment = re.compile(
            r"(?P<option>--?[A-Za-z0-9_-]*(?:password|passwd|pass|pwd|token|secret|credential|cred|username|user|api[-_]?key|access[-_]?key|private[-_]?key|client[-_]?secret)[A-Za-z0-9_-]*)"
            r"\s*=\s*(?P<value>[^\s;&|]+)",
            re.IGNORECASE,
        )
        return option_assignment.sub(lambda m: f"{m.group('option')}={REDACTED}", command)

    @classmethod
    def _sanitize_command(cls, command: str) -> str:
        if not command:
            return command

        sanitized = PRIVATE_KEY_PATTERN.sub(REDACTED, command)
        sanitized = JWT_PATTERN.sub(REDACTED, sanitized)
        sanitized = AWS_ACCESS_KEY_PATTERN.sub(REDACTED, sanitized)
        sanitized = AUTH_HEADER_PATTERN.sub(r"\1" + REDACTED, sanitized)
        sanitized = cls._redact_sensitive_assignments(sanitized)

        try:
            tokens = shlex.split(sanitized, posix=True)
        except ValueError:
            tokens = None

        if tokens is None:
            return sanitized

        output = []
        redact_next = False
        for token in tokens:
            if redact_next:
                output.append(REDACTED)
                redact_next = False
                continue

            # Explicitly support the common ``-U <username> -P <password>``
            # convention, including attached forms such as ``-Ualice`` and
            # ``-Psecret`` (and the common lowercase ``-u`` / ``-p`` forms).  Both the option and its value are preserved only
            # as the option name plus a redaction marker.
            if SHORT_USERNAME_OPTION.match(token):
                option = token[:2]
                if token == option:
                    output.append(token)
                    redact_next = True
                else:
                    output.append(f"{option}{REDACTED}")
                continue

            if SHORT_PASSWORD_OPTION.match(token):
                option = token[:2]
                if token == option:
                    output.append(token)
                    redact_next = True
                else:
                    output.append(f"{option}{REDACTED}")
                continue

            if SENSITIVE_OPTION_PATTERN.match(token):
                if "=" in token:
                    option, _ = token.split("=", 1)
                    output.append(f"{option}={REDACTED}")
                else:
                    output.append(token)
                    redact_next = True
                continue

            if (
                re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token)
                and SENSITIVE_ENV_NAME_PATTERN.search(token)
            ):
                output.append(token)
                redact_next = True
                continue

            if "=" in token:
                name, _ = token.split("=", 1)
                if SENSITIVE_ENV_NAME_PATTERN.search(name):
                    output.append(f"{name}={REDACTED}")
                    continue

            output.append(token)

        if any(ch in sanitized for ch in ("|", ";", "&&", "||", ">", "<", "$(", "`")):
            return cls._redact_sensitive_assignments(sanitized)

        return " ".join(output)

    @staticmethod
    def _fingerprint_command(command: str) -> str:
        return hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest()

    def collect(self) -> dict:
        # Verify the hook every collection. A normal repeat is silent; the
        # status is included in the snapshot for diagnostics.
        hook_status = self._ensure_shell_hook()
        if hook_status.get("installed"):
            print(
                "CMDTRACE: User command history hook installed in "
                f"{hook_status.get('startup_file')}. "
                "It will become active when this shell next loads its startup file."
            )

        histories = {}
        for path in self._history_files():
            commands = self._read_history(path)
            sanitized_commands = [self._sanitize_command(command) for command in commands]
            try:
                stat = path.stat()
                exists = True
                size, mtime_ns = stat.st_size, stat.st_mtime_ns
            except OSError:
                exists = False
                size = mtime_ns = 0

            histories[str(path)] = {
                "exists": exists,
                "size": size,
                "mtime_ns": mtime_ns,
                "entry_count": len(sanitized_commands),
                "entries": sanitized_commands,
            }

        return {"histories": histories, "hook": hook_status}

    @staticmethod
    def _entry_diff(start_entries: list[str], stop_entries: list[str]) -> tuple[list[str], list[str]]:
        if len(stop_entries) >= len(start_entries) and stop_entries[:len(start_entries)] == start_entries:
            return stop_entries[len(start_entries):], []

        remaining = list(start_entries)
        added = []
        for item in stop_entries:
            try:
                remaining.remove(item)
            except ValueError:
                added.append(item)
        return added, remaining

    def diff(self, start: dict, stop: dict, meta_start: dict, meta_stop: dict) -> dict:
        start_histories = start.get("histories", {})
        stop_histories = stop.get("histories", {})
        changes = {}

        for path in sorted(set(start_histories) | set(stop_histories)):
            before = start_histories.get(path)
            after = stop_histories.get(path)

            if before is None:
                entries = after.get("entries", [])
                changes[path] = {
                    "created": True, "deleted": False, "changed": True,
                    "entries_added": len(entries), "entries_removed": 0,
                    "added_entries": entries, "removed_entries": [],
                    "before_count": 0, "after_count": len(entries),
                }
                continue

            if after is None:
                entries = before.get("entries", [])
                changes[path] = {
                    "created": False, "deleted": True, "changed": True,
                    "entries_added": 0, "entries_removed": len(entries),
                    "added_entries": [], "removed_entries": entries,
                    "before_count": len(entries), "after_count": 0,
                }
                continue

            start_entries = before.get("entries", [])
            stop_entries = after.get("entries", [])
            added, removed = self._entry_diff(start_entries, stop_entries)
            changed = (
                start_entries != stop_entries
                or before.get("size") != after.get("size")
                or before.get("mtime_ns") != after.get("mtime_ns")
            )

            changes[path] = {
                "created": False, "deleted": False, "changed": changed,
                "entries_added": len(added), "entries_removed": len(removed),
                "added_entries": added, "removed_entries": removed,
                "before_count": len(start_entries), "after_count": len(stop_entries),
            }

        return {
            "changed": any(c.get("changed", False) for c in changes.values()),
            "histories": changes,
            "hook": stop.get("hook", start.get("hook", {})),
        }

    def has_changes(self, diff_data: dict) -> bool:
        return bool(diff_data.get("changed", False))

    def render(self, diff_data: dict) -> None:
        if not self.has_changes(diff_data):
            return

        print("USER COMMAND HISTORY")
        for path, change in diff_data.get("histories", {}).items():
            if not change.get("changed"):
                continue

            if change.get("created"):
                print(f"  + History file created: {path} ({change['after_count']} entries)")
                for command in change.get("added_entries", []):
                    print(f"    + {command}")
                print()
                continue

            if change.get("deleted"):
                print(f"  - History file deleted: {path} ({change['before_count']} entries)")
                continue

            print(f"  ~ Changed: {path}")
            print(f"    Entries: {change['before_count']} → {change['after_count']}")
            for command in change.get("added_entries", []):
                print(f"    + {command}")
            for command in change.get("removed_entries", []):
                print(f"    - {command}")
            if change.get("entries_added") == 0 and change.get("entries_removed") == 0:
                print("    History metadata changed without an entry-content change")
            print()
        print()

    def summary_metrics(self, diff_data: dict) -> dict:
        histories = diff_data.get("histories", {})
        return {
            "Command History Files Changed": sum(1 for c in histories.values() if c.get("changed", False)),
            "Command History Entries Added": sum(c.get("entries_added", 0) for c in histories.values()),
            "Command History Entries Removed": sum(c.get("entries_removed", 0) for c in histories.values()),
        }
