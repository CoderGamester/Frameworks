#!/usr/bin/env python3
"""RCR verify harness. Mutate one line -> run filtered suite -> record reds -> revert.
Matches on NUnit methodname+classname, so duplicate bare names across fixtures and
parameterized [TestCase] rows (named "Method(args)") resolve correctly."""
import json, os, pathlib, re, subprocess, sys, shutil, time

# Repo-relative so the harness runs on any checkout: scripts -> empirical-audit -> skills -> .agents.
ROOT  = pathlib.Path(os.environ.get("RCR_ROOT") or pathlib.Path(__file__).resolve().parents[4])
if not (ROOT/"Packages").is_dir():
    sys.exit(f"RCR_ROOT does not look like the Frameworks host: {ROOT}")
UNITY = os.environ.get("RCR_UNITY") or str(pathlib.Path.home()/".unity/bin/unity")
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
    # Accept a short OR fully-qualified fixture. Requiring the short form silently produced
    # NOT-FOUND for every row in a spec that used fully-qualified names -- indistinguishable
    # from "the test does not exist".
    def fx(r): return not fixture or r[0] == fixture or r[0].split('.')[-1] == fixture.split('.')[-1]
    hits = [r for r in rows if r[1] == test and fx(r)]
    if not hits:  # parameterized fallback: NUnit may only give name="Method(args)"
        hits = [r for r in rows if (r[2] == test or r[2].startswith(test + "(")) and fx(r)]
    return hits

def ident(r): return f"{r[0].split('.')[-1]}.{r[2]}"

def owning_repo(path):
    """The repository that owns this path. A host `git` sees nothing below a gitlink."""
    out = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    return pathlib.Path(out.stdout.strip()) if out.returncode == 0 else ROOT

def porcelain(rels):
    """git status of each production path, asked of the repository that owns it."""
    state = {}
    for rel in rels:
        path = (ROOT/rel).resolve()
        top = owning_repo(path)
        try:
            relative = str(path.relative_to(top))
        except ValueError:
            relative = str(path)
        out = subprocess.run(["git", "-C", str(top), "status", "--porcelain", "--", relative],
                             capture_output=True, text=True)
        state[rel] = out.stdout
    return state

def run_dir(specfile):
    """One directory per attempt under the location AGENTS.md reserves for mutation records."""
    d = ROOT/".test-all"/"rcr"/f"{time.strftime('%Y%m%dT%H%M%S')}-{pathlib.Path(specfile).stem}"
    d.mkdir(parents=True, exist_ok=True)
    print(f"run id: {d.relative_to(ROOT)}")
    return d

def main(specfile):
    spec  = json.loads(pathlib.Path(specfile).read_text())
    mode, filt = spec["mode"], spec["filter"]
    muts  = spec["mutations"]
    files = {m.get("file", spec.get("file")) for m in muts}
    backups = {p: (ROOT/p).read_text() for p in files}
    RUN = run_dir(specfile)
    for p in files: shutil.copy(ROOT/p, RUN/f"{pathlib.Path(p).name}.orig")
    before = porcelain(files)

    base = run(mode, filt, str(RUN/"base.xml"))
    if base is None: print("!! baseline produced no report"); return 1
    bad = [ident(r) for r in base if r[3] != "Passed"]
    if bad: print(f"!! baseline not green: {bad[:8]}"); return 1
    print(f"baseline green: {len(base)} test cases\n")
    basered = {ident(r) for r in base if r[3] != "Passed"}

    results = []
    rc = 0
    try:
      for i, m in enumerate(muts, 1):
        t0, rel = time.time(), m.get("file", spec.get("file"))
        src, fixture = ROOT/rel, m.get("fixture")
        cur = src.read_text()
        if cur.count(m["find"]) != 1:
            results.append((m["test"], "BAD-ANCHOR", f'{cur.count(m["find"])} matches'))
            print(f"[{i}/{len(muts)}] BAD-ANCHOR    {m['test']}"); continue
        src.write_text(cur.replace(m["find"], m["replace"], 1))
        # The run can time out after 30 minutes or be interrupted; without the finally the file
        # stays mutated and the restoration assertion below never executes to say so.
        try:
            rows = run(mode, filt, str(RUN/f"m{i}.xml"))
        finally:
            src.write_text(backups[rel])
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
    finally:
        for p, b in backups.items():
            if (ROOT/p).read_text() != b:
                (ROOT/p).write_text(b); print(f"!! restored {p} after an interrupted run"); rc = 2
        after = porcelain(files)
        drifted = {k: after[k] for k in after if after[k] != before[k]}
        if drifted:
            print(f"!! production working tree changed and was not restored: {drifted}"); rc = 2
        print(f"\nall {len(backups)} production file(s) restored byte-identical\n" if rc == 0
              else "\nRESTORATION REQUIRED INTERVENTION\n")
    ok = sum(1 for _, v, _ in results if v == "RED-OK")
    print(f"RED-OK: {ok}/{len(results)}")
    for t, v, d in results:
        if v != "RED-OK": print(f"  {v}: {t} — {d}")
    (RUN/"results.json").write_text(json.dumps(results, indent=1))
    return rc

if __name__ == "__main__": sys.exit(main(sys.argv[1]))
