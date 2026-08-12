#!/usr/bin/env python3
"""Dialect-agnostic Keep-a-Changelog section extractor for GameLovers UPM packages.

The six packages use four different sub-heading dialects:
    **New**:  / **Changed**: / **Fixed**: / **Docs**:   (canonical, AGENTS.md 6.5)
    **New**   / **Fixed**                                (statechart, no colon)
    **Changes**: / **Fixes**:  + `---` rules             (gamedata, plural)
    ### Added / ### Changed                              (mobileservices, canonical KaC)

None of that needs special handling -- the section body is copied verbatim, which is
exactly what the published release bodies do. The real hazards are structural:

  * CRLF: services, statechart, googlesheetimporter are CRLF; the others are LF.
    `.gitattributes` has no `text=auto`, so this is committed as-is. Without
    normalisation, `$`-anchored regexes never match and stray \\r lands in the
    release body.
  * gamedata separates versions with `---` thematic breaks, which must not leak
    into the extracted body.
  * The last section in the file ends at EOF, not at a following heading.

Usage:
    changelog.py section [--any] <CHANGELOG.md> <version>  # print the section body
    changelog.py prev-tag <version> <tag>...               # resolve the compare base
    changelog.py validate-pending <CHANGELOG.md> <version> <date> [--baseline FILE]
    changelog.py rewrite-pending <CHANGELOG.md> <version> <date> <BODY.md>

`section` asserts the version is the file's newest section (gates G8/G9). Pass
`--any` to read a historical section instead, as `audit` and `reattest` must.
"""

from __future__ import annotations

import pathlib
import re
import sys

# All 127 historical headings are canonically formatted. No `## [Unreleased]`,
# no code fences anywhere in any of the six files, so no false positives.
HEADING = re.compile(r"^##\s+\[(?P<ver>[^\]\s]+)\]\s*-\s*(?P<date>\d{4}-\d{2}-\d{2})\s*$")
RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")  # markdown thematic break
UNRELEASED = re.compile(r"^##\s+\[Unreleased\]\s*$", re.MULTILINE | re.IGNORECASE)
RAW_HEADING = re.compile(
    r"^##\s+\[(?P<ver>[^\]\s]+)\]\s*-\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\r?$",
    re.MULTILINE,
)
RAW_UNRELEASED = re.compile(r"^##\s+\[Unreleased\]\s*\r?$", re.MULTILINE | re.IGNORECASE)
CANONICAL_LABEL = re.compile(r"^\*\*(?:New|Changed|Fixed|Removed|Migration|Docs)\*\*:$")
LABEL_LIKE = re.compile(r"^(?:###\s+\S.*|\*\*[^*]+\*\*:?)$")


class ChangelogError(ValueError):
    """A pending changelog violates the release-note contract."""


def read(path: str | pathlib.Path) -> str:
    """Read a CHANGELOG, stripping any BOM and normalising CRLF/CR to LF."""
    text = pathlib.Path(path).read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def semver(version: str) -> tuple[int, int, int] | None:
    """Parse bare X.Y.Z. Returns None for anything else.

    Every historical tag is bare MAJOR.MINOR.PATCH with no prerelease or build
    suffix, so integer-tuple comparison is exact and needs no semver library.
    """
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def sections(path: str | pathlib.Path) -> list[dict]:
    """Return every `## [X.Y.Z] - YYYY-MM-DD` section, in file order."""
    lines = read(path).split("\n")
    heads = [(i, m) for i, line in enumerate(lines) if (m := HEADING.match(line))]

    out = []
    for n, (i, m) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = lines[i + 1 : end]

        while body and not body[0].strip():  # leading blanks
            body.pop(0)
        while body and (not body[-1].strip() or RULE.match(body[-1])):  # trailing blanks + rules
            body.pop()

        out.append(
            {
                "version": m["ver"],
                "date": m["date"],
                "line": i + 1,
                "body": "\n".join(body),
            }
        )
    return out


