#!/usr/bin/env python3
"""Audit C# sources against the XML-documentation rules in root AGENTS.md §6.6.

Usage:
    python3 Tools/style-audit.py                 # gate: nonzero exit on violations
    python3 Tools/style-audit.py --advisory      # also print the noisy ordering report
    python3 Tools/style-audit.py --json out.json # machine-readable findings
    python3 Tools/style-audit.py --list A B      # print every finding for these rule ids

WHAT IS GATED (a violation; exit 1)
    A  enum value carrying `/// <summary>` instead of an inline `//`
    B  a *private* field carrying a doc comment
    C  any constructor carrying a doc comment (all accesses)
    D  any other private member carrying a doc comment
    E  public/protected/internal operator with no doc
    F  public/protected/internal type with no doc
    G  public/protected/internal property with no doc
    H  public/protected/internal method with no doc
    I  public/protected/internal event with no doc
    J  a doc block with <remarks> but no <summary>
    K  <param>/<returns>/<typeparam>/<exception> outside public consumer-facing API
    M  single-line <summary> on a method/type that IS public consumer-facing API
    N  an `internal` method declared after a `private` one in the same type

NOT GATED, BY DESIGN
    Properties/events/fields may use either the single-line or the block form
    (§6.6 says "a single line when the content fits"), so form is not checked for
    them. `Tests/` and `Samples~/` are exempt outright and are counted for
    visibility only. Member ORDERING beyond rule N is advisory (--advisory): the
    check does not model §6.6's "Unity MonoBehaviour methods" slot, so CreateGUI /
    Dispose / OnValidate false-positive. Rule N alone is exact and is gated.

"Public consumer-facing API" is operationalised as: a `public` or `protected`
declaration in a Runtime/ assembly whose every enclosing type is also public or
protected. Editor/ assemblies are tooling and `internal` is not a consumer surface,
so both may use the compact single-line form and neither may carry <param> tags.

Accessibility is EFFECTIVE, not declared: interface members carry no modifier and
default to public, so a member of an `internal` interface reports as `public` yet is
unreachable outside the assembly. Rules K and M therefore test the narrowest of the
member's own access and all its enclosing types' — without this, every member of
`IHapticsBackend` / `IGameNotificationsPlatform` / `ITransitionInternal` would be
misjudged as consumer-facing API.

KNOWN LIMITATIONS (affect displayed names, not counts)
  * A method whose return type is generic renders its name as the type
    (`UniTask<T> OpenUiAsync(...)` -> "UniTask"). File and line are correct.
  * K cannot detect "an implementation repeated <param> instead of using
    <inheritdoc />" -- that needs cross-assembly type resolution. Such cases are
    reported only when the declaration is itself non-consumer-facing.

The tokenizer was cross-checked against independent greps: interfaces 127/127
exact, enums 27/27 exact (34 grep hits minus 7 log/codegen strings), classes 562
vs 567 grep (grep also matches `where T : class`).
"""
import argparse
import collections
import json
import os
import re
import sys

RULESET_VERSION = "AGENTS.md §6.6 as of 2026-08-04"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_ROOTS = ("Packages", "Assets")
EXEMPT_AREAS = ("Tests", "Samples~", "Assets")

TYPE_KINDS = ("class", "struct", "interface", "enum", "record")
ACCESS = ("public", "private", "protected", "internal")
MODS = ("static", "abstract", "virtual", "override", "sealed", "readonly", "const",
        "async", "extern", "unsafe", "new", "partial", "volatile", "event", "delegate",
        "implicit", "explicit", "fixed", "required", "ref")
CONTROL = {"if", "else", "for", "foreach", "while", "do", "switch", "case", "default",
           "try", "catch", "finally", "using", "lock", "return", "throw", "yield",
           "break", "continue", "goto", "checked", "unchecked", "await", "when", "nameof",
           "typeof", "sizeof", "get", "set", "add", "remove", "value", "this", "base"}

