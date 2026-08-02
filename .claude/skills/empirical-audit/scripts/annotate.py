#!/usr/bin/env python3
"""Insert ADMIT/RCR blocks above named tests. Spec: {"file": {"TestName": "comment text"}}"""
import json, pathlib, re, sys
ROOT = pathlib.Path("/Users/miguel.cartier/Desktop/Frameworks")
spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
total = 0
for rel, blocks in spec.items():
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
        if "// ADMIT:" in t[max(0,m.start()-400):m.start("sig")]:
            print(f"  -- {rel} :: {name}: already annotated"); continue
        cmt = "\n".join(ind + l for l in blk.strip("\n").split("\n"))
        head = t[m.start():m.start("mid")]        # the [Test] line
        t = t[:m.start()] + head + cmt + "\n" + t[m.start("mid"):]
        n += 1
    p.write_text(t); total += n
    print(f"  {rel}: +{n}")
print(f"annotated {total}")
