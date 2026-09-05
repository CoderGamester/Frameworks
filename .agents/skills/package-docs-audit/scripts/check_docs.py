#!/usr/bin/env python3
"""Check package documentation invariants without claiming Unity compatibility."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Optional


LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
UNITY_VERSION = re.compile(r"\bUnity(?:\s+version)?\s+\d", re.IGNORECASE)


def slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r"[ ]+", "-", text)


def anchors(markdown: str) -> set[str]:
    counts: dict[str, int] = {}
    result: set[str] = set()
    for heading in HEADING.findall(markdown):
        base = slug(heading)
        index = counts.get(base, 0)
        counts[base] = index + 1
        result.add(base if index == 0 else f"{base}-{index}")
    return result


def link_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split(maxsplit=1)[0]


def check_package(package: Path, base: Optional[str] = None) -> list[str]:
    errors: list[str] = []
    manifest_path = package / "package.json"
    readme = package / "README.md"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{manifest_path}: cannot read valid JSON: {exc}"]

    description = str(manifest.get("description", ""))
    if not description.strip():
        errors.append(f"{manifest_path}: description is empty")
    if UNITY_VERSION.search(description):
        errors.append(f"{manifest_path}: description contains a Unity version")
    if not readme.is_file():
        errors.append(f"{readme}: missing package README")
    else:
        content = readme.read_text(encoding="utf-8-sig")
        if "minimum unity version" not in content.lower():
            errors.append(f"{readme}: missing authoritative compatibility notice")

    for sample in manifest.get("samples", []):
        relative = sample.get("path", "")
        sample_root = package / relative
        if not relative or not sample_root.is_dir():
            errors.append(f"{manifest_path}: missing declared sample path {relative!r}")
        elif not (sample_root / "README.md").is_file():
            errors.append(f"{sample_root}: declared sample has no canonical README.md")

    markdown_files = sorted(package.rglob("*.md"))
    markdown_anchors: dict[Path, set[str]] = {}
    for path in markdown_files:
        text = path.read_text(encoding="utf-8-sig")
        markdown_anchors[path.resolve()] = anchors(text)
        for raw in LINK.findall(text):
            target = urllib.parse.unquote(link_target(raw))
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if any(marker in target for marker in ("<", ">", "{", "}")):
                continue
            file_part, _, fragment = target.partition("#")
            destination = (path.parent / file_part).resolve() if file_part else path.resolve()
            if file_part and not destination.exists():
                errors.append(f"{path}: broken link {target!r}")
                continue
            if fragment and destination.suffix.lower() == ".md" and destination.is_file():
                target_anchors = markdown_anchors.get(destination)
                if target_anchors is None:
                    target_anchors = anchors(destination.read_text(encoding="utf-8-sig"))
                    markdown_anchors[destination] = target_anchors
                if fragment.lower() not in target_anchors:
                    errors.append(f"{path}: missing heading anchor {target!r}")

    samples_root = package / "Samples~"
    if samples_root.is_dir() and (package / ".git").exists():
        comparisons = ["HEAD"]
        if base:
            comparisons.insert(0, f"{base}...HEAD")
        added: list[bytes] = []
        for comparison in comparisons:
            added.extend(subprocess.run(
                ["git", "-C", str(package), "diff", "--name-only", "--diff-filter=A", "-z", comparison],
                check=True, capture_output=True,
            ).stdout.split(b"\0"))
        untracked = subprocess.run(
            ["git", "-C", str(package), "ls-files", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True,
        ).stdout.split(b"\0")
        candidates: set[Path] = set()
        for raw in added + untracked:
            if not raw:
                continue
            relative = Path(raw.decode())
            if relative.parts and relative.parts[0] == "Samples~" and not relative.name.endswith(".meta"):
                candidates.add(package / relative)
                parent = (package / relative).parent
                while parent != samples_root and samples_root in parent.parents:
                    candidates.add(parent)
                    parent = parent.parent
        for asset in sorted(candidates):
            if not Path(f"{asset}.meta").is_file():
                errors.append(f"{asset}: newly added Unity asset is missing .meta")
    return errors


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        good = root / "good"
        sample = good / "Samples~" / "Example"
        sample.mkdir(parents=True)
        (good / "package.json").write_text(json.dumps({
            "description": "Imports configuration data from Google Sheets.",
            "samples": [{"displayName": "Example", "path": "Samples~/Example"}],
        }))
        (good / "README.md").write_text("# Good\n\nMinimum Unity version: 6000.0.\n\n[Sample](<Samples~/Example/README.md#run-it>)\n")
        (sample / "README.md").write_text("# Example\n\n## Run it\n")
        for asset in (good / "Samples~", sample, sample / "README.md"):
            Path(f"{asset}.meta").write_text("fileFormatVersion: 2\n")
        if check_package(good):
            print("SELF-TEST FAILED: valid fixture was rejected")
            return 1
        (good / "README.md").write_text("# Good\n\n[Broken](missing.md#nope)\n")
        failures = check_package(good)
        expected = ("compatibility notice", "broken link")
        if not all(any(item in failure for failure in failures) for item in expected):
            print("SELF-TEST FAILED: invalid fixture was not rejected in both directions")
            return 1
    print("SELF-TEST PASSED: positive and negative fixtures behaved as expected")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packages", nargs="*", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--base", help="also check sample assets added since this Git ref")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.packages:
        parser.error("provide at least one package path or --self-test")
    failures: list[str] = []
    for package in args.packages:
        failures.extend(check_package(package.resolve(), args.base))
    if failures:
        print("\n".join(failures))
        print(f"FAILED: {len(failures)} documentation invariant(s)")
        return 1
    print(f"PASSED: checked {len(args.packages)} package(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
