#!/usr/bin/env python3
"""Track live agent sessions across sibling checkouts on this machine, keyed by checkout root."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOSTS = ("claude", "codex", "cursor")
SAFE_ID = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")
DEFAULT_STALE_SECONDS = 24 * 60 * 60
MAX_CONTEXT_LENGTH = 8_000
MUTATION_LOCK_TIMEOUT_SECONDS = 1.0
MUTATION_LOCK_RETRY_SECONDS = 0.02
ABANDONED_LOCK_GRACE_SECONDS = 2.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def detect_host(payload: dict[str, Any], fallback: str = "claude") -> str:
    if payload.get("cursor_version"):
        return "cursor"
    if payload.get("turn_id"):
        return "codex"
    return fallback


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        return {}
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def safe_identifier(value: Any) -> str:
    identifier = str(value or "")
    if SAFE_ID.match(identifier):
        return identifier
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]


def conversation_key(host: str, payload: dict[str, Any]) -> str | None:
    identifier = payload.get("conversation_id") or payload.get("session_id")
    if not identifier:
        return None
    return f"{host}-{safe_identifier(identifier)}"


def is_subagent(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("agent_id")
        or payload.get("parent_session_id")
        or payload.get("parent_conversation_id")
        or payload.get("is_subagent")
    )


def state_user() -> str:
    candidate = os.environ.get("USER") or os.environ.get("LOGNAME") or getpass.getuser() or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", candidate)


def resolve_state_dir(override: str | None) -> Path:
    if override:
        return Path(override).expanduser()
    configured = os.environ.get("AGENT_ROSTER_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / f"agent-roster-{state_user()}"


def resolve_repo_root(override: str | None, payload: dict[str, Any]) -> Path:
    if override:
        candidate = Path(override).expanduser().resolve()
    else:
        payload_root = payload.get("workspace_roots") or payload.get("workspace_root") or payload.get("cwd")
        if isinstance(payload_root, list) and payload_root:
            payload_root = payload_root[0]
        candidate = (
            Path(str(payload_root)).expanduser().resolve()
            if payload_root
            else Path(__file__).resolve().parent.parent
        )
    top_level = run_git(candidate, "rev-parse", "--show-toplevel")
    return Path(top_level).resolve() if top_level else candidate


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return environment


def run_git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=git_environment(),
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def dirty_paths(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        timeout=15,
        check=False,
        env=git_environment(),
    )
    if completed.returncode != 0:
        return []

    fields = completed.stdout.decode("utf-8", errors="replace").split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        status = field[:2]
        path = field[3:] if len(field) >= 4 else ""
        if path:
            paths.add(path)
        if "R" in status or "C" in status:
            if index < len(fields) and fields[index]:
                paths.add(fields[index])
            index += 1
    return sorted(paths)


def repository_snapshot(root: Path) -> tuple[str, str, list[str]]:
    return (
        run_git(root, "branch", "--show-current"),
        run_git(root, "rev-parse", "--verify", "HEAD"),
        dirty_paths(root),
    )


def entry_path(state_dir: Path, key: str) -> Path:
    return state_dir / f"{key}.json"


def prepare_state_dir(state_dir: Path, create: bool) -> bool:
    if state_dir.is_symlink():
        raise PermissionError(f"state directory must not be a symlink: {state_dir}")
    try:
        metadata = state_dir.lstat()
    except FileNotFoundError:
        if not create:
            return False
        try:
            os.mkdir(state_dir, 0o700)
        except FileExistsError:
            pass
        metadata = state_dir.lstat()

    if not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(f"state path is not a directory: {state_dir}")
    if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
        raise PermissionError(f"state directory is owned by another user: {state_dir}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError(f"state directory permissions must be 0700: {state_dir}")
    return True


def process_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap_abandoned_lock(lock_dir: Path) -> bool:
    try:
        owner = int((lock_dir / "pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        try:
            age = time.time() - lock_dir.stat().st_mtime
        except OSError:
            return False
        if age < ABANDONED_LOCK_GRACE_SECONDS:
            return False
    else:
        if process_is_live(owner):
            return False
    discard(lock_dir / "pid")
    try:
        lock_dir.rmdir()
    except OSError:
        return False
    return True


@contextmanager
def mutation_lock(state_dir: Path) -> Iterator[None]:
    prepare_state_dir(state_dir, create=True)
    lock_dir = state_dir / ".mutation.lock"
    deadline = time.monotonic() + MUTATION_LOCK_TIMEOUT_SECONDS
    while True:
        try:
            os.mkdir(lock_dir, 0o700)
            break
        except FileExistsError:
            if reap_abandoned_lock(lock_dir):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for the agent roster mutation lock")
            time.sleep(MUTATION_LOCK_RETRY_SECONDS)

    try:
        (lock_dir / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        yield
    finally:
        discard(lock_dir / "pid")
        try:
            lock_dir.rmdir()
        except OSError:
            pass


def write_entry(path: Path, entry: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.stem}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(entry, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def read_entry(path: Path) -> dict[str, Any] | None:
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def stale_seconds() -> int:
    try:
        value = int(os.environ.get("AGENT_ROSTER_STALE_SECONDS", DEFAULT_STALE_SECONDS))
    except ValueError:
        return DEFAULT_STALE_SECONDS
    return value if value > 0 else DEFAULT_STALE_SECONDS


def classify_entry(path: Path, now: datetime | None = None) -> str:
    if not path.is_file():
        return "missing"
    entry = read_entry(path)
    if entry is None:
        return "invalid-json"

    required_strings = ("key", "host", "conversation_id", "root", "branch", "head", "joined_at", "last_seen")
    if any(not isinstance(entry.get(field), str) for field in required_strings):
        return "invalid-schema"
    if entry["host"] not in HOSTS or not isinstance(entry.get("dirty_paths"), list):
        return "invalid-schema"
    if any(not isinstance(path_value, str) for path_value in entry["dirty_paths"]):
        return "invalid-schema"

    last_seen = parse_timestamp(entry["last_seen"])
    if last_seen is None:
        return "invalid-schema"
    age = ((now or datetime.now(timezone.utc)) - last_seen).total_seconds()
    return "stale" if age > stale_seconds() else "live"


def discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def live_entries(state_dir: Path, reap: bool) -> list[dict[str, Any]]:
    if not state_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(state_dir.glob("*.json")):
        classification = classify_entry(path)
        if classification == "live":
            entry = read_entry(path)
            if entry is not None:
                entries.append(entry)
        elif reap:
            discard(path)
    return entries


def with_current_paths(entry: dict[str, Any]) -> dict[str, Any]:
    rendered = dict(entry)
    root = Path(str(entry["root"]))
    current = set(dirty_paths(root))
    joined = set(str(path) for path in entry.get("dirty_paths", []))
    rendered["checkout_paths_changed_since_join"] = sorted(current - joined)
    return rendered


def describe_entry(entry: dict[str, Any]) -> str:
    rendered = with_current_paths(entry)
    intent = str(rendered.get("intent") or "intent not declared")
    paths = rendered["checkout_paths_changed_since_join"]
    if paths:
        # Set difference over the dirty checkout, so authorship never enters the computation. Earlier
        # wording ("changed since join with authorship unknown") read as attribution to every session
        # that saw it, and three peers in one evening each believed the others held these paths.
        path_text = (
            "paths dirty in this shared checkout since this session joined — any session or the user may "
            f"have changed them, NOT attributable to this one: {', '.join(paths[:12])}")
        if len(paths) > 12:
            path_text += f", and {len(paths) - 12} more"
    else:
        path_text = "no checkout paths changed since this session joined"
    return (
        f"{rendered['key']} on {rendered['host']} is in {rendered['root']} "
        f"at {rendered['branch'] or '(detached)'} ({str(rendered['head'])[:10]}), "
        f"with {intent}; {path_text}."
    )


def session_context(key: str, entries: list[dict[str, Any]]) -> str:
    peers = [entry for entry in entries if entry.get("key") != key]
    if not peers:
        text = f"Agent roster snapshot: {key} is the only live agent session currently visible on this machine."
    else:
        lines = [f"Agent roster snapshot for {key}: {len(peers)} other live session(s) are visible."]
        lines.extend(describe_entry(entry) for entry in peers)
        # The snapshot is injected before any skill trigger matches, so it is the only place a
        # session learns it has peers at the moment that fact first matters.
        lines.append(
            "Load `multi-agent-session` before editing shared files; `git status --short` plus "
            "`python3 Tools/agent-roster.py roster` is the probe for a path that changed under you."
        )
        text = "\n".join(lines)
    return text[:MAX_CONTEXT_LENGTH]


def emit_join_context(host: str, text: str) -> None:
    if host == "cursor":
        json.dump({"additional_context": text}, sys.stdout)
        sys.stdout.write("\n")
    elif host == "claude":
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": text,
                }
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
    else:
        sys.stdout.write(f"{text}\n")


def handle_join(arguments: argparse.Namespace, payload: dict[str, Any], host: str) -> None:
    if is_subagent(payload):
        return
    key = conversation_key(host, payload)
    if key is None:
        return

    state_dir = resolve_state_dir(arguments.state_dir)
    root = resolve_repo_root(arguments.repo_root, payload)
    branch, head, paths = repository_snapshot(root)
    now = utc_now()
    with mutation_lock(state_dir):
        path = entry_path(state_dir, key)
        existing = read_entry(path) or {}
        entry = {
            "key": key,
            "host": host,
            "conversation_id": str(payload.get("conversation_id") or payload.get("session_id")),
            "root": str(root),
            "branch": branch,
            "head": head,
            "dirty_paths": paths,
            "intent": str(existing.get("intent") or ""),
            "joined_at": str(existing.get("joined_at") or now),
            "last_seen": now,
        }
        write_entry(path, entry)
        live_entries(state_dir, reap=True)
    emit_join_context(host, session_context(key, live_entries(state_dir, reap=False)))


def handle_leave(arguments: argparse.Namespace, payload: dict[str, Any], host: str) -> None:
    if is_subagent(payload):
        return
    key = conversation_key(host, payload)
    if key is None:
        return
    state_dir = resolve_state_dir(arguments.state_dir)
    if not prepare_state_dir(state_dir, create=False):
        return
    with mutation_lock(state_dir):
        discard(entry_path(state_dir, key))
        live_entries(state_dir, reap=True)


def handle_beat(arguments: argparse.Namespace, payload: dict[str, Any], host: str) -> None:
    if is_subagent(payload):
        return
    key = conversation_key(host, payload)
    if key is None:
        return
    state_dir = resolve_state_dir(arguments.state_dir)
    if not prepare_state_dir(state_dir, create=False):
        return
    with mutation_lock(state_dir):
        path = entry_path(state_dir, key)
        entry = read_entry(path)
        if entry is None:
            return
        entry["last_seen"] = utc_now()
        write_entry(path, entry)
        live_entries(state_dir, reap=True)


def handle_roster(arguments: argparse.Namespace) -> None:
    state_dir = resolve_state_dir(arguments.state_dir)
    entries = (
        [with_current_paths(entry) for entry in live_entries(state_dir, reap=False)]
        if prepare_state_dir(state_dir, create=False)
        else []
    )
    if arguments.json:
        json.dump({"sessions": entries}, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return
    if not entries:
        print("No live agent sessions.")
        return
    for entry in entries:
        print(describe_entry(entry))


def handle_intent(arguments: argparse.Namespace, payload: dict[str, Any], host: str) -> None:
    state_dir = resolve_state_dir(arguments.state_dir)
    if not prepare_state_dir(state_dir, create=False):
        raise ValueError("no live agent sessions")
    key = arguments.key or conversation_key(host, payload)
    root = str(resolve_repo_root(arguments.repo_root, payload))
    with mutation_lock(state_dir):
        candidates = live_entries(state_dir, reap=True)
        if key is None:
            matching = [entry for entry in candidates if entry.get("root") == root]
            if len(matching) == 1:
                key = str(matching[0]["key"])
        if key is None:
            raise ValueError("intent requires --key when multiple or no sessions share this checkout")

        path = entry_path(state_dir, key)
        entry = read_entry(path)
        if entry is None:
            raise ValueError(f"live session not found: {key}")
        entry["intent"] = " ".join(arguments.text.split())[:500]
        entry["last_seen"] = utc_now()
        write_entry(path, entry)
    print(f"Updated intent for {key}.")


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir")
    parser.add_argument("--repo-root")
    parser.add_argument("--host", choices=HOSTS, default="claude")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--classify-entry", type=Path)

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("join")
    subparsers.add_parser("leave")
    subparsers.add_parser("beat")

    roster = subparsers.add_parser("roster")
    roster.add_argument("--json", action="store_true")

    intent = subparsers.add_parser("intent")
    intent.add_argument("text")
    intent.add_argument("--key")
    arguments, _unrecognized = parser.parse_known_args(argv)
    return arguments


def main(argv: list[str]) -> int:
    arguments = parse_arguments(argv)
    try:
        if arguments.classify_entry is not None:
            print(classify_entry(arguments.classify_entry))
            return 0

        if arguments.command == "roster":
            handle_roster(arguments)
            return 0
        if arguments.command is None:
            raise ValueError("a command is required")

        payload = read_payload() if arguments.command in {"join", "leave", "beat"} else {}
        host = detect_host(payload, arguments.host)
        handlers = {
            "join": handle_join,
            "leave": handle_leave,
            "beat": handle_beat,
            "intent": handle_intent,
        }
        handlers[arguments.command](arguments, payload, host)
    except Exception as error:
        if arguments.strict:
            raise
        print(f"agent roster unavailable: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
