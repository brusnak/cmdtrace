#!/usr/bin/env python3
#
# example_module_template.py
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


#==========================================================================
# EXAMPLE MODULE: MODULE TEMPLATE
#==========================================================================

from cmdtrace import BaseDetector, run_cmd

class cmdtrace_module_name(BaseDetector):
    """Description of what this module tracks, shown in reports and --help output."""

    key = "example.template_file"
    name = "Module Template File"
    description = "Example Template Module"

    def collect(self) -> dict:
        return {

        }

    def diff(self) -> dict:
        return {
            
        }

    def render(self) -> None:
        
        print()

    def summary_metrics(self) -> dict:
        return {}
