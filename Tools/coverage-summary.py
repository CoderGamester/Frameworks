#!/usr/bin/env python3
"""Print the coverage split that actually means something.

The combined figure is roughly half Editor code, which sits near 0% *by policy*
(each Tests/AGENTS.md section 13 records EditorWindow / PropertyDrawer / UIToolkit
classes as ACCEPTED (iii) harness-impossible). Steering by the combined number
means steering by a figure that can never move. Runtime is the headline.

Reads Report/Summary.xml -- never the numbered Frameworks-opencov files, where
TestCoverageResults_0000.xml is a zero-hit structural pre-pass that must not be
summed with _0001.
"""
import pathlib
import re
import sys

REPORT = pathlib.Path(__file__).resolve().parent.parent / "CodeCoverage" / "Report" / "Summary.xml"


def main() -> int:
    if not REPORT.exists():
        print(f"no report at {REPORT} -- run Tools/coverage.sh first", file=sys.stderr)
        return 1

    text = REPORT.read_text()
    generated = re.search(r"<Generatedon>([^<]+)</Generatedon>", text).group(1)

    rows = [
        (m.group(1), int(m.group(2)), int(m.group(3)))
        for m in re.finditer(
            r'<Assembly name="([^"]+)"[^>]*coveredlines="(\d+)" coverablelines="(\d+)"', text
        )
    ]
    leaked = [n for n, _, _ in rows if re.search(r"Test|Sample", n)]
    runtime = [r for r in rows if not r[0].endswith(".Editor")]
    editor = [r for r in rows if r[0].endswith(".Editor")]

    def pct(group):
        cov = sum(r[1] for r in group)
        able = sum(r[2] for r in group)
        return cov, able, (100 * cov / able if able else 0.0)

    print(f"generated {generated}   {len(rows)} assemblies")
    if leaked:
        print(f"\n  WARNING: test/sample assemblies leaked into the report: {leaked}")
        print("  the assemblyFilters in Tools/coverage.sh are not doing their job\n")

    print(f"\n{'assembly':<44}{'cov%':>7}{'covered':>9}{'coverable':>11}")
    for name, cov, able in sorted(rows, key=lambda r: -r[2]):
        share = 100 * cov / able if able else 0.0
        print(f"{name:<44}{share:>6.1f}%{cov:>9}{able:>11}")

    rc, ra, rp = pct(runtime)
    ec, ea, ep = pct(editor)
    ac, aa, ap = pct(rows)

    print(f"\n{'':-<71}")
    print(f"{'RUNTIME (the headline)':<44}{rp:>6.1f}%{rc:>9}{ra:>11}")
    print(f"{'EDITOR  (accepted harness-impossible)':<44}{ep:>6.1f}%{ec:>9}{ea:>11}")
    print(f"{'combined (do not steer by this)':<44}{ap:>6.1f}%{ac:>9}{aa:>11}")
    print(
        f"\nEditor is {100 * ea / aa:.1f}% of all coverable lines, which is what drags "
        f"the combined figure from {rp:.1f}% down to {ap:.1f}%."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