RULE_TITLES = {
    "A": "enum value uses /// instead of inline //",
    "B": "private field carries a doc comment",
    "C": "constructor carries a doc comment",
    "D": "private member carries a doc comment",
    "E": "operator missing doc",
    "F": "type missing doc",
    "G": "property missing doc",
    "H": "method missing doc",
    "I": "event missing doc",
    "J": "<remarks> without <summary>",
    "K": "<param>/<returns>/etc. outside public consumer API",
    "M": "single-line <summary> on public consumer-facing method/type",
    "N": "internal method declared after a private one",
}


# --------------------------------------------------------------------------- parse
def preprocess(text):
    """Return (stream, docs): a (char, line) stream with comments/strings neutralised,
    and {line: text} for every `///` line."""
    stream, docs = [], {}
    line, i, n = 1, 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            stream.append((" ", line - 1))
            i += 1
            continue
        if c == "/" and i + 1 < n:
            if text[i + 1] == "/":
                j = text.find("\n", i)
                j = n if j == -1 else j
                seg = text[i:j]
                if seg.startswith("///"):
                    docs[line] = seg.strip()
                i = j
                continue
            if text[i + 1] == "*":
                j = text.find("*/", i + 2)
                j = n if j == -1 else j + 2
                line += text.count("\n", i, j)
                stream.append((" ", line))
                i = j
                continue
        if c == '"' and text[i - 1:i] == "@":
            j = i + 1
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            line += text.count("\n", i, j)
            stream.append(('"', line))
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "\n":
                    break
                j += 1
            stream.append(('"', line))
            i = j + 1
            continue
        if c == "'":
            j = i + 1
            while j < n and text[j] != "'":
                if text[j] == "\\":
                    j += 2
                    continue
                j += 1
            stream.append(("'", line))
            i = j + 1
            continue
        if c == "#":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        stream.append((c, line))
        i += 1
    return stream, docs


def strip_attrs(head):
    h = head.strip()
    while h.startswith("["):
        d = 0
        for i, ch in enumerate(h):
            if ch == "[":
                d += 1
            elif ch == "]":
                d -= 1
                if d == 0:
                    h = h[i + 1:].strip()
                    break
        else:
            break
    return h


def top_index(head, token):
    """Index of `token` at bracket depth 0, else -1. The token test must precede the
    depth update or a search for '(' can never match."""
    d = i = 0
    while i < len(head):
        if d == 0 and head.startswith(token, i):
            return i
        ch = head[i]
        if ch in "([":
            d += 1
        elif ch in ")]":
            d -= 1
        i += 1
    return -1


def access_of(head, owner_kind):
    acc = set()
    for t in re.findall(r'[A-Za-z_]\w*', head.split("(")[0]):
        if t in ACCESS:
            acc.add(t)
        elif t in MODS or t in TYPE_KINDS:
            continue
        else:
            break
    if not acc:
        return "public" if owner_kind == "interface" else ("internal" if owner_kind is None else "private")
    for a in ("protected", "public", "internal"):
        if a in acc:
            return a
    return "private"


class Decl:
    __slots__ = ("kind", "name", "access", "line", "path", "doc", "owner", "owner_kind", "raw",
                 "enclosing")


