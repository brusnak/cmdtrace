#!/usr/bin/env python3
#
# time_sync_detector.py
#
# EXAMPLE external cmdtrace detector module.
#
# This file exists purely as a template/reference for writing your own
# external detector modules. It is not required for cmdtrace to function —
# copy it, rename the class, and rewrite collect()/diff()/render() for
# whatever you want to track.
#
# HOW EXTERNAL MODULES ARE LOADED
# --------------------------------
# 1. Point cmdtrace at a directory:      sudo cmdtrace set module path /etc/cmdtrace/modules.d
# 2. Copy this file into that directory: sudo cp time_sync_detector.py /etc/cmdtrace/modules.d/
# 3. Run cmdtrace normally. Every top-level *.py file in the module path
#    (except ones starting with "_") is loaded once at startup, alongside
#    the built-in detectors. There's nothing else to register — subclassing
#    cmdtrace.BaseDetector is enough.
# 4. Confirm it's active:                sudo cmdtrace modules
#
# THE CONTRACT
# ------------
# A detector class must:
#   - subclass cmdtrace.BaseDetector
#   - set `name` and `description` class attributes (shown in reports/help)
#   - implement collect(self), diff(self, start, stop, meta_start, meta_stop),
#     and render(self, diff_data)
# It may optionally override:
#   - summary_metrics(self, diff_data) -> dict of {label: number} shown in
#     the report's final SUMMARY box
#   - has_changes(self, diff_data) -> bool used by --fail-on-change; the
#     default (any truthy value in the diff dict) is usually fine
#
# `import cmdtrace` works here even though cmdtrace has no __init__.py and
# may not be on PYTHONPATH — cmdtrace registers itself under that name
# before loading any external module, specifically so this line works.
#
# SECURITY NOTE: this code runs with the same privileges as cmdtrace itself
# (typically root). Only put files here that you wrote or trust.

from cmdtrace import BaseDetector, run_cmd


class TimeSyncDetector(BaseDetector):
    key = "module.time_sync"
    name = "Time Synchronization (example module)"
    description = "Example external module: tracks NTP sync status and configured timezone via timedatectl"

    def collect(self) -> dict:
        """
        Capture live state into a JSON-serializable dict. Keep it flat and
        simple — this dict is what gets diffed between 'start' and 'stop'
        (or against a saved baseline).
        """
        output = run_cmd(["timedatectl", "show", "--property=NTPSynchronized,NTP,Timezone"])
        values = {}
        for line in output.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                values[key] = value

        return {
            "ntp_synchronized": values.get("NTPSynchronized", "unknown"),
            "ntp_enabled": values.get("NTP", "unknown"),
            "timezone": values.get("Timezone", "unknown"),
        }

    def diff(self, start: dict, stop: dict, meta_start: dict, meta_stop: dict) -> dict:
        """
        Compare the two collect() snapshots. Return whatever shape is
        convenient — render() and summary_metrics() below just need to
        agree on it. This also becomes the JSON export for this detector,
        so keep it JSON-serializable.
        """
        return {
            "sync_changed": start.get("ntp_synchronized") != stop.get("ntp_synchronized"),
            "ntp_toggle_changed": start.get("ntp_enabled") != stop.get("ntp_enabled"),
            "timezone_changed": start.get("timezone") != stop.get("timezone"),
            "before": {
                "synchronized": start.get("ntp_synchronized"),
                "ntp_enabled": start.get("ntp_enabled"),
                "timezone": start.get("timezone"),
            },
            "after": {
                "synchronized": stop.get("ntp_synchronized"),
                "ntp_enabled": stop.get("ntp_enabled"),
                "timezone": stop.get("timezone"),
            },
        }

    def has_changes(self, diff_data: dict) -> bool:
        """
        Explicitly identify which fields represent actual changes.
        Used by cmdtrace --fail-on-change.
        """
        return (
            diff_data.get("sync_changed", False)
            or diff_data.get("ntp_toggle_changed", False)
            or diff_data.get("timezone_changed", False)
        )

    def render(self, diff_data: dict) -> None:
        """
        Print a section to the report ONLY if something actually changed.
        This runs inside cmdtrace's report buffer, so plain print() is
        exactly right — no need to return a string.
        """
        if not self.has_changes(diff_data):
            return

        print("TIME SYNCHRONIZATION (example module)")

        before = diff_data["before"]
        after = diff_data["after"]

        if diff_data["sync_changed"]:
            print(
                f"  ~ NTP sync status changed: "
                f"{before['synchronized']} → {after['synchronized']}"
            )

        if diff_data["ntp_toggle_changed"]:
            print(
                f"  ~ NTP enabled/disabled: "
                f"{before['ntp_enabled']} → {after['ntp_enabled']}"
            )

        if diff_data["timezone_changed"]:
            print(
                f"  ~ Timezone changed: "
                f"{before['timezone']} → {after['timezone']}"
            )

        print()


    def summary_metrics(self, diff_data: dict) -> dict:
        """Optional: contributes a line to the report's final SUMMARY box."""
        total = sum([
            diff_data["sync_changed"],
            diff_data["ntp_toggle_changed"],
            diff_data["timezone_changed"],
        ])
        return {"Time Sync Changes": total}
