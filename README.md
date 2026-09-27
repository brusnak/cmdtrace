# cmdtrace

**cmdtrace** is a Linux system change tracking and troubleshooting tool that captures system state before and after an operation and produces a consolidated change report.

It is designed to answer two related questions:

1. **What changed between the beginning and end of a session?**
2. **What filesystem activity happened during the session?**

The second capability is provided by a native Linux `inotify` filesystem event timeline, allowing cmdtrace to see intermediate filesystem activity that a simple before/after snapshot cannot.

---

## Features

- Full system-state snapshots before and after an operation
- Chronological filesystem activity timeline during tracing
- Named sessions for concurrent traces
- Automatic command tracing with `cmdtrace run`
- Saved "golden" baselines for drift/compliance comparisons
- Persistent filesystem watch directories
- Persistent filesystem ignore patterns
- Human-readable reports
- JSON report export
- Optional CI/automation change gate with `--fail-on-change`
- Persistent session history
- Sensitive environment-variable value redaction
- Modular detector architecture
- Pluggable filesystem event collector architecture with a default Python `inotify` backend and an optional native backend
- Runs as a single Python script with no third-party Python dependencies

---

## How It Works

A normal tracing session has two complementary mechanisms.

### 1. Start/stop state comparison

When `cmdtrace start` runs, cmdtrace captures a baseline snapshot of the system.

When `cmdtrace stop` runs, it captures the ending state and compares the two snapshots.

This detects changes such as:

- Packages installed, removed, or updated
- Users and groups added or removed
- Firewall changes
- Services changed
- Network configuration changes
- Processes started
- Listening ports changed
- Files created, modified, deleted, or changed in ownership/permissions
- And other tracked subsystem changes

### 2. Filesystem event timeline

At the same time the tracing session starts, cmdtrace launches a detached Linux `inotify` monitor.

During the session it records filesystem events such as:

- `CREATED`
- `DELETED`
- `PERMISSIONS_CHANGED`
- `OWNERSHIP_CHANGED`
- `METADATA_CHANGED`
- `CONTENT_WRITE`
- `MOVED_FROM`
- `MOVED_TO`

The resulting timeline is included in the final report.

For example:

```text
FILESYSTEM ACTIVITY TIMELINE
  14:32:01  CREATED             /etc/example.conf — mode=0o644 uid=0 gid=0
  14:32:01  PERMISSIONS_CHANGED /etc/example.conf — mode 0o644 → 0o600
  14:32:02  CONTENT_WRITE       /etc/example.conf
  14:32:03  PERMISSIONS_CHANGED /etc/example.conf — mode 0o600 → 0o644
```

This solves an important limitation of a pure snapshot model: a file can be created and then changed several times before `cmdtrace stop` is run.

---

## Requirements

- Linux
- Python 3
- Linux `inotify` support
- Appropriate permissions to inspect the system areas being monitored

For comprehensive system inspection, run cmdtrace with `sudo` or as root.

Example:

```bash
sudo ./cmdtrace help
```

Without root privileges, cmdtrace can still run, but access to some system information will be limited.

No third-party Python packages are required.

---

## Installation

Clone the repository and make the script executable:

```bash
git clone https://github.com/brusnak/cmdtrace.git
cd cmdtrace
chmod +x cmdtrace
```

Optionally place it somewhere in your `PATH`:

```bash
sudo cp cmdtrace /usr/local/bin/cmdtrace
sudo chmod +x /usr/local/bin/cmdtrace
```

Then:

```bash
cmdtrace help
```

Running the script with no arguments also displays the full help/manual:

```bash
cmdtrace
```

---

# Usage

## Interactive Start / Stop Session

Start a trace:

```bash
sudo cmdtrace start
```

Perform the operation you want to investigate:

```bash
sudo apt install nginx
```

Stop tracing:

```bash
sudo cmdtrace stop
```

cmdtrace captures the ending state, stops the filesystem event monitor, and generates the change report.

---

## Automatic Command Wrapper

For a single command, `run` automatically starts and stops the trace:

```bash
sudo cmdtrace run -- apt install -y nginx
```

Another example:

```bash
sudo cmdtrace run -- systemctl restart nginx
```

This is often the simplest way to investigate what a command changes.

---

# Named Sessions

Sessions can be given explicit names.

```bash
sudo cmdtrace start --session nginx_test
```

Later:

```bash
sudo cmdtrace stop --session nginx_test
```

Active sessions can be listed:

```bash
sudo cmdtrace sessions
```

Named sessions allow multiple traces to coexist rather than relying exclusively on the default session.

