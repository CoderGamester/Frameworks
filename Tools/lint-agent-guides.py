#!/usr/bin/env python3
"""Validate repository AGENTS.md structure without rewriting any guide."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", "Library", "Temp", "Logs", "obj"}
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
SHARED_PATTERN = re.compile(
    r"<!-- BEGIN SHARED TEST RULES -->.*?<!-- END SHARED TEST RULES -->",
    re.DOTALL,
)
ROOT_REQUIRED_HEADINGS = (
    "## Scope and precedence",
    "## Safe repository workflow",
    "## Unity and verification",
    "## Implementation rules",
    "### Code comments",
    "### XML documentation",
    "### Member ordering",
    "## Releases",
    "### Package release workflow",
    "## Guide maintenance",
)


def GuideFiles() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("AGENTS.md")
        if not any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts)
    )


def Slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return re.sub(r"-+", "-", text.replace(" ", "-")).strip("-")


def WordBudget(path: Path) -> int:
    relative = path.relative_to(ROOT)
    if relative == Path("AGENTS.md"):
        return 3500
    if path.parent.name == "Tests":
        return 1300
    return 1800


def CheckLinks(path: Path, text: str, errors: list[str]) -> None:
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.strip().strip("<>")
        if target.startswith(("http://", "https://", "mailto:")):
            continue

        file_part, separator, fragment = target.partition("#")
        destination = path if not file_part else (path.parent / unquote(file_part)).resolve()
        if not destination.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing link target {target}")
            continue

        if separator and destination.is_file() and destination.suffix.lower() == ".md":
            anchors = {Slug(heading) for heading in HEADING_PATTERN.findall(destination.read_text(encoding="utf-8"))}
            if unquote(fragment).lower() not in anchors:
                errors.append(f"{path.relative_to(ROOT)}: missing heading anchor {target}")


def CheckCompanions(path: Path, errors: list[str]) -> None:
    relative = path.relative_to(ROOT)
    if len(relative.parts) < 3 or relative.parts[0] != "Packages":
        return

    for name in ("AGENTS.md.meta", "CLAUDE.md", "CLAUDE.md.meta"):
        if not (path.parent / name).exists():
            errors.append(f"{relative}: missing companion {name}")


def MissingRootSections(text: str) -> list[str]:
    lines = set(text.splitlines())
    return [heading for heading in ROOT_REQUIRED_HEADINGS if heading not in lines]


def EmptyRootSections(text: str) -> list[str]:
    lines = text.splitlines()
    empty: list[str] = []
    for heading in ROOT_REQUIRED_HEADINGS:
        if heading not in lines:
            continue
        start = lines.index(heading)
        level = len(heading) - len(heading.lstrip("#"))
        body = []
        for line in lines[start + 1:]:
            match = re.match(r"^(#{1,6})\s+", line)
            if match and len(match.group(1)) <= level:
                break
            if line.strip() and not match:
                body.append(line)
        if not body:
            empty.append(heading)
    return empty


def SelfTest() -> int:
    complete = "\n".join(f"{heading}\n- Enforced rule." for heading in ROOT_REQUIRED_HEADINGS)
    if MissingRootSections(complete) or EmptyRootSections(complete):
        print("SELF-TEST FAILED: complete fixture was rejected")
        return 1
    incomplete = complete.replace("### XML documentation\n- Enforced rule.\n", "")
    if MissingRootSections(incomplete) != ["### XML documentation"]:
        print("SELF-TEST FAILED: missing XML-documentation family was not detected")
        return 1
    empty = complete.replace(
        "### XML documentation\n- Enforced rule.",
        "### XML documentation",
    )
    if "### XML documentation" not in EmptyRootSections(empty):
        print("SELF-TEST FAILED: empty XML-documentation family was not detected")
        return 1
    print("SELF-TEST PASSED: accepts complete root and rejects a missing rule family")
    return 0


def Main(argv: list[str]) -> int:
    if argv[1:] == ["--self-test"]:
        return SelfTest()
    if argv[1:]:
        print(f"Usage: {argv[0]} [--self-test]", file=sys.stderr)
        return 2

    guides = GuideFiles()
    errors: list[str] = []
    warnings: list[str] = []
    shared_blocks: dict[Path, str] = {}

    if not guides:
        errors.append("No AGENTS.md files found")

    for path in guides:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        words = len(text.split())
        budget = WordBudget(path)

        if words > budget:
            warnings.append(f"{relative}: {words} words exceeds review budget {budget}")
        longest = max((len(line) for line in text.splitlines()), default=0)
        if longest > 500:
            warnings.append(f"{relative}: longest line is {longest} characters")
        if re.search(r"^##\s+.*Coverage Register", text, re.MULTILINE | re.IGNORECASE):
            errors.append(f"{relative}: volatile coverage register belongs in run artifacts")

        CheckLinks(path, text, errors)
        CheckCompanions(path, errors)
        if relative == Path("AGENTS.md"):
            for heading in MissingRootSections(text):
                errors.append(f"AGENTS.md: missing required rule-family heading {heading}")
            for heading in EmptyRootSections(text):
                errors.append(f"AGENTS.md: empty required rule-family heading {heading}")

        if path.parent.name == "Tests":
            match = SHARED_PATTERN.search(text)
            if match is None:
                errors.append(f"{relative}: missing synchronized shared-test block")
            else:
                shared_blocks[path] = match.group(0)

    if shared_blocks:
        canonical_path, canonical = next(iter(shared_blocks.items()))
        for path, block in shared_blocks.items():
            if block != canonical:
                errors.append(
                    f"{path.relative_to(ROOT)}: shared-test block differs from "
                    f"{canonical_path.relative_to(ROOT)}"
                )

    print(f"Agent guides: {len(guides)} files")
    print(f"Errors: {len(errors)}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"WARNING: {warning}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(Main(sys.argv))
