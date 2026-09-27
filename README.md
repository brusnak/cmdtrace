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
- Runs as a single Python script with no third-party Python dependencies

---

## How It Works

A normal tracing session has two complementary mechanisms.

### 1. Start/stop state comparison

When `cmdtrace start` runs, cmdtrace captures a baseline snapshot of the system.

When `cmdtrace stop` runs, it captures the ending state and compares the two snapshots.

This detects changes such as:

- Packages installed or removed
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
git clone https://github.com/<your-user>/cmdtrace.git
cd cmdtrace
chmod +x cmdtrace.py
```

Optionally place it somewhere in your `PATH`:

```bash
sudo cp cmdtrace.py /usr/local/bin/cmdtrace
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

If real-time enforcement is needed in the future, that would be a separate feature with different semantics, such as configurable rules for which events should cause an operation to be terminated.

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
| Software Packages | `dpkg` or `rpm` inventory |
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

# Filesystem Monitoring Architecture

The filesystem functionality intentionally uses two complementary mechanisms.

```text
                    cmdtrace start
                         |
              +----------+----------+
              |                     |
        State Snapshot       inotify Monitor
              |                     |
              |              filesystem events
              |                     |
              |                     v
              |              event JSONL log
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
***REDACTED***
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