---

# Filesystem Watch Configuration

The filesystem detector and event timeline use a persistent list of watched directories.

List the current configuration:

```bash
sudo cmdtrace watch list
```

Add a directory:

```bash
sudo cmdtrace watch add /etc/nginx
```

Remove a directory:

```bash
sudo cmdtrace watch remove /var/www
```

The watch configuration is persistent across cmdtrace executions.

Default watched locations include:

```text
/etc
/usr/local/bin
/usr/local/sbin
/usr/local/etc
/opt
/root
/boot
/usr/lib/systemd/system
/var/www
```

---

# Filesystem Ignore Patterns

Some paths generate large amounts of expected activity. cmdtrace supports persistent glob-style ignore patterns.

List them:

```bash
sudo cmdtrace watch ignore list
```

Add an ignore pattern:

```bash
sudo cmdtrace watch ignore add "*.cache"
```

Or:

```bash
sudo cmdtrace watch ignore add "*/tmp/*"
```

Remove one:

```bash
sudo cmdtrace watch ignore remove "*.cache"
```

Default ignored patterns include:

```text
*.log
*.tmp
*.swp
*/.git/*
*/__pycache__/*
*/node_modules/*
```

The ignore configuration is used by the filesystem monitoring components.

---

# Baselines

cmdtrace can save a known-good system state as a named baseline.

Create one:

```bash
sudo cmdtrace baseline save known_good
```

List saved baselines:

```bash
sudo cmdtrace baseline list
```

Compare the current live system against a baseline:

```bash
sudo cmdtrace compare known_good
```

Export the comparison:

```bash
sudo cmdtrace compare known_good \
    --export /var/log/cmdtrace/drift/ \
    --export-format both
```

Remove a baseline:

```bash
sudo cmdtrace baseline remove known_good
```

Baseline comparisons are point-in-time comparisons; they do not create a filesystem event timeline because there is no active start/stop tracing session.

---

# Report Export

Reports can be written to disk with `--export`.

Text report:

```bash
sudo cmdtrace stop --export /var/log/cmdtrace/report.txt
```

JSON report:

```bash
sudo cmdtrace stop \
    --export /var/log/cmdtrace/report.json \
    --export-format json
```

Both formats:

```bash
sudo cmdtrace stop \
    --export /var/log/cmdtrace/report \
    --export-format both
```

A directory can also be supplied:

```bash
sudo cmdtrace stop \
    --export /var/log/cmdtrace/ \
    --export-format both
```

In directory mode, cmdtrace generates timestamped filenames such as:

```text
cmdtrace_report_20260927_143201.txt
cmdtrace_report_20260927_143201.json
```

The same export options are available with `run` and `compare`.

---

# Automation / CI

## `--fail-on-change`

`--fail-on-change` is a **post-operation validation gate**. It does not stop a command at the moment a change occurs. Instead, cmdtrace lets the operation finish, performs its normal change detection, and then returns exit status `2` if a tracked change was found.

For example:

```bash
sudo cmdtrace run --fail-on-change -- ./deploy.sh
```

The sequence is:

```text
start tracing
     │
     ▼
run ./deploy.sh
     │
     │  system changes may occur here
     │
     ▼
stop tracing / collect final state
     │
     ▼
compare before vs. after
     │
     ├── no tracked changes ──► exit 0
     │
     └── changes detected ────► exit 2
```

This makes the option useful in CI/CD, deployment verification, and automated validation where the requirement is:

> **Run the operation, then fail the job if it left the system in a changed state.**

For example, a deployment script might be expected to make certain changes. If it unexpectedly changes another tracked subsystem, the cmdtrace step can return `2` and cause the surrounding pipeline to flag the operation.

### What it does not do

`--fail-on-change` is **not a real-time protection mechanism**. If a command creates a file, changes its permissions, and then deletes it during the operation, the final snapshot may not show that the file ever existed. The option therefore should not be interpreted as “terminate immediately when anything changes.”

The filesystem event timeline provides additional visibility into activity that occurred during the session, including intermediate events such as create, permission changes, writes, and deletes. That timeline is primarily for investigation and reporting; it is separate from the `--fail-on-change` exit-code gate.

### `--fail-on-change` with other commands

The option is available anywhere cmdtrace performs a change comparison:

```bash
# Automatic command tracing
sudo cmdtrace run --fail-on-change -- ./deploy.sh

# Start/stop tracing
sudo cmdtrace stop --fail-on-change

# Compare against a saved baseline
sudo cmdtrace compare known_good --fail-on-change
```

