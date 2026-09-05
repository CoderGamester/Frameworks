#!/usr/bin/env python3
"""Scan for the defects a scripted doc-comment edit introduces silently.

None of these fail a build and none fail a test. Every check below corresponds to a defect actually
self-inflicted during a scripted §6.6 pass, so run this after ANY bulk edit -- see Phase 5 of
SKILL.md.

    1  doc block placed after a member's attributes   -> attaches to nothing; member reads as undocumented forever
    2  doc block whose lines disagree on indentation  -> a helper prefixed the indent twice
    3  unbalanced <summary> inside one block          -> a truncated or doubled tag
    4  '/// <summary> Text' (stray leading space)     -> cosmetic drift from the house style
    5  UTF-8 BOM changed against HEAD                 -> read as utf-8-sig, written as utf-8

Usage:
    python3 .agents/skills/code-standards-audit/scripts/post-edit-scan.py
    python3 .agents/skills/code-standards-audit/scripts/post-edit-scan.py --baseline

Exit 0 when clean, 1 when anything is found.

`--baseline` records the current findings to .code-standards-baseline.json and treats them as
pre-existing on later runs, so a defect that predates this work does not mask a new one. Use it
once, deliberately: a growing baseline is a rule nobody obeys.
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
BASELINE = os.path.join(ROOT, ".code-standards-baseline.json")
SKIP_DIRS = ("Library", "obj", "bin", ".git")


def cs_files(root_rel):
    root = os.path.join(ROOT, root_rel)
    if not os.path.isdir(root):
        return
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in SKIP_DIRS]
        for f in fn:
            if f.endswith(".cs"):
                yield os.path.relpath(os.path.join(dp, f), ROOT)


def doc_blocks(lines):
    """Yield (start_index, [block lines]) for each contiguous /// run."""
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("///"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("///"):
                j += 1
            yield i, lines[i:j]
            i = j
        else:
            i += 1


def scan_text(rel, lines):
    out = []
    for i, l in enumerate(lines):
        if l.strip().startswith("///") and i > 0:
            prev = lines[i - 1].strip()
            if prev.startswith("[") and prev.endswith("]"):
                out.append(("doc-after-attribute", rel, i + 1,
                            "doc block sits between an attribute and the declaration"))
                break   # one report per file is enough to send someone looking
    for start, block in doc_blocks(lines):
        indents = sorted({len(x) - len(x.lstrip()) for x in block})
        if len(indents) > 1:
            out.append(("inconsistent-indent", rel, start + 1, f"indents={indents}"))
        joined = "\n".join(block)
        if len(re.findall(r"<summary>", joined)) != len(re.findall(r"</summary>", joined)):
            out.append(("unbalanced-summary", rel, start + 1, "open/close <summary> count differs"))
    for i, l in enumerate(lines):
        if re.search(r"/// <summary> \S", l):
            out.append(("summary-leading-space", rel, i + 1, l.strip()[:70]))
    return out


def head_bytes(rel, n=3):
    """First n bytes of rel at HEAD, honouring submodule boundaries. None when untracked."""
    d = os.path.dirname(rel)
    sub = None
    parts = rel.split(os.sep)
    if len(parts) > 2 and parts[0] == "Packages":
        sub = os.path.join(ROOT, parts[0], parts[1])
        inner = os.sep.join(parts[2:])
    else:
        sub, inner = ROOT, rel
    r = subprocess.run(["git", "show", f"HEAD:{inner}"], cwd=sub, capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout[:n]


def scan_bom(rel):
    disk = open(os.path.join(ROOT, rel), "rb").read(3)
    head = head_bytes(rel)
    if head is None:
        return []
    BOM = b"\xef\xbb\xbf"
    if (disk == BOM) != (head == BOM):
        was = "present" if head == BOM else "absent"
        now = "present" if disk == BOM else "absent"
        return [("bom-changed", rel, 1, f"HEAD={was} disk={now}")]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true",
                    help="record current findings as pre-existing")
    ap.add_argument("--changed-only", action="store_true",
                    help="only files differing from HEAD (faster; misses collateral damage)")
    args = ap.parse_args()

    targets = list(cs_files("Packages")) + list(cs_files("Assets"))
    if args.changed_only:
        changed = set()
        for cwd in [ROOT] + [os.path.join(ROOT, "Packages", d)
                             for d in os.listdir(os.path.join(ROOT, "Packages"))
                             if os.path.isdir(os.path.join(ROOT, "Packages", d))]:
            r = subprocess.run(["git", "diff", "--name-only", "--", "*.cs"],
                               cwd=cwd, capture_output=True, text=True)
            base = os.path.relpath(cwd, ROOT)
            for line in r.stdout.split("\n"):
                if line.strip():
                    changed.add(os.path.normpath(os.path.join(base, line.strip())))
        targets = [t for t in targets if t in changed]

    findings = []
    for rel in targets:
        lines = open(os.path.join(ROOT, rel), encoding="utf-8-sig", errors="replace").read().split("\n")
        findings += scan_text(rel, lines)
        findings += scan_bom(rel)

    if args.baseline:
        with open(BASELINE, "w") as fh:
            json.dump([list(f) for f in findings], fh, indent=1)
        print(f"recorded {len(findings)} pre-existing finding(s) to {os.path.basename(BASELINE)}")
        print("These will be treated as pre-existing on later runs. Keep this list shrinking.")
        return 0

    known = set()
    if os.path.exists(BASELINE):
        known = {tuple(x) for x in json.load(open(BASELINE))}

    new = [f for f in findings if tuple(f) not in known]
    pre = len(findings) - len(new)

    print(f"scanned {len(targets)} .cs files")
    by_kind = {}
    for kind, rel, ln, detail in new:
        by_kind.setdefault(kind, []).append((rel, ln, detail))
    for kind in sorted(by_kind):
        print(f"\n{kind} ({len(by_kind[kind])}):")
        for rel, ln, detail in by_kind[kind][:20]:
            print(f"  {rel}:{ln}  {detail}")
        if len(by_kind[kind]) > 20:
            print(f"  ... and {len(by_kind[kind]) - 20} more")

    if pre:
        print(f"\n({pre} pre-existing finding(s) suppressed via baseline)")
    if new:
        print(f"\nFAIL: {len(new)} new finding(s). None of these break a build or a test —")
        print("they are exactly the damage a scripted edit does invisibly.")
        return 1
    print("\nPASS: no new findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