def parse(path, rel):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    stream, docs = preprocess(text)
    decls, stack = [], []
    depth = bdepth = 0
    head, head_line, arrow = "", None, -1

    def emit(kind, name, acc, ln, body, owner, owner_kind, doclines):
        d = Decl()
        d.kind, d.name, d.access, d.line, d.path = kind, name, acc, ln, rel
        d.doc, d.owner, d.owner_kind, d.raw = doclines, owner, owner_kind, body[:200]
        # Effective accessibility is bounded by every enclosing type: a `public` member of an
        # `internal` interface is not reachable outside the assembly, so it is not consumer API.
        d.enclosing = tuple(e.get("access", "public") for e in stack if e["kind"] in TYPE_KINDS)
        decls.append(d)

    def handle(body_raw, term, ln, arrow_idx):
        nonlocal depth
        owner_e = stack[-1] if stack and stack[-1]["kind"] in TYPE_KINDS else None
        owner = owner_e["name"] if owner_e else None
        owner_kind = owner_e["kind"] if owner_e else None
        at_member = bool(owner_e) and depth == owner_e["body_depth"]
        at_ns = (not stack) or (stack[-1]["kind"] == "namespace" and depth == stack[-1]["body_depth"])
        in_enum = bool(stack) and stack[-1]["kind"] == "enum" and depth == stack[-1]["body_depth"]

        body = strip_attrs(body_raw)
        if not body:
            return
        doclines = []
        k = ln - 1
        while k in docs:
            doclines.append(docs[k])
            k -= 1
        doclines.reverse()

        m = re.match(r'namespace\s+([\w.]+)', body)
        if m:
            if term == "{":
                stack.append({"kind": "namespace", "name": m.group(1), "body_depth": depth + 1})
            return
        if in_enum:
            nm = re.match(r'([A-Za-z_]\w*)', body)
            if nm:
                emit("enumvalue", nm.group(1), "public", ln, body, owner, owner_kind, doclines)
            return
        if not (at_member or at_ns):
            return

        tm = re.search(r'\b(class|struct|interface|enum|record)\s+([A-Za-z_]\w*)', body)
        if tm:
            pre = body[:tm.start()]
            if not any(x in pre for x in ("where", "(", "=", ":")):
                kind, name = tm.group(1), tm.group(2)
                acc_t = access_of(body, owner_kind)
                emit("type:" + kind, name, acc_t, ln, body, owner, owner_kind, doclines)
                if term == "{":
                    stack.append({"kind": kind, "name": name, "body_depth": depth + 1, "access": acc_t})
                return

        mod_re = "|".join(ACCESS + MODS)
        if re.match(r'(?:(?:' + mod_re + r')\s+)*delegate\b', body):
            nm = re.search(r'([A-Za-z_]\w*)\s*(?:<[^()]*>)?\s*\(', body)
            emit("delegate", nm.group(1) if nm else "?", access_of(body, owner_kind), ln, body, owner, owner_kind, doclines)
            return
        if not at_member:
            return
        if re.match(r'(?:(?:' + mod_re + r')\s+)*event\b', body):
            nm = re.findall(r'([A-Za-z_]\w*)', body.split("=")[0])
            emit("event", nm[-1] if nm else "?", access_of(body, owner_kind), ln, body, owner, owner_kind, doclines)
            return

        # The `=>` position must be found in `body`, not carried in from the raw accumulated
        # head: the head keeps its leading whitespace, so an index taken there overshoots the
        # stripped body and leaves the arrow inside `sig`, where `=>` then reads as an
        # assignment and every expression-bodied property is misfiled as a field.
        arrow_pos = top_index(body, "=>")
        sig = body if arrow_pos < 0 else body[:arrow_pos]
        eq, par = top_index(sig, "="), top_index(sig, "(")
        acc = access_of(body, owner_kind)

        # explicit interface implementation (`void IFoo.Bar()`) has no access modifier
        # by language rule but is part of the public surface, so it is not "private".
        name_part = (sig[:par] if par >= 0 else sig).strip()
        if acc == "private" and re.search(r'\b[A-Za-z_]\w*(?:<[^()]*>)?\s*\.\s*[A-Za-z_]\w*$', name_part):
            acc = "explicit-impl"

        if "this[" in sig.replace(" ", ""):
            emit("property", "this[]", acc, ln, body, owner, owner_kind, doclines)
            return
        if eq >= 0 and (par < 0 or eq < par):
            nm = re.findall(r'([A-Za-z_]\w*)', sig[:eq])
            emit("field", nm[-1] if nm else "?", acc, ln, body, owner, owner_kind, doclines)
            return
        if par >= 0:
            if owner and re.match(r'(?:(?:' + mod_re + r')\s+)*~?' + re.escape(owner) + r'\s*(?:<[^()]*>)?\s*\(', sig):
                emit("ctor", owner, acc, ln, body, owner, owner_kind, doclines)
                return
            if sig.lstrip().startswith("~"):
                emit("ctor", owner or "?", "private", ln, body, owner, owner_kind, doclines)
                return
            if re.search(r'\boperator\b', sig):
                nm = re.search(r'operator\s*(\S+?)\s*\(', sig)
                emit("operator", nm.group(1) if nm else "?", acc, ln, body, owner, owner_kind, doclines)
                return
            nm = re.search(r'([A-Za-z_]\w*)\s*(?:<[^()]*>)?\s*\(', sig)
            if nm and nm.group(1) not in CONTROL:
                emit("method", nm.group(1), acc, ln, body, owner, owner_kind, doclines)
            return
        nm = re.findall(r'([A-Za-z_]\w*)', sig)
        name = nm[-1] if nm else "?"
        if term == "{" or arrow_pos >= 0:
            emit("property", name, acc, ln, body, owner, owner_kind, doclines)
        elif term == ";":
            emit("field", name, acc, ln, body, owner, owner_kind, doclines)

    def flush(term):
        nonlocal head, head_line, arrow
        h = head.strip()
        if h and head_line is not None:
            handle(h, term, head_line, arrow)
        head, head_line, arrow = "", None, -1

    i, N = 0, len(stream)
    while i < N:
        ch, ln = stream[i]
        if head_line is None and not ch.isspace():
            head_line = ln
        if ch in "([":
            bdepth += 1
        elif ch in ")]":
            bdepth -= 1
        if bdepth == 0:
            if ch == "=" and i + 1 < N and stream[i + 1][0] == ">" and arrow < 0:
                arrow = len(head)
            if ch == "{":
                flush("{")
                depth += 1
                i += 1
                continue
            if ch == "}":
                flush(None)
                depth -= 1
                while stack and stack[-1]["body_depth"] > depth:
                    stack.pop()
                i += 1
                continue
            if ch == ";":
                flush(";")
                i += 1
                continue
            if ch == "," and stack and stack[-1]["kind"] == "enum" and depth == stack[-1]["body_depth"]:
                flush(",")
                i += 1
                continue
        head += ch
        i += 1
    return decls


