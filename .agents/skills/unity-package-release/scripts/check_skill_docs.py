#!/usr/bin/env python3
"""Resolve the cross-file references between release.py and SKILL.md that no compiler checks.

Five commits changed how the release tool is used without touching its guide, leaving three working
days of stale instructions. Both directions of the reference are checked: every `add_parser`
subcommand must be documented, and every gate the guide cites must exist in the tool.

    python3 <this>              # check the real pair
    python3 <this> --self-test  # in-memory fixtures, both directions
"""
from __future__ import annotations

import pathlib
import re
import sys

ADD_PARSER = re.compile(r'add_parser\(\s*"([^"]+)"')
GATE_TOKEN = re.compile(r"\bG\d{1,2}[a-z]?\b")
# The guide writes contiguous gates as a prose range, so a token scan alone reports nine false
# "undefined" gates that are simply spelled as endpoints.
GATE_RANGE = re.compile(r"`?(G\d{1,2})`?\s*[-–]\s*`?(G\d{1,2})`?")

HERE = pathlib.Path(__file__).resolve().parent
RELEASE = HERE / "release.py"
SKILL = HERE.parent / "SKILL.md"


def subcommands(release_text: str) -> list[str]:
    return sorted(set(ADD_PARSER.findall(release_text)))


def undocumented_subcommands(release_text: str, skill_text: str) -> list[str]:
    missing = []
    for name in subcommands(release_text):
        if re.search(rf"release\.py\s+{re.escape(name)}\b", skill_text):
            continue
        if re.search(rf"`{re.escape(name)}`", skill_text):
            continue
        missing.append(name)
    return missing


def defined_gates(release_text: str) -> set[str]:
    return set(GATE_TOKEN.findall(release_text))


def cited_gates(skill_text: str) -> set[str]:
    cited = set(GATE_TOKEN.findall(skill_text))
    for low, high in GATE_RANGE.findall(skill_text):
        start, end = int(low[1:]), int(high[1:])
        if start <= end:
            cited.update(f"G{number}" for number in range(start, end + 1))
    return cited


def undefined_cited_gates(release_text: str, skill_text: str) -> list[str]:
    return sorted(cited_gates(skill_text) - defined_gates(release_text))


def self_test() -> int:
    release = 'add_parser("prepare")\nadd_parser("pack")\nG1 G2 G3 ok\n'
    skill = "Run `release.py prepare` then `release.py pack`. Gates `G1`-`G3` apply.\n"
    failures = []
    if undocumented_subcommands(release, skill):
        failures.append("a documented pair was rejected")
    if undefined_cited_gates(release, skill):
        failures.append("a prose gate range was read as undefined")
    if undocumented_subcommands(release + 'add_parser("audit")\n', skill) != ["audit"]:
        failures.append("an undocumented subcommand was accepted")
    if undefined_cited_gates(release, skill + "See `G99`.\n") != ["G99"]:
        failures.append("a cited gate with no definition was accepted")
    # The range must be expanded, not merely tolerated: G2 removed from the tool has to surface.
    if undefined_cited_gates('add_parser("prepare")\nadd_parser("pack")\nG1 G3 ok\n', skill) != ["G2"]:
        failures.append("a gate missing from the middle of a cited range was accepted")
    if failures:
        for failure in failures:
            print(f"SELF-TEST FAILED: {failure}", file=sys.stderr)
        return 1
    print("SELF-TEST PASSED: subcommand and gate references resolve in both directions")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    release_text = RELEASE.read_text(encoding="utf-8")
    skill_text = SKILL.read_text(encoding="utf-8")
    missing = undocumented_subcommands(release_text, skill_text)
    undefined = undefined_cited_gates(release_text, skill_text)
    print(
        f"subcommands={len(subcommands(release_text))} "
        f"gates-defined={len(defined_gates(release_text))} "
        f"gates-cited={len(cited_gates(skill_text))}"
    )
    for name in missing:
        print(f"ERROR: release.py subcommand {name!r} is not documented in SKILL.md", file=sys.stderr)
    for gate in undefined:
        print(f"ERROR: SKILL.md cites {gate}, which release.py does not define", file=sys.stderr)
    return 1 if (missing or undefined) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
