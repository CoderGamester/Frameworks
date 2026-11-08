#!/usr/bin/env python3
"""Resolve the `// RCR:` anchors in package tests against the production code they name.

An RCR line is a claim about production: change this snippet in this file and the test goes RED.
Nothing compiles it, so a rename silently turns it into a claim about code that no longer exists,
and the next reader trusts it. This resolves both halves without Unity, so rot fails in the commit
that causes it.

    python3 Tools/rcr-anchor-check.py [--root .]
    python3 Tools/rcr-anchor-check.py --self-test
"""
from __future__ import annotations

import pathlib
import re
import sys
import tempfile

TEST_GLOB = "Packages/com.gamelovers.*/Tests/**/*.cs"
RCR_LINE = re.compile(r"^\s*//\s*RCR:\s*(.*)$")
COMMENT_LINE = re.compile(r"^\s*//\s?(.*)$")
ADMIT_LINE = re.compile(r"^\s*//\s*ADMIT:")
# "no isolated red", "none claimed": a deliberate statement that nothing was mutated.
NO_CLAIM = re.compile(r"^(?:none|no)\b", re.IGNORECASE)
CANONICAL_HEAD = re.compile(r"^(\S+\.cs)\s+(\S+)")
CHANGE_SNIPPET = re.compile(r"change\s+`([^`]+)`")
MIN_PREFIX = 8


def collapse(text):
    # Compare with whitespace removed, not merely collapsed: a long snippet wraps across comment
    # lines and the join lands a space mid-token, so `if (!activity` + `.IsCompleted)` must still
    # match `if (!activity.IsCompleted)`. Indentation differences fall out for free.
    return "".join(text.split())


def anchor_blocks(text: str):
    """Yield (line-number, joined-text) for each RCR block, following its continuation comments."""
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = RCR_LINE.match(lines[index])
        if not match:
            index += 1
            continue
        start = index + 1
        parts = [match.group(1).strip()]
        index += 1
        while index < len(lines):
            following = COMMENT_LINE.match(lines[index])
            if not following or RCR_LINE.match(lines[index]) or ADMIT_LINE.match(lines[index]):
                break
            parts.append(following.group(1).strip())
            index += 1
        yield start, " ".join(part for part in parts if part)


def production_files(package: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    by_name: dict[str, list[pathlib.Path]] = {}
    for path in package.rglob("*.cs"):
        relative = path.relative_to(package).parts
        if "Tests" in relative or any(part.endswith("Samples~") for part in relative):
            continue
        by_name.setdefault(path.name, []).append(path)
    return by_name


def check_block(block: str, by_name: dict[str, list[pathlib.Path]]) -> str | None:
    if NO_CLAIM.match(block):
        return None
    head = CANONICAL_HEAD.match(block)
    if not head:
        return ("non-canonical head; the shared test block prescribes `<file>.cs <symbol> — <mutation>`, "
                f"got {block[:60]!r}")
    name = head.group(1)
    candidates = by_name.get(name, [])
    if not candidates:
        return f"cites {name}, which does not exist in this package outside Tests/"
    if len(candidates) > 1:
        return f"cites {name}, which is ambiguous: {[str(c) for c in candidates]}"
    snippet_match = CHANGE_SNIPPET.search(block)
    if not snippet_match:
        return None
    snippet = snippet_match.group(1)
    body = collapse(candidates[0].read_text(encoding="utf-8", errors="replace"))
    if "..." in snippet:
        # An elided snippet can only be checked up to the elision.
        prefix = snippet.split("...", 1)[0].rstrip()
        if len(prefix.strip()) < MIN_PREFIX:
            return None
        if collapse(prefix) not in body:
            return f"snippet prefix {prefix!r} does not occur in {name}"
        return None
    if collapse(snippet) not in body:
        return f"snippet {snippet!r} does not occur in {name}"
    return None


def check(root: pathlib.Path) -> tuple[list[str], int, int]:
    failures: list[str] = []
    anchors = checked = 0
    for package in sorted(root.glob("Packages/com.gamelovers.*")):
        tests = package / "Tests"
        if not tests.is_dir():
            continue
        by_name = production_files(package)
        for path in sorted(tests.rglob("*.cs")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for line, block in anchor_blocks(text):
                anchors += 1
                if CHANGE_SNIPPET.search(block):
                    checked += 1
                problem = check_block(block, by_name)
                if problem:
                    failures.append(f"{path.relative_to(root)}:{line}: {problem}")
    return failures, anchors, checked


def self_test() -> int:
    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        package = root / "Packages" / "com.gamelovers.fixture"
        (package / "Runtime" / "Internal").mkdir(parents=True)
        (package / "Tests" / "Editor").mkdir(parents=True)
        (package / "Runtime" / "Internal" / "Foo.cs").write_text(
            "class Foo { void Go() { if (!activity.IsCompleted) { Do(a, b); } } }\n", encoding="utf-8")
        tests = package / "Tests" / "Editor" / "FooTest.cs"

        def run(body: str) -> list[str]:
            tests.write_text(body, encoding="utf-8")
            return check(root)[0]

        cases = [
            ("// RCR: Foo.cs Go — change `if (!activity.IsCompleted)` to `if (true)` → RED\n", False),
            ("// RCR: Foo.cs Go — change `if (!_activity.IsCompleted)` to `if (true)` → RED\n", True),
            ("// RCR: Bar.cs Go — change `if (true)` to `if (false)` → RED\n", True),
            ("// RCR: none claimed for this fixture\n", False),
            ("// RCR: no isolated red\n", False),
            ("// RCR: Foo.cs Go — change `Do(a, ...)` to nothing → RED\n", False),
            ("// RCR: Foo.Go — skip the thing → RED\n", True),
            ("// RCR: Foo.cs Go — change `if (!activity\n// .IsCompleted)` to `if (true)` → RED\n", False),
        ]
        for body, should_fail in cases:
            failed = bool(run(body))
            if failed != should_fail:
                verb = "accepted" if should_fail else "rejected"
                print(f"SELF-TEST FAILED: {verb} {body.strip()!r}", file=sys.stderr)
                return 1
    print("SELF-TEST PASSED: anchors resolve, and rot, ambiguity, and a non-canonical head are rejected")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    root = pathlib.Path(argv[argv.index("--root") + 1]) if "--root" in argv else pathlib.Path.cwd()
    failures, anchors, checked = check(root.resolve())
    print(f"anchors={anchors} checked-snippets={checked}")
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