# ------------------------------------------------------------------------ evaluate
TAG_BANNED = re.compile(r'<(param|returns|typeparam|exception)\b')
NEEDS_DOC = ("public", "protected", "internal")
DOC_KINDS = ("method", "property", "delegate", "operator", "event")


def area_of(rel):
    parts = rel.split(os.sep)
    if parts[0] == "Assets":
        return "Assets", "Assets"
    pkg = parts[1] if len(parts) > 1 else "?"
    for marker in ("Samples~", "Tests", "Editor"):
        if marker in parts:
            return pkg, marker
    return pkg, "Runtime"


VISIBLE = ("public", "protected")
RESTRICTIVENESS = {"public": 0, "protected": 1, "internal": 2, "private": 3}


def effective_access(d):
    """The narrowest of the member's own access and every enclosing type's."""
    return max((d.access,) + d.enclosing, key=lambda a: RESTRICTIVENESS.get(a, 0))


def is_consumer_api(d, sub):
    """§6.6: public consumer-facing API == a public/protected declaration in Runtime/ whose
    every enclosing type is also public/protected. A `public` member of an `internal` type is
    not reachable outside the assembly, so it takes the compact internal form."""
    return sub == "Runtime" and d.access in VISIBLE and all(a in VISIBLE for a in d.enclosing)


