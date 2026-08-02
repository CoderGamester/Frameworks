#!/usr/bin/env python3
"""RCR verify harness. Mutate one line -> run filtered suite -> record reds -> revert.
Matches on NUnit methodname+classname, so duplicate bare names across fixtures and
parameterized [TestCase] rows (named "Method(args)") resolve correctly."""
import json, pathlib, re, subprocess, sys, shutil, time

ROOT  = pathlib.Path("/Users/miguel.cartier/Desktop/Frameworks")
UNITY = str(pathlib.Path.home()/".unity/bin/unity")
CASE  = re.compile(r"<test-case\b([^>]*)>")
ATTR  = re.compile(r'\b(\w+)="([^"]*)"')

def run(mode, filt, out):
    p = pathlib.Path(out)
    if p.exists(): p.unlink()                     # never read a stale report
    for _ in range(3):
        subprocess.run([UNITY,"test","--mode",mode,"--filter",filt,"--output",out],
                       cwd=ROOT, capture_output=True, timeout=1800)
        if p.exists(): break
        time.sleep(20)
    if not p.exists(): return None
    out_rows = []
    for m in CASE.finditer(p.read_text()):
        a = dict(ATTR.findall(m.group(1)))
        out_rows.append((a.get("classname",""), a.get("methodname",a.get("name","")),
                         a.get("name",""), a.get("result","")))
    return out_rows

def sel(rows, test, fixture):
    """Rows for this mutation's target: methodname match + optional fixture suffix match."""
    hits = [r for r in rows if r[1] == test and (not fixture or r[0].split('.')[-1] == fixture)]
    if not hits:  # parameterized fallback: NUnit may only give name="Method(args)"
        hits = [r for r in rows if (r[2] == test or r[2].startswith(test + "("))
                and (not fixture or r[0].split('.')[-1] == fixture)]
    return hits

def ident(r): return f"{r[0].split('.')[-1]}.{r[2]}"

def main(specfile):
    spec  = json.loads(pathlib.Path(specfile).read_text())
    mode, filt = spec["mode"], spec["filter"]
    muts  = spec["mutations"]
    files = {m.get("file", spec.get("file")) for m in muts}
    backups = {p: (ROOT/p).read_text() for p in files}
    for p in files: shutil.copy(ROOT/p, f"/tmp/rcrharness/{pathlib.Path(p).name}.orig")

    base = run(mode, filt, "/tmp/rcrharness/base.xml")
    if base is None: print("!! baseline produced no report"); return 1
    bad = [ident(r) for r in base if r[3] != "Passed"]
    if bad: print(f"!! baseline not green: {bad[:8]}"); return 1
    print(f"baseline green: {len(base)} test cases\n")
    basered = {ident(r) for r in base if r[3] != "Passed"}

    results = []
    for i, m in enumerate(muts, 1):
        t0, rel = time.time(), m.get("file", spec.get("file"))
        src, fixture = ROOT/rel, m.get("fixture")
        cur = src.read_text()
        if cur.count(m["find"]) != 1:
            results.append((m["test"], "BAD-ANCHOR", f'{cur.count(m["find"])} matches'))
            print(f"[{i}/{len(muts)}] BAD-ANCHOR    {m['test']}"); continue
        src.write_text(cur.replace(m["find"], m["replace"], 1))
        rows = run(mode, filt, f"/tmp/rcrharness/m{i}.xml")
        src.write_text(backups[rel])                            # revert immediately
        if rows is None:
            verdict, detail = "NO-RESULTS", "unity produced no report after 3 attempts"
        else:
            target = sel(rows, m["test"], fixture)
            if not target:
                verdict, detail = "NOT-FOUND", f"no test case matched (fixture={fixture})"
            else:
                red = {ident(r) for r in rows if r[3] != "Passed"} - basered
                tid = {ident(r) for r in target}
                if tid & red:
                    verdict = "RED-OK"
                    others  = sorted(red - tid)
                    detail  = f"also red: {others}" if others else "isolated"
                else:
                    verdict = "STAYED-GREEN"
                    detail  = f"red instead: {sorted(red)}" if red else "nothing went red"
        results.append((m["test"], verdict, detail))
        print(f"[{i}/{len(muts)}] {verdict:13} {m['test']}  ({time.time()-t0:.0f}s)  {detail}")

    for p, b in backups.items():
        assert (ROOT/p).read_text() == b, f"NOT RESTORED: {p}"
    print(f"\nall {len(backups)} production file(s) restored byte-identical\n")
    ok = sum(1 for _, v, _ in results if v == "RED-OK")
    print(f"RED-OK: {ok}/{len(results)}")
    for t, v, d in results:
        if v != "RED-OK": print(f"  {v}: {t} — {d}")
    pathlib.Path("/tmp/rcrharness/" + pathlib.Path(specfile).stem + "-results.json").write_text(json.dumps(results, indent=1))
    return 0

if __name__ == "__main__": sys.exit(main(sys.argv[1]))
