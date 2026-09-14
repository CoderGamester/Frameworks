#!/usr/bin/env python3
"""Refuse a package commit that leaves more than one pending CHANGELOG section.

`AGENTS.md` says to follow the package's existing unpublished section, and the release skill says to
merge `Unreleased` into it rather than cutting another version. Both were in force when a session cut
0.7.4 above an unreleased 0.7.3 anyway, and the user had to catch it. The release-time gates cannot:
`preflight-pr` accepts a two-pending shape as long as `package.json` matches the top heading, and by
then the commit has already landed. This runs before git does.

    python3 Tools/check-package-version.py --check Packages/com.gamelovers.services   # judge a package
    python3 Tools/check-package-version.py --self-test                                # fixtures
    python3 Tools/check-package-version.py gate-commit                                # PreToolUse hook

Ships in shadow mode: it reports and denies nothing until `FRAMEWORKS_HOOK_PREDICATES=enforce`.
A `package-version-gate.disabled` marker beside the roster state stops it mid-session.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent /
                       ".agents/skills/unity-package-release/scripts"))
import changelog  # noqa: E402

MODE_DEFAULT = "shadow"
MODES = ("enforce", "shadow", "off")
DISABLED_MARKER = "package-version-gate.disabled"
GIT_GLOBAL_OPTIONS_WITH_VALUE = ("-C", "-c", "--exec-path", "--git-dir", "--work-tree", "--namespace")


def tokenize_segment(chunk: str) -> list[str]:
    """Split one shell segment into tokens, tolerating quoting a shell balances later.

    A here-document is the repository's normal way to write a multi-line commit message,
    and it leaves the segment holding `git commit` with an unbalanced quote. Skipping a
    segment that fails to parse therefore hides the most common commit of all, so fall
    back to whitespace tokens with the quote characters removed. Requiring `git` in
    argv[0] is what still rejects a quoted mention such as `rg "git commit"`.
    """
    try:
        return shlex.split(chunk)
    except ValueError:
        return chunk.replace('"', " ").replace("'", " ").split()


def command_segments(command: str) -> list[list[str]]:
    """Split a shell command into argv lists, one per `;`/`&&`/`||`/pipe/newline segment.

    An operator inside a quoted argument does not end a segment, so a grep alternation such
    as `"a|git commit|b"` stays one token instead of surfacing a `git commit` segment. An
    unbalanced quote (a here-document body) runs to the end of the command, which leaves
    every segment before it intact.
    """
    segments: list[list[str]] = []
    chunk: list[str] = []
    quote = None
    index = 0

    def flush() -> None:
        text = "".join(chunk).strip()
        tokens = tokenize_segment(text) if text else []
        if tokens:
            segments.append(tokens)
        chunk.clear()

    while index < len(command):
        char = command[index]
        if quote:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"' and index + 1 < len(command):
                chunk.append(char)
                index += 1
                char = command[index]
            chunk.append(char)
        elif char in ("'", '"'):
            quote = char
            chunk.append(char)
        elif char == "\\" and index + 1 < len(command):
            chunk.append(char)
            index += 1
            chunk.append(command[index])
        elif command.startswith(("||", "&&"), index):
            flush()
            index += 1
        elif char in ";|&\n":
            flush()
        else:
            chunk.append(char)
        index += 1
    flush()
    return segments


def is_git_commit(command: str) -> bool:
    """True when any segment invokes `git commit` for real, ignoring quoted mentions."""
    for tokens in command_segments(command):
        index = 0
        while index < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]):
            index += 1
        if index < len(tokens) and tokens[index] == "env":
            index += 1
        if index >= len(tokens):
            continue
        executable = tokens[index]
        if executable != "git" and not executable.endswith("/git"):
            continue
        index += 1
        while index < len(tokens):
            token = tokens[index]
            if token in GIT_GLOBAL_OPTIONS_WITH_VALUE:
                index += 2
                continue
            if token.startswith("--") or token.startswith("-"):
                index += 1
                continue
            break
        if index < len(tokens) and tokens[index] == "commit":
            if "--dry-run" in tokens:
                continue
            return True
    return False



def is_git_commit(command: str) -> bool:
    """True when a segment invokes `git commit` for real, ignoring a quoted mention."""
    for tokens in command_segments(command):
        index = 0
        while index < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]):
            index += 1
        if index < len(tokens) and tokens[index] == "env":
            index += 1
        if index >= len(tokens):
            continue
        executable = tokens[index]
        if executable != "git" and not executable.endswith("/git"):
            continue
        index += 1
        while index < len(tokens):
            token = tokens[index]
            if token in GIT_GLOBAL_OPTIONS_WITH_VALUE:
                index += 2
                continue
            if token.startswith("-"):
                index += 1
                continue
            break
        if index < len(tokens) and tokens[index] == "commit":
            if "--dry-run" in tokens:
                continue
            return True
    return False


def commit_directories(command: str, cwd: str) -> list[str]:
    """Directories a `git commit` in this command would run in: an explicit -C, a preceding cd, or cwd."""
    directories: list[str] = []
    current = cwd
    for tokens in command_segments(command):
        if tokens and tokens[0] == "cd" and len(tokens) > 1:
            candidate = tokens[1]
            current = candidate if os.path.isabs(candidate) else os.path.join(current, candidate)
            continue
        explicit = None
        for position, token in enumerate(tokens):
            if token == "-C" and position + 1 < len(tokens):
                explicit = tokens[position + 1]
        if is_git_commit(" ".join(shlex.quote(token) for token in tokens)):
            target = explicit or current
            directories.append(target if os.path.isabs(target) else os.path.join(current, target))
    return directories


def package_root(directory: str) -> pathlib.Path | None:
    """The package repository this directory sits in, or None when it is not one."""
    top = run_git(["-C", directory, "rev-parse", "--show-toplevel"])
    if not top:
        return None
    path = pathlib.Path(top)
    if path.parent.name != "Packages":
        return None
    if not (path / "package.json").is_file() or not (path / "CHANGELOG.md").is_file():
        return None
    return path


def run_git(args: list[str]) -> str:
    try:
        done = subprocess.run(["git", *args], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def pending_names(changelog_path: pathlib.Path, highest: tuple | None) -> list[str]:
    """Unreleased, plus every versioned heading above the highest published tag."""
    names: list[str] = []
    text = changelog_path.read_text(encoding="utf-8", errors="replace")
    if changelog.UNRELEASED.search(text):
        names.append("Unreleased")
    for section in changelog.sections(changelog_path):
        parsed = changelog.semver(section["version"])
        # With no tags at all, "published" is undecidable, so only the version check applies.
        if parsed and highest and parsed > highest:
            names.append(section["version"])
    return names


def evaluate(package: pathlib.Path, changelog_path: pathlib.Path, package_json: pathlib.Path,
             where: str) -> list[str]:
    problems: list[str] = []
    tags = [parsed for tag in run_git(["-C", str(package), "tag", "--list"]).splitlines()
            if (parsed := changelog.semver(tag.strip()))]
    highest = max(tags) if tags else None
    pending = pending_names(changelog_path, highest)
    if len(pending) > 1:
        versioned = [name for name in pending if name != "Unreleased"]
        target = min(versioned, key=lambda v: changelog.semver(v)) if versioned else pending[-1]
        extras = ", ".join(name for name in pending if name != target)
        problems.append(
            f"{package.name} ({where}): CHANGELOG.md has {len(pending)} pending sections "
            f"({', '.join(pending)}). Fold {extras} into ## [{target}], the existing unpublished "
            "section, before committing. AGENTS.md Releases and unity-package-release Step 0 both "
            "say to merge rather than cut another version."
        )
    try:
        declared = json.loads(package_json.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return problems
    heads = changelog.sections(changelog_path)
    if heads and declared and declared != heads[0]["version"]:
        problems.append(
            f"{package.name} ({where}): package.json is {declared} but the top CHANGELOG heading is "
            f"## [{heads[0]['version']}]; they must agree. `release.py prepare` is the sanctioned bump."
        )
    return problems


def problems_for(package: pathlib.Path) -> list[str]:
    """Judge the working tree and the index: a pathspec commit takes one, a bare commit the other."""
    found = evaluate(package, package / "CHANGELOG.md", package / "package.json", "working tree")
    with tempfile.TemporaryDirectory() as scratch:
        staged = pathlib.Path(scratch)
        wrote = True
        for name in ("CHANGELOG.md", "package.json"):
            blob = run_git(["-C", str(package), "show", f":{name}"])
            if not blob:
                wrote = False
                break
            (staged / name).write_text(blob + "\n", encoding="utf-8")
        if wrote:
            for problem in evaluate(package, staged / "CHANGELOG.md", staged / "package.json", "index"):
                if problem.replace("(index)", "(working tree)") not in found:
                    found.append(problem)
    return found


def mode(state_dir: pathlib.Path) -> str:
    if (state_dir / DISABLED_MARKER).exists():
        return "off"
    requested = (os.environ.get("FRAMEWORKS_HOOK_PREDICATES") or "").strip().lower()
    return requested if requested in MODES else MODE_DEFAULT


def state_directory() -> pathlib.Path:
    base = os.environ.get("TMPDIR") or tempfile.gettempdir()
    user = re.sub(r"[^A-Za-z0-9._-]", "_", os.environ.get("USER") or "agent")
    return pathlib.Path(base) / f"agent-roster-{user}"


def deny_output(payload: dict, text: str) -> dict:
    if payload.get("cursor_version"):
        return {"permission": "deny", "agent_message": text,
                "user_message": "Fold the pending CHANGELOG section before committing."}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def gate_commit(payload: dict) -> dict | None:
    tool_input = payload.get("tool_input")
    command = str((tool_input or {}).get("command") or payload.get("command") or "")
    if not command or not is_git_commit(command):
        return None
    cwd = str(payload.get("cwd") or pathlib.Path.cwd())
    problems: list[str] = []
    for directory in commit_directories(command, cwd):
        package = package_root(directory)
        if package is not None:
            problems.extend(problems_for(package))
    if not problems:
        return None
    if mode(state_directory()) != "enforce":
        return None
    marker = state_directory() / DISABLED_MARKER
    text = "\n\n".join(problems + [f"False deny? `touch {marker}` stops this gate; report it so it is fixed."])
    return deny_output(payload, text)


def self_test() -> int:
    import shutil
    failures: list[str] = []

    def package(scratch: pathlib.Path, name: str, entries: list[str], version: str,
                tags: list[str], unreleased: bool) -> pathlib.Path:
        root = scratch / "Packages" / name
        root.mkdir(parents=True)
        subprocess.run(["git", "-C", str(root), "init", "-q", "."], check=True)
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
        body = "# Changelog\n\n"
        if unreleased:
            body += "## [Unreleased]\n\n**Changed**:\n- pending\n\n"
        for entry in entries:
            body += f"## [{entry}] - 2026-01-01\n\n**Changed**:\n- shipped\n\n"
        (root / "CHANGELOG.md").write_text(body, encoding="utf-8")
        (root / "package.json").write_text(json.dumps({"name": name, "version": version}), encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
        for tag in tags:
            subprocess.run(["git", "-C", str(root), "tag", tag], check=True)
        return root

    def expect(label: str, root: pathlib.Path, should_fail: bool, needle: str = "") -> None:
        found = problems_for(root)
        if bool(found) != should_fail:
            failures.append(f"{label}: expected {'a problem' if should_fail else 'none'}, got {found}")
        elif needle and not any(needle in problem for problem in found):
            failures.append(f"{label}: expected {needle!r} in {found}")

    with tempfile.TemporaryDirectory() as scratch_name:
        scratch = pathlib.Path(scratch_name)
        # F1 the shape every package is in today.
        expect("F1 Unreleased above a tagged top", package(scratch, "f1", ["0.7.3"], "0.7.3", ["0.7.3"], True), False)
        # F2 the shape the incident produced: a second version cut above an unreleased one.
        expect("F2 two versions above the tag", package(scratch, "f2", ["0.7.4", "0.7.3"], "0.7.4", ["0.7.2"], False),
               True, "Fold 0.7.4 into ## [0.7.3]")
        # F3 Unreleased plus an unreleased version.
        expect("F3 Unreleased above an unreleased version",
               package(scratch, "f3", ["0.7.4", "0.7.3"], "0.7.4", ["0.7.3"], True), True, "Fold Unreleased")
        # F4 a legitimate release cut: one pending version, package.json agreeing.
        expect("F4 a release being cut", package(scratch, "f4", ["0.7.4", "0.7.3"], "0.7.4", ["0.7.3"], False), False)
        # F5 the version and the heading disagreeing.
        expect("F5 package.json disagrees", package(scratch, "f5", ["0.7.3"], "0.7.4", ["0.7.3"], False),
               True, "they must agree")
        # F6 no tags at all: publication is undecidable, so only the version check applies.
        expect("F6 no tags", package(scratch, "f6", ["0.1.0"], "0.1.0", [], False), False)

        # F7 the index and the working tree disagreeing: a bare commit records the index.
        split = package(scratch, "f7", ["0.7.3"], "0.7.3", ["0.7.3"], True)
        text = (split / "CHANGELOG.md").read_text(encoding="utf-8")
        (split / "CHANGELOG.md").write_text(text.replace("## [Unreleased]", "## [0.7.5] - 2026-02-02"), encoding="utf-8")
        subprocess.run(["git", "-C", str(split), "add", "CHANGELOG.md"], check=True)
        (split / "CHANGELOG.md").write_text(text, encoding="utf-8")
        found = problems_for(split)
        if not any("(index)" in problem for problem in found):
            failures.append(f"F7 index/tree split: the staged shape was not judged, got {found}")

        # F8 command parsing.
        cases = [
            ("git -C Packages/x commit -m m", "/repo", ["/repo/Packages/x"]),
            ("cd Packages/x && git commit -m m", "/repo", ["/repo/Packages/x"]),
            ("rg \"git commit\" .", "/repo", []),
            ("git commit --dry-run", "/repo", []),
            ("git commit -m m", "/repo", ["/repo"]),
        ]
        for command, cwd, expected in cases:
            got = commit_directories(command, cwd)
            if got != expected:
                failures.append(f"F8 {command!r}: expected {expected}, got {got}")

        # F9 both output shapes.
        text = "problem"
        if deny_output({}, text)["hookSpecificOutput"]["permissionDecision"] != "deny":
            failures.append("F9 Claude shape")
        if deny_output({"cursor_version": "3.0"}, text).get("permission") != "deny":
            failures.append("F9 Cursor shape")

    if failures:
        for failure in failures:
            print(f"SELF-TEST FAILED: {failure}", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: pending sections, version agreement, index split, parsing, and both shapes")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if "--check" in argv:
        problems: list[str] = []
        for name in argv[argv.index("--check") + 1:]:
            root = pathlib.Path(name).resolve()
            if (root / "package.json").is_file():
                problems.extend(problems_for(root))
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        print(f"checked {len(argv[argv.index('--check') + 1:])} package(s); {len(problems)} problem(s)")
        return 1 if problems else 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        response = gate_commit(payload if isinstance(payload, dict) else {})
    except Exception:
        # Fail open: this gate must never wedge a host.
        return 0
    if response is not None:
        json.dump(response, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
