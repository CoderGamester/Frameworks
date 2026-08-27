#!/usr/bin/env python3
"""Validate repository AGENTS.md structure without rewriting any guide."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".git", "Library", "Temp", "Logs", "obj"}
CANONICAL_SKILLS_PATH = Path(".agents/skills")
CLAUDE_SKILLS_PATH = Path(".claude/skills")
EXPECTED_WRAPPER = b"@AGENTS.md\n"
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


def CheckWrappers(root: Path, guides: list[Path], errors: list[str]) -> None:
    for guide in guides:
        wrapper = guide.with_name("CLAUDE.md")
        if not wrapper.is_file():
            errors.append(f"{guide.relative_to(root)}: missing sibling CLAUDE.md")
            continue
        if wrapper.read_bytes() != EXPECTED_WRAPPER:
            errors.append(
                f"{wrapper.relative_to(root)}: wrapper must contain exactly @AGENTS.md followed by LF"
            )


def GitIndexModes(root: Path, relative_root: Path, errors: list[str]) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", str(relative_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append(f"cannot inspect Git modes for {relative_root}: {result.stderr.strip()}")
        return {}

    modes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^(\d{6}) [0-9a-f]+ \d+\t(.+)$", line)
        if match:
            modes[match.group(2)] = match.group(1)
    return modes


def VisibleNames(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {child.name for child in path.iterdir() if child.name != ".DS_Store"}


def SkillAliasViolations(root: Path, modes: dict[str, str]) -> list[str]:
    errors: list[str] = []
    canonical_root = root / CANONICAL_SKILLS_PATH
    claude_root = root / CLAUDE_SKILLS_PATH

    if canonical_root.is_symlink() or not canonical_root.is_dir():
        return [f"{CANONICAL_SKILLS_PATH}: canonical skills root must be a real directory"]
    if claude_root.is_symlink() or not claude_root.is_dir():
        return [f"{CLAUDE_SKILLS_PATH}: Claude skills root must be a real directory"]

    canonical_names = VisibleNames(canonical_root)
    claude_names = VisibleNames(claude_root)
    for name in sorted(canonical_names - claude_names):
        errors.append(f"{CLAUDE_SKILLS_PATH / name}: missing Claude skill alias")
    for name in sorted(claude_names - canonical_names):
        errors.append(f"{CLAUDE_SKILLS_PATH / name}: alias has no canonical skill")

    checkout_root = root.resolve()
    for name in sorted(canonical_names & claude_names):
        canonical = canonical_root / name
        alias = claude_root / name
        relative_alias = CLAUDE_SKILLS_PATH / name
        expected_target = f"../../.agents/skills/{name}"

        if canonical.is_symlink() or not canonical.is_dir():
            errors.append(f"{CANONICAL_SKILLS_PATH / name}: canonical skill must be a real directory")
            continue
        if not (canonical / "SKILL.md").is_file():
            errors.append(f"{CANONICAL_SKILLS_PATH / name}: missing SKILL.md")
        if not alias.is_symlink():
            if alias.is_dir():
                errors.append(f"{relative_alias}: copied skill directory is forbidden")
            elif alias.is_file() and alias.read_text(encoding="utf-8", errors="ignore") == expected_target:
                errors.append(f"{relative_alias}: plain Git symlink placeholder; enable Git symlinks")
            else:
                errors.append(f"{relative_alias}: expected a symlink")
            continue

        actual_target = os.readlink(alias)
        if actual_target != expected_target:
            errors.append(f"{relative_alias}: expected target {expected_target!r}, found {actual_target!r}")
        if not alias.exists():
            errors.append(f"{relative_alias}: dangling Claude skill alias")
        else:
            resolved = alias.resolve()
            if resolved != canonical.resolve() or not resolved.is_relative_to(checkout_root):
                errors.append(f"{relative_alias}: must resolve to its checkout-local canonical skill")
        if modes.get(str(relative_alias)) != "120000":
            errors.append(f"{relative_alias}: Git index mode must be 120000")

    return errors


def CheckSkillAliases(root: Path, errors: list[str]) -> None:
    errors.extend(SkillAliasViolations(root, GitIndexModes(root, CLAUDE_SKILLS_PATH, errors)))


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

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        guide = root / "AGENTS.md"
        wrapper = root / "CLAUDE.md"
        guide.write_text("# Guide\n", encoding="utf-8")
        wrapper.write_bytes(EXPECTED_WRAPPER)
        wrapper_errors: list[str] = []
        CheckWrappers(root, [guide], wrapper_errors)
        if wrapper_errors:
            print("SELF-TEST FAILED: valid wrapper fixture was rejected")
            return 1
        wrapper.write_bytes(b"@AGENTS.md\r\n")
        wrapper_errors = []
        CheckWrappers(root, [guide], wrapper_errors)
        if not wrapper_errors:
            print("SELF-TEST FAILED: CRLF wrapper was accepted")
            return 1
        wrapper.write_bytes(EXPECTED_WRAPPER)

        canonical = root / CANONICAL_SKILLS_PATH / "example"
        aliases = root / CLAUDE_SKILLS_PATH
        canonical.mkdir(parents=True)
        aliases.mkdir(parents=True)
        (canonical / "SKILL.md").write_text("---\nname: example\n---\n", encoding="utf-8")
        alias = aliases / "example"
        alias.symlink_to("../../.agents/skills/example", target_is_directory=True)
        modes = {str(CLAUDE_SKILLS_PATH / "example"): "120000"}
        if SkillAliasViolations(root, modes):
            print("SELF-TEST FAILED: valid skill alias fixture was rejected")
            return 1
        alias.unlink()
        alias.mkdir()
        if not any("copied skill directory" in error for error in SkillAliasViolations(root, modes)):
            print("SELF-TEST FAILED: copied skill directory was accepted")
            return 1
        alias.rmdir()
        alias.write_text("../../.agents/skills/example", encoding="utf-8")
        if not any("plain Git symlink placeholder" in error for error in SkillAliasViolations(root, modes)):
            print("SELF-TEST FAILED: plain symlink placeholder was accepted")
            return 1
        alias.unlink()
        alias.symlink_to("../../.agents/skills/missing", target_is_directory=True)
        wrong_errors = SkillAliasViolations(root, modes)
        if not any("expected target" in error for error in wrong_errors) or not any("dangling" in error for error in wrong_errors):
            print("SELF-TEST FAILED: wrong dangling skill target was accepted")
            return 1

    print("SELF-TEST PASSED: guide sections and skill aliases pass in both directions")
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

    CheckWrappers(ROOT, guides, errors)
    CheckSkillAliases(ROOT, errors)

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