def evaluate(decls):
    out = collections.defaultdict(list)
    counted = collections.Counter()
    for d in decls:
        pkg, sub = area_of(d.path)
        exempt = sub in EXEMPT_AREAS
        dt = " ".join(d.doc)
        has_doc = bool(d.doc)
        has_sum = "<summary>" in dt
        has_inh = "<inheritdoc" in dt
        label = f"{(d.owner + '.') if d.owner else ''}{d.name}"
        loc = (d.path, d.line, label)

        def add(rule, extra=""):
            counted[(rule, sub)] += 1
            if not exempt:
                out[rule].append((d.path, d.line, label + extra))

        if d.kind == "enumvalue":
            if has_doc:
                add("A")
            continue
        if d.kind == "field":
            if has_doc and d.access == "private":
                add("B")
            continue
        if d.kind == "ctor":
            if has_doc:
                add("C")
            continue
        if d.access == "explicit-impl":
            continue
        if d.access == "private":
            if has_doc:
                add("D", f" [{d.kind}]")
            continue
        if d.access not in NEEDS_DOC:
            continue
        if not (d.kind in DOC_KINDS or d.kind.startswith("type:")):
            continue

        if not has_doc:
            rule = {"operator": "E", "property": "G", "method": "H", "event": "I"}.get(d.kind, "F")
            if d.kind == "delegate":
                rule = "F"
            add(rule, f" [{d.access}]")
            continue

        if not has_sum and not has_inh:
            add("J")
        if TAG_BANNED.search(dt) and not is_consumer_api(d, sub):
            tags = ",".join(sorted(set(TAG_BANNED.findall(dt))))
            eff = effective_access(d)
            shown = eff if eff == d.access else f"{d.access}, effectively {eff}"
            add("K", f" <{tags}> [{shown} in {sub}]")
        if (d.kind == "method" or d.kind.startswith("type:")) and has_sum and len(d.doc) == 1:
            if is_consumer_api(d, sub):
                add("M", f" [{d.kind}]")
    return out, counted


# §6.6's member order gives Unity's message methods their own slot BEFORE "methods by access",
# so a private Unity callback does not open the private block and cannot strand a later
# `internal` member. Without this, OnDestroy / Update / OnEnable false-positive rule N.
UNITY_MESSAGES = {
    "Awake", "Start", "Update", "LateUpdate", "FixedUpdate", "OnEnable", "OnDisable",
    "OnDestroy", "OnGUI", "OnValidate", "Reset", "OnApplicationFocus", "OnApplicationPause",
    "OnApplicationQuit", "OnBecameVisible", "OnBecameInvisible", "OnTransformParentChanged",
    "OnBeforeTransformParentChanged", "OnRectTransformDimensionsChange", "OnCanvasGroupChanged",
    "OnDidApplyAnimationProperties", "OnTriggerEnter", "OnTriggerExit", "OnTriggerStay",
    "OnCollisionEnter", "OnCollisionExit", "OnCollisionStay", "OnMouseDown", "OnMouseUp",
    "OnMouseEnter", "OnMouseExit", "OnMouseOver", "OnMouseDrag", "OnMouseUpAsButton",
    "OnDrawGizmos", "OnDrawGizmosSelected", "OnPreRender", "OnPostRender", "OnPreCull",
    "OnRenderObject", "OnWillRenderObject", "OnRenderImage", "OnAnimatorMove", "OnAnimatorIK",
    "OnParticleCollision", "OnParticleTrigger", "OnAudioFilterRead", "OnJointBreak",
    "OnControllerColliderHit", "OnLevelWasLoaded", "OnPlayerConnected", "OnServerInitialized",
    "CreateGUI", "CreateInspectorGUI", "CreatePropertyGUI", "OnInspectorGUI", "OnSceneGUI",
    "OnPreprocessBuild", "OnPostprocessBuild", "OnAfterDeserialize", "OnBeforeSerialize",
}


def ordering(decls):
    """Rule N (gated) plus an advisory access-order report."""
    groups = collections.defaultdict(list)
    for d in decls:
        if d.kind == "method" and d.owner and d.access in ACCESS:
            groups[(d.path, d.owner)].append(d)
    rank = {"public": 0, "internal": 1, "protected": 2, "private": 3}
    gated, advisory = [], []
    for (path, owner), ms in groups.items():
        pkg, sub = area_of(path)
        if sub in EXEMPT_AREAS:
            continue
        ms.sort(key=lambda x: x.line)
        seen_private = None
        for d in ms:
            if d.access == "private":
                if d.name not in UNITY_MESSAGES:
                    seen_private = d.line
            elif d.access == "internal" and seen_private is not None:
                gated.append((path, d.line, f"{owner}.{d.name} internal after private@{seen_private}"))
        worst, wname, wline = -1, None, None
        for d in ms:
            r = rank[d.access]
            if r < worst:
                advisory.append((path, d.line, f"{owner}.{d.name} [{d.access}] after [{wname}]@{wline}"))
                break
            if r > worst:
                worst, wname, wline = r, d.access, d.line
    return gated, advisory


