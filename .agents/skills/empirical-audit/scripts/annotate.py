#!/usr/bin/env python3
"""Insert ADMIT/RCR blocks above named tests.

Spec: {"production": ["<Runtime path>", ...], "annotations": {"<TestFile.cs>": {"<Test>": "<comment>"}}}

The production list is what makes a record checkable: an RCR line is a claim about a production
symbol, so the file it cites has to be named, and the tree it describes has to be the restored one.
"""
import json, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(os.environ.get("RCR_ROOT") or pathlib.Path(__file__).resolve().parents[4])
spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
if not isinstance(spec.get("production"), list) or not isinstance(spec.get("annotations"), dict):
    sys.exit('spec must be {"production": [...], "annotations": {"<TestFile.cs>": {"<Test>": "<comment>"}}}')


def is_clean(rel):
    """Ask the repository that owns the path: a host `git` reports anything below a gitlink clean."""
    path = (ROOT/rel).resolve()
    top = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    if not top:
        return False
    relative = str(path.relative_to(pathlib.Path(top)))
    return subprocess.run(["git", "-C", top, "diff", "--quiet", "HEAD", "--", relative]).returncode == 0


dirty = [rel for rel in spec["production"] if not is_clean(rel)]
if dirty:
    sys.exit(f"refusing to write RCR records while production is mutated: {dirty} -- restore first")

names = {pathlib.Path(rel).name for rel in spec["production"]}
for rel, blocks in spec["annotations"].items():
    for name, blk in blocks.items():
        cited = re.search(r"RCR:\s*(\S+\.cs)\b", blk)
        if cited and cited.group(1) not in names:
            sys.exit(f"{rel} :: {name} cites {cited.group(1)}, which is not listed under production")

total = 0
for rel, blocks in spec["annotations"].items():
    p = ROOT/rel; t = p.read_text(); n = 0
    for name, blk in blocks.items():
        # [Test]/[UnityTest] (+ optional extra attrs) then a signature declaring `name(`
        pat = re.compile(
            r"(?P<ind>[ \t]*)\[(?:Test|UnityTest)[^\]]*\]\n"
            r"(?P<mid>(?:[ \t]*\[[^\]]*\]\n)*)"
            r"(?P<sig>[ \t]*(?:public|private|protected|internal)[^\n]*?\b" + re.escape(name) + r"\s*\()")
        ms = list(pat.finditer(t))
        if len(ms) != 1:
            print(f"  !! {rel} :: {name}: {len(ms)} matches"); continue
        m = ms[0]; ind = m.group("ind")
        # Only scan THIS test's own attribute block (between [Test] and the signature).
        # A fixed character lookback reaches into the PREVIOUS test's comment and reports a
        # false "already annotated", silently skipping tests that have none of their own.
        if "// ADMIT:" in t[m.start("mid"):m.start("sig")]:
            print(f"  -- {rel} :: {name}: already annotated"); continue
        cmt = "\n".join(ind + l for l in blk.strip("\n").split("\n"))
        head = t[m.start():m.start("mid")]        # the [Test] line
        t = t[:m.start()] + head + cmt + "\n" + t[m.start("mid"):]
        n += 1
    p.write_text(t); total += n
    print(f"  {rel}: +{n}")
print(f"annotated {total}")