In all cases, the meaning is the same: **complete the comparison, then use the exit status to indicate whether tracked changes were detected.**

---

# History

cmdtrace maintains a persistent history log containing session summaries.

Normal tracing:

```bash
sudo cmdtrace stop
```

To suppress the history entry for a particular operation:

```bash
sudo cmdtrace stop --no-history
```

---

# Tracked Subsystems

cmdtrace uses modular detectors to inspect different areas of a Linux system.

The current script includes detectors covering:

| Area | Examples |
|---|---|
| Users, Groups & Auth | `/etc/passwd`, `/etc/group`, sudoers, SSH keys, SSH configuration, PAM |
| Kernel & Hardware | Loaded kernel modules |
| Execution Environment | `PATH`, environment variables, shell profiles |
| Scheduled Jobs | Cron and systemd timers |
| Firewall Rulesets | nftables, iptables, UFW, firewalld |
| Storage & Mounts | Mount information |
| Container Runtimes | Docker and Podman state |
| Network Identity & Routing | IP addresses, routes, hosts, resolver configuration |
| Software Packages | `dpkg` or `rpm` inventory | Install, Remove, Updates |
| Systemd Services & Dependencies | Service units and states |
| Process Activity | Processes, owners, PPIDs, open file descriptors |
| Network Ports & Sockets | TCP/UDP listeners |
| Filesystem Integrity | Content, size, timestamps, permissions, ownership |
| System Logs | Journal activity |
| Database Activity | MySQL-related state |

The exact detector registry and descriptions can always be viewed with:

```bash
cmdtrace help
```

---

# Modular Detector Architecture

cmdtrace includes its core detectors directly in the main script, while also supporting optional external detector modules.

This provides two layers:

```text
cmdtrace
   |
   +-- Built-in detectors
   |      Users/Auth
   |      Kernel/Hardware
   |      Packages
   |      Services
   |      Filesystem
   |      ...
   |
   +-- External detector modules
          /etc/cmdtrace/modules/*.py
```

Built-in detectors are always loaded first. External modules are then discovered from the configured module directory and added to the detector registry.

This allows site-specific or team-specific checks to be added without modifying the main cmdtrace script.

## Configuring the Module Path

The default external module directory is:

```text
/etc/cmdtrace/modules
```

The path can be changed with:

```bash
sudo cmdtrace set module path /etc/cmdtrace/modules
```

For example:

```bash
sudo cmdtrace set module path /opt/cmdtrace/modules
```

The configured path is stored in the cmdtrace configuration file and is used by future cmdtrace executions.

The directory does not have to exist when the path is configured. cmdtrace will save the configuration and warn if the directory is not currently available.

## Listing Detectors

Use:

```bash
cmdtrace modules
```

to display the built-in and externally loaded detectors.

The output identifies:

- Built-in detectors
- External detectors
- Detector names and descriptions
- The source path of external modules
- The configured module directory
- External module loading errors, if any

Built-in detectors are listed before external detectors.

## Building an External Detector

An external detector is a normal Python module containing a class derived from `BaseDetector`.

A minimal module looks like this:

```python
from pathlib import Path

from cmdtrace import BaseDetector, hash_file


TEST_FILE = Path("/var/tmp/cmdtrace_module_test.txt")


class MarkerFileDetector(BaseDetector):
    key = "example.marker_file"
    name = "Module Test File"
    description = "Example external module tracking /var/tmp/cmdtrace_module_test.txt"

    def collect(self) -> dict:
        return {
            "path": str(TEST_FILE),
            "exists": TEST_FILE.exists(),
            "sha256": hash_file(TEST_FILE),
        }

    def diff(self, start, stop, meta_start, meta_stop) -> dict:
        return {
            "created": not start.get("exists", False) and stop.get("exists", False),
            "deleted": start.get("exists", False) and not stop.get("exists", False),
            "content_changed": (
                start.get("exists", False)
                and stop.get("exists", False)
                and start.get("sha256", "") != stop.get("sha256", "")
            ),
        }

    def render(self, diff_data) -> None:
        if not any(diff_data.values()):
            return

        print("MODULE TEST FILE")

        if diff_data["created"]:
            print(f"  + Created: {TEST_FILE}")

        if diff_data["deleted"]:
            print(f"  - Deleted: {TEST_FILE}")

        if diff_data["content_changed"]:
            print(f"  ~ Content changed: {TEST_FILE}")

        print()

    def summary_metrics(self, diff_data) -> dict:
        return {
            "Module Test File Changes": int(any(diff_data.values()))
        }
```