# -------------------------------------------------------------------------- report
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--advisory", action="store_true", help="print the noisy member-ordering report")
    ap.add_argument("--json", metavar="PATH", help="write all findings as JSON")
    ap.add_argument("--list", nargs="*", metavar="RULE", help="print every finding for these rule ids")
    args = ap.parse_args()

    files = []
    for base in SCAN_ROOTS:
        for dp, dn, fn in os.walk(os.path.join(ROOT, base)):
            dn[:] = [x for x in dn if x not in ("Library", "obj", "bin", ".git")]
            for f in fn:
                if f.endswith(".cs"):
                    p = os.path.join(dp, f)
                    files.append((p, os.path.relpath(p, ROOT)))
    files.sort()

    decls = []
    for p, r in files:
        try:
            decls.extend(parse(p, r))
        except Exception as e:                                  # noqa: BLE001
            print(f"PARSE FAIL {r}: {e}", file=sys.stderr)

    out, counted = evaluate(decls)
    gated_n, advisory = ordering(decls)
    if gated_n:
        out["N"] = gated_n

    # §2.2: a verifier must name what it inspected, not just return a verdict.
    print(f"style-audit — ruleset: {RULESET_VERSION}")
    print(f"scanned: {len(files)} .cs files under {'/, '.join(SCAN_ROOTS)}/  ->  {len(decls)} declarations")
    print(f"gated areas: Runtime, Editor    exempt (counted only): {', '.join(EXEMPT_AREAS)}")
    print()

    total = sum(len(v) for v in out.values())
    print(f"{'rule':5} {'gated':>6} {'exempt':>7}  description")
    print("-" * 78)
    for rule in sorted(RULE_TITLES):
        g = len(out.get(rule, []))
        ex = sum(n for (r, sub), n in counted.items() if r == rule and sub in EXEMPT_AREAS)
        if g or ex:
            print(f"{rule:5} {g:6d} {ex:7d}  {RULE_TITLES[rule]}")
    print("-" * 78)
    print(f"{'TOTAL':5} {total:6d}")
    print()

    if total:
        print("by package / area:")
        per = collections.Counter()
        for rule, v in out.items():
            for p, _, _ in v:
                pkg, sub = area_of(p)
                per[(pkg, sub)] += 1
        for (pkg, sub), n in sorted(per.items(), key=lambda x: -x[1]):
            print(f"   {n:5d}  {pkg}/{sub}")
        print()
        print("worst files:")
        fc = collections.Counter(p for v in out.values() for p, _, _ in v)
        for f, n in fc.most_common(10):
            print(f"   {n:5d}  {f}")
        print()

    if args.list is not None:
        wanted = args.list or sorted(out)
        for rule in wanted:
            v = out.get(rule, [])
            print(f"=== {rule}: {RULE_TITLES.get(rule, '?')} ({len(v)})")
            for p, ln, label in sorted(v):
                print(f"   {p}:{ln}  {label}")
        print()

    if args.advisory:
        print(f"ADVISORY — access-order (NOT gated; does not model the Unity-callback slot,")
        print(f"so CreateGUI / Dispose / OnValidate false-positive): {len(advisory)} types")
        for p, ln, label in advisory[:40]:
            print(f"   {p}:{ln}  {label}")
        print()

    if args.json:
        payload = {"ruleset": RULESET_VERSION, "files": len(files), "declarations": len(decls),
                   "findings": {k: [list(x) for x in v] for k, v in out.items()},
                   "advisory_access_order": [list(x) for x in advisory]}
        with open(args.json, "w") as f:
            json.dump(payload, f, indent=1)
        print(f"wrote {args.json}")

    if total:
        print(f"FAIL: {total} violation(s) of {RULESET_VERSION}")
        return 1
    print(f"PASS: 0 violations across {len(files)} files ({RULESET_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