def section_for(path: str | pathlib.Path, version: str, require_newest: bool = True) -> dict:
    """Extract the section for `version`.

    With `require_newest` (the release path) this doubles as CHANGELOG-side gates
    G8/G9: the version must be the file's first section AND its highest version.
    Pass `require_newest=False` to read a historical section -- needed by `audit`
    and `reattest`, where by definition newer sections sit above the target.
    """
    secs = sections(path)
    if not secs:
        die(f"D1: no '## [X.Y.Z] - YYYY-MM-DD' headings found in {path}")

    hits = [s for s in secs if s["version"] == version]
    if not hits:
        die(
            f"D2: no '## [{version}]' heading in {path}. Newest heading is "
            f"'## [{secs[0]['version']}] - {secs[0]['date']}' at line {secs[0]['line']}."
        )
    if len(hits) > 1:
        die(
            f"D3: '## [{version}]' appears {len(hits)} times in {path} "
            f"(lines {[s['line'] for s in hits]}); duplicate section."
        )

    sec = hits[0]
    if require_newest:
        if secs[0]["version"] != version:
            die(
                f"D4: '## [{version}]' is at line {sec['line']} but the file's first section is "
                f"'## [{secs[0]['version']}]' at line {secs[0]['line']} -- new section inserted "
                f"in the wrong place."
            )

        ranked = sorted(
            (s for s in secs if semver(s["version"])),
            key=lambda s: semver(s["version"]),
            reverse=True,
        )
        if ranked and ranked[0]["version"] != version:
            die(
                f"D5: {version} is not the highest version in {path} "
                f"(found {ranked[0]['version']} at line {ranked[0]['line']})."
            )

    if not sec["body"].strip():
        die(f"D6: section '## [{version}]' at line {sec['line']} has an empty body.")
    if "## [" in sec["body"]:
        die(f"D7: extracted body for {version} contains a '## [' heading -- boundary detection broke.")

    return sec


def prev_tag(tags: list[str], version: str) -> str | None:
    """Highest remote tag strictly below `version`, or None for a first release.

    Deliberately NOT `git describe` (walks local history, can name an unrelated
    ancestor) and NOT latest-by-date (works today only by coincidence).
    """
    want = semver(version)
    if want is None:
        die(f"D8: version '{version}' is not bare X.Y.Z.")

    candidates = []
    for tag in tags:
        parsed = semver(tag)
        if parsed is None:
            print(f"warn: ignoring non-SemVer remote tag '{tag}'", file=sys.stderr)
            continue
        if parsed < want:
            candidates.append((parsed, tag))

    return max(candidates)[1] if candidates else None


def release_body(section: dict, repo: str, version: str, prev: str | None) -> str:
    """Assemble the release body in the established house shape.

    Matches the live 2.1.1 body exactly: heading, blank, verbatim section, blank,
    compare link. The Full Changelog line is omitted when there is no predecessor.
    """
    body = f"## What's Changed\n\n{section['body']}\n"
    if prev:
        body += f"\n**Full Changelog**: https://github.com/{repo}/compare/{prev}...{version}\n"
    return body


def _historical_suffix_bytes(raw: bytes, pending_version: str) -> str:
    """Return published history, whether or not the baseline has the pending entry."""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    headings = list(RAW_HEADING.finditer(text))
    if not headings:
        return ""
    first_historical = 1 if headings[0]["ver"] == pending_version else 0
    return text[headings[first_historical].start() :] if len(headings) > first_historical else ""


def _historical_suffix(path: str | pathlib.Path, pending_version: str) -> str:
    return _historical_suffix_bytes(pathlib.Path(path).read_bytes(), pending_version)


def validate_pending(
    path: str | pathlib.Path,
    version: str,
    expected_date: str | None = None,
    baseline: str | pathlib.Path | None = None,
    baseline_bytes: bytes | None = None,
) -> dict:
    """Validate the editable release entry without rewriting historical entries."""
    text = read(path)
    if UNRELEASED.search(text):
        raise ChangelogError(
            "pending changelog still contains an Unreleased heading; merge it into "
            f"the [{version}] release entry"
        )

    secs = sections(path)
    hits = [section for section in secs if section["version"] == version]
    if len(hits) != 1:
        raise ChangelogError(
            f"expected exactly one [{version}] release entry, found {len(hits)}"
        )
    section = hits[0]
    if not secs or secs[0]["version"] != version:
        raise ChangelogError(f"[{version}] must be the first versioned release entry")
    ranked = sorted(
        (candidate for candidate in secs if semver(candidate["version"])),
        key=lambda candidate: semver(candidate["version"]),
        reverse=True,
    )
    if ranked and ranked[0]["version"] != version:
        raise ChangelogError(
            f"[{version}] is not the highest version; found [{ranked[0]['version']}]"
        )
    if expected_date and section["date"] != expected_date:
        raise ChangelogError(
            f"[{version}] is dated {section['date']}; expected {expected_date}"
        )
    if not section["body"].strip():
        raise ChangelogError(f"[{version}] has an empty release body")

    labels = [line.strip() for line in section["body"].splitlines() if LABEL_LIKE.match(line.strip())]
    invalid = [label for label in labels if not CANONICAL_LABEL.match(label)]
    if invalid or not labels:
        detail = ", ".join(invalid) if invalid else "none found"
        raise ChangelogError(
            "pending entries must use canonical labels "
            "(**New**:, **Changed**:, **Fixed**:, **Removed**:, **Migration**:, **Docs**:); "
            f"invalid labels: {detail}"
        )

    if baseline is not None and baseline_bytes is not None:
        raise ChangelogError("provide baseline or baseline_bytes, not both")
    expected_history = None
    if baseline is not None:
        expected_history = _historical_suffix(baseline, version)
    elif baseline_bytes is not None:
        expected_history = _historical_suffix_bytes(baseline_bytes, version)
    if expected_history is not None and _historical_suffix(path, version) != expected_history:
        raise ChangelogError("historical release entries differ from the baseline")
    return section