The example above is also provided as:

```text
cmdtrace_example_module.py
```

The module demonstrates the basic detector API:

| Component | Purpose |
|---|---|
| `BaseDetector` | Base class for cmdtrace detectors |
| `key` | Optional stable identifier for the detector |
| `name` | Human-readable detector name |
| `description` | Description shown by `cmdtrace modules` |
| `collect()` | Captures detector-specific state |
| `diff()` | Compares beginning and ending state |
| `render()` | Adds human-readable changes to the report |
| `summary_metrics()` | Optional summary statistics |

`summary_metrics()` is optional. The other detector methods provide the core collection, comparison, and reporting behavior.

### Detector Keys

Built-in detectors retain their existing detector keys for compatibility.

External detectors should preferably define an explicit `key`, for example:

```python
key = "example.marker_file"
```

If an external detector does not define a key, cmdtrace automatically namespaces it using its Python module and class name. This prevents an external class from accidentally overwriting a built-in detector's snapshot/report data simply because it happens to use the same class name.

### External Module Loading Rules

External modules are loaded from the configured module directory:

- Only `.py` files are considered.
- Files beginning with `_` are ignored.
- External modules are loaded after all built-in detectors.
- External modules are loaded alphabetically by filename.
- A failure in one external module is reported as a warning and does not prevent the built-in detectors from running.
- Modules are loaded once per cmdtrace process.

This makes the built-in detector set reliable even when a site-specific module contains an error.

## Installing the Example Module

Create the module directory:

```bash
sudo mkdir -p /etc/cmdtrace/modules
```

Copy the example detector:

```bash
sudo cp cmdtrace_example_module.py /etc/cmdtrace/modules/
```

Configure the module path:

```bash
sudo cmdtrace set module path /etc/cmdtrace/modules
```

Verify that it loaded:

```bash
sudo cmdtrace modules
```

The example module tracks:

```text
/var/tmp/cmdtrace_module_test.txt
```

Test it with:

```bash
echo "before" | sudo tee /var/tmp/cmdtrace_module_test.txt
sudo cmdtrace start

echo "after" | sudo tee /var/tmp/cmdtrace_module_test.txt

sudo cmdtrace stop
```

The resulting report includes a module-specific section similar to:

```text
MODULE TEST FILE
  ~ Content changed: /var/tmp/cmdtrace_module_test.txt
```

and the summary can include:

```text
Module Test File Changes: 1
```

The example is intentionally simple. A production module could instead collect state from a site-specific configuration file, application, service, database, API, or other system resource that is not covered by the built-in detectors.

## Module Design Philosophy

The modular detector system is intentionally lightweight. External modules do not need to implement a separate plugin framework or install third-party Python packages.

A detector is responsible for:

1. Collecting its own state.
2. Comparing the start and stop state.
3. Rendering meaningful changes.
4. Optionally providing summary metrics.

The main cmdtrace application remains responsible for session management, snapshot persistence, report generation, history, and command-line behavior.

This keeps site-specific detection logic isolated while allowing all detectors to participate in the same start/stop comparison and reporting pipeline.

---

# Filesystem Monitoring Architecture

The filesystem functionality intentionally uses two complementary mechanisms.

```text
                    cmdtrace start
                         |
              +----------+----------+
              |                     |
        State Snapshot       Event Collector
              |                     |
              |              filesystem events
              |                     |
              |                     v
              |              JSONL event log
              |                     |
              +----------+----------+
                         |
                    cmdtrace stop
                         |
              +----------+----------+
              |                     |
       Ending Snapshot       Event Timeline
              |                     |
              +----------+----------+
                         |
                    Change Report
```

The snapshot comparison answers:

> What is different now compared with when tracing started?

The event timeline answers:

> What filesystem activity occurred while tracing was running?

Keeping both mechanisms avoids forcing one approach to do two different jobs.

## Event Collector Architecture

The collector layer is intentionally decoupled from the rest of the tool. The implementation now uses an abstract `EventCollector` interface, with the default backend provided by `PythonInotifyCollector` and an optional future/native backend represented by `NativeEventCollector`.

This means the session lifecycle, report generation, and detector logic do not depend on whether the event source is implemented in Python with `ctypes` and Linux `inotify` or in a standalone native executable later.

The current backend behavior is:

- `cmdtrace` selects the configured backend via `load_config().get("event_collector", "python-inotify")`
- the default collector is `python-inotify`
- a native collector can be configured with the `native_collector` config value or the `CMDTRACE_NATIVE_COLLECTOR` environment variable
- the collector starts as a detached subprocess with a per-session JSONL event file
- the collector writes JSON events to that file and emits a `MONITOR_STARTED` readiness marker before `cmdtrace` continues
- `cmdtrace` sends `SIGTERM` to the collector on stop, then reads back the normalized event stream and removes the temporary log

This keeps the event protocol stable across backends. A native collector only needs to honor the same lifecycle contract:

1. start with a session name and event-file path
2. write JSONL events to the file
3. emit a `MONITOR_STARTED` line after initialization
4. exit cleanly on `SIGTERM`

The normalized event stream is then consumed by the reporting layer the same way regardless of origin.

## Event Collector Configuration

The collector choice is controlled by the config file and environment:

```json
{
  "event_collector": "python-inotify",
  "native_collector": "/usr/local/bin/cmdtrace-native-collector"
}
```

Or with the environment variable:

```bash
export CMDTRACE_NATIVE_COLLECTOR=/usr/local/bin/cmdtrace-native-collector
```

When `event_collector` is set to `native`, cmdtrace will use the configured native executable. Otherwise it stays on the default Python `inotify` backend.

---

# Filesystem Event Limitations

The event timeline is based on Linux `inotify`.

`inotify` reports that filesystem events occurred, but it does not provide a complete historical record of every prior file state.

For example, if a file is changed extremely rapidly:

```bash
touch test.conf
chmod 600 test.conf
chmod 644 test.conf
chmod 600 test.conf
```

multiple operations may occur before cmdtrace can inspect the intermediate state. In those cases, the event timeline can record metadata activity without necessarily being able to reconstruct every exact intermediate permission value.

The start/stop snapshot comparison remains the authoritative final-state comparison.

For security-sensitive environments requiring syscall-level auditing or complete historical reconstruction, Linux audit facilities may be more appropriate than inotify.

---

# Sensitive Data Handling

Environment-variable values whose names appear sensitive are redacted before being written to snapshots, reports, or exports.

Names matching terms such as:

```text
KEY
TOKEN
SECRET
PASSWORD
PASSWD
CREDENTIAL
AUTH
PRIVATE
```

have their values replaced with:

```text
***REDACTED***(SHA-256 Hash)
```

This is name-based redaction, not a guarantee that every possible secret format will be detected.

---

# Persistent Files

The current implementation uses the following locations:

| Path | Purpose |
|---|---|
| `/etc/cmdtrace_config.json` | Persistent watch directories and ignore patterns |
| `/var/tmp/cmdtrace_snapshot_<session>.json` | Active session baseline snapshots |
| `/var/tmp/cmdtrace_events_<session>.jsonl` | Temporary filesystem event timeline |
| `/var/lib/cmdtrace/baselines/` | Saved baseline snapshots |
| `/var/log/cmdtrace/history.log` | Session history |

Filesystem event logs are consumed when a session stops and are removed afterward.

---

# Example Investigation

Suppose an installation script appears to modify several parts of a server.

Start tracing:

```bash
sudo cmdtrace start --session investigation
```

Run the installation:

```bash
sudo ./install.sh
```

Stop tracing:

```bash
sudo cmdtrace stop --session investigation \
    --export /var/log/cmdtrace/investigation \
    --export-format both
```

The report can then show both high-level subsystem changes and filesystem activity.

For example:

```text
FILESYSTEM UPDATES
  + Created: /etc/example/application.conf
  ~ Modified: /etc/example/application.conf
  ~ Permissions: /etc/example/application.conf (0o644 → 0o600)

FILESYSTEM ACTIVITY TIMELINE
  15:41:02  CREATED             /etc/example/application.conf
  15:41:02  PERMISSIONS_CHANGED /etc/example/application.conf — mode 0o644 → 0o600
  15:41:03  CONTENT_WRITE       /etc/example/application.conf
  15:41:03  CREATED             /etc/systemd/system/example.service
```

This makes it possible to see both the **final state** and the **sequence of filesystem activity**.

---

# Project Goals

cmdtrace is intended to be useful for:

- Linux troubleshooting
- Change investigation
- Configuration auditing
- Deployment verification
- Incident investigation
- System administration
- Change-control documentation
- Before/after testing of installation scripts
- CI/CD environment validation
- Understanding what an unfamiliar installer or maintenance script changes
- Extending system change detection with site-specific external detector modules

The design goal is to provide useful system visibility without requiring a large external monitoring stack.

---

# License

```text
GPL v3 License
```

---

# Author

**Bret Rusnak**

cmdtrace — Linux System Change Tracking and Troubleshooting Tool