def rewrite_pending(
    path: str | pathlib.Path,
    version: str,
    date: str,
    body: str,
) -> None:
    """Replace only Unreleased/current-version prose, preserving file byte conventions."""
    target = pathlib.Path(path)
    raw = target.read_bytes()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    payload = raw[len(bom) :]
    text = payload.decode("utf-8")
    newline = "\r\n" if b"\r\n" in payload else "\n"
    ended_with_newline = text.endswith(("\n", "\r"))

    headings = list(RAW_HEADING.finditer(text))
    targets = [match for match in headings if match["ver"] == version]
    if len(targets) != 1:
        raise ChangelogError(
            f"rewrite requires exactly one existing [{version}] entry, found {len(targets)}"
        )
    target_heading = targets[0]
    if headings[0] != target_heading:
        raise ChangelogError(f"[{version}] must be the first versioned entry before rewriting")

    unreleased = [match for match in RAW_UNRELEASED.finditer(text) if match.start() < target_heading.start()]
    if len(unreleased) > 1:
        raise ChangelogError("multiple Unreleased headings found")
    start = unreleased[0].start() if unreleased else target_heading.start()
    following = next((match for match in headings if match.start() > target_heading.start()), None)
    suffix = text[following.start() :] if following else ""
    prefix = text[:start]

    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not normalized_body.strip():
        raise ChangelogError("replacement body is empty")
    normalized_body = normalized_body.replace("\n", newline)
    pending = f"## [{version}] - {date}{newline}{newline}{normalized_body}"
    if suffix:
        pending += newline + newline
    elif ended_with_newline:
        pending += newline

    target.write_bytes(bom + (prefix + pending + suffix).encode("utf-8"))


def die(message: str) -> None:
    print(f"FATAL {message}", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    command = argv[1]

    if command == "section":
        args = [a for a in argv[2:] if a != "--any"]
        if len(args) != 2:
            die("usage: changelog.py section [--any] <CHANGELOG.md> <version>")
        print(section_for(args[0], args[1], require_newest="--any" not in argv)["body"])
        return 0

    if command == "prev-tag":
        if len(argv) < 3:
            die("usage: changelog.py prev-tag <version> <tag>...")
        result = prev_tag(argv[3:], argv[2])
        print(result if result else "")
        return 0

    if command == "validate-pending":
        args = argv[2:]
        baseline = None
        if "--baseline" in args:
            index = args.index("--baseline")
            if index + 1 >= len(args):
                die("--baseline requires a file")
            baseline = args[index + 1]
            del args[index : index + 2]
        if len(args) != 3:
            die(
                "usage: changelog.py validate-pending <CHANGELOG.md> <version> "
                "<YYYY-MM-DD> [--baseline FILE]"
            )
        try:
            section = validate_pending(args[0], args[1], args[2], baseline=baseline)
        except ChangelogError as exc:
            die(str(exc))
        print(
            f"VALID [{section['version']}] {section['date']} at line {section['line']}; "
            f"historical baseline={'checked' if baseline else 'not supplied'}"
        )
        return 0

    if command == "rewrite-pending":
        if len(argv) != 6:
            die(
                "usage: changelog.py rewrite-pending <CHANGELOG.md> <version> "
                "<YYYY-MM-DD> <BODY.md>"
            )
        try:
            body = pathlib.Path(argv[5]).read_text(encoding="utf-8-sig")
            rewrite_pending(argv[2], argv[3], argv[4], body)
            section = validate_pending(argv[2], argv[3], argv[4])
        except ChangelogError as exc:
            die(str(exc))
        print(f"REWROTE [{section['version']}] {section['date']} at line {section['line']}")
        return 0

    die(f"unknown subcommand '{command}'")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
