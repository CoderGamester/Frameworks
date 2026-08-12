#!/usr/bin/env python3
"""Polarity-test Tools/style-audit.py: assert it flags what it must AND stays silent where it must.

A counting tool's false negatives are invisible and its false positives cause destructive edits, so
a fixture has to pin both directions. Every case below corresponds to a defect the checker actually
had -- see the bug-class table in SKILL.md. When a new class is found, add a case here rather than
only patching the parser, or the next rewrite reintroduces it.

Two kinds of case, and the split is deliberate:

  MUST-FLAG  -> tested against SYNTHETIC snippets parsed in memory. A clean repo contains no
                violations by definition, so anchoring these to live files makes them
                unsatisfiable the moment the audit reaches zero. (That is not hypothetical: the
                first version of this script anchored the private-field case to `floatP._raw`,
                whose doc comment the audit itself had removed hours earlier.)
  MUST-BE-SILENT -> tested against LIVE repo files. Asserting silence stays valid forever, and
                these are the cases where a false positive would drive a destructive edit.

Nothing here writes to the repo -- snippets are parsed via style-audit's own parse()/evaluate()
with a fabricated relative path, so no file is created under Packages/ where a concurrent
`git add -A` could sweep it up.

Usage:
    python3 .claude/skills/code-standards-audit/scripts/polarity-check.py [--verbose]

Exit 0 when every expectation holds, 1 otherwise.
"""
import argparse
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))

_spec = importlib.util.spec_from_file_location("style_audit", os.path.join(ROOT, "Tools", "style-audit.py"))
sa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sa)

# A path the tool will classify as gated Runtime code.
FAKE_REL = os.path.join("Packages", "com.gamelovers.fixture", "Runtime", "Fixture.cs")

# ---------------------------------------------------------------- must-flag (synthetic)
# (rule, snippet, why this must be caught)
MUST_FLAG = [
    ("B", """
namespace Fx {
    public class C {
        /// <summary>Doc on a private field.</summary>
        private int _x;
    }
}""", "a private field carrying a doc comment"),

    ("C", """
namespace Fx {
    public class C {
        /// <summary>Doc on a constructor.</summary>
        public C() { }
    }
}""", "constructors are never documented, whatever their access"),

    ("D", """
namespace Fx {
    public class C {
        /// <summary>Doc on a private method.</summary>
        private void M() { }
    }
}""", "a private method carrying a doc comment"),

    ("A", """
namespace Fx {
    /// <summary>An enum.</summary>
    public enum E {
        /// <summary>Doc above an enum value.</summary>
        A,
        B
    }
}""", "enum values take an inline // comment, never a /// block"),

    ("H", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        public void Undocumented() { }
    }
}""", "an undocumented public method"),

    ("G", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        public int Undocumented => 1;
    }
}""", "an undocumented public property (expression-bodied, the shape once misfiled as a field)"),

    ("K", """
namespace Fx {
    internal interface I {
        /// <summary>Does a thing.</summary>
        /// <param name="a">The thing.</param>
        void M(int a);
    }
}""", "<param> on an internal member, which is not consumer-facing API"),

    ("L", """
namespace Fx {
    internal class C {
        /// <summary>This deliberately oversized inline summary proves the checker measures the complete indented physical source line instead of only counting the XML content after trimming.</summary>
        internal void M() { }
    }
}""", "an inline summary whose complete physical line exceeds 120 columns"),

    ("M", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        /// <summary>One-liner on public Runtime API.</summary>
        public void M() { }
    }
}""", "public consumer-facing methods take the multi-line block form"),

    ("N", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        private void Helper() { }
        internal void Seam() { }
    }
}""", "an internal method declared after a private one"),

    ("D", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        private class Nested {
            /// <inheritdoc />
            public override string ToString() => "x";
        }
    }
}""", "even a bare <inheritdoc /> on a member of a private nested type is forbidden"),

    ("J", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        /// <remarks>Only remarks, no summary.</remarks>
        public void M() { }
    }
}""", "a doc block with <remarks> but no <summary> renders nothing in IntelliSense"),
]

# ------------------------------------------------------- must-be-silent (synthetic)
MUST_BE_SILENT_SYNTHETIC = [
    ("L", """
namespace Fx {
    internal class C {
        /// <summary>
        /// This intentionally long block-summary content line proves rule L targets collapsed inline layout instead of mass-firing on established XML prose and indivisible references.
        /// </summary>
        internal void M() { }
    }
}""", "an already-multiline summary is not treated as a collapsed inline-layout violation"),

    ("L", """
namespace Fx {
    internal class C {
        /// <summary>
        /// A single sentence may wrap across short physical lines.
        /// </summary>
        internal void M() { }
    }
}""", "a multi-line single-sentence summary whose physical lines fit within 120 columns"),

    ("H", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        private class Nested {
            public override string ToString() => "x";
            public void AlsoUnreachable() { }
        }
    }
}""", "members of a PRIVATE nested type are effectively private, so no doc may be DEMANDED of "
      "them -- demanding one would produce documentation the same ruleset forbids"),

    ("H", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        /// <summary>Documented, with a tool directive between doc and declaration.</summary>
        // ReSharper disable once UnusedMember.Global
        public void M() { }
    }
}""", "a // comment does not detach XML documentation in C#"),

    ("N", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C : UnityEngine.MonoBehaviour {
        private void OnDestroy() { }
        internal void Seam() { }
    }
}""", "Unity message methods have their own ordering slot ahead of methods-by-access"),

    ("N", """
namespace Fx {
    /// <summary>
    /// A type.
    /// </summary>
    public class C {
        [System.Runtime.InteropServices.DllImport("__Internal")]
        private static extern void Native();
        internal void Seam() { }
    }
}""", "a [DllImport] extern declaration sits with the interop surface, not the private block"),
]

# ------------------------------------------------------------ must-be-silent (live repo)
# (rule, path-fragment, member-fragment, why)
MUST_BE_SILENT_LIVE = [
    ("K", "IUiService.cs", "",
     "<param> on a public consumer-facing interface is explicitly permitted by §6.6"),
    ("M", "IHapticsBackend.cs", "",
     "members of an INTERNAL interface default to public but are not consumer-facing API"),
    ("D", "CoroutineService.cs", "AsyncCoroutine",
     "AsyncCoroutine is a private nested class; effective accessibility makes its members private"),
    ("B", "RngService.cs", "",
     "RngData's explicit interface impls carry no access modifier by language rule"),
    ("B", "ValidationResult.cs", "",
     "auto-properties with initializers flush twice; the phantom field would have driven a "
     "deletion of valid property documentation"),
]


def rules_for(snippet):
    """Parse a snippet in memory and return the set of rule ids it triggers."""
    fd, path = tempfile.mkstemp(suffix=".cs")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(snippet)
        decls = sa.parse(path, FAKE_REL)
    finally:
        os.unlink(path)
    out, _ = sa.evaluate(decls)
    gated_n, _ = sa.ordering(decls)
    if gated_n:
        out["N"] = gated_n
    return {r for r, v in out.items() if v}


def live_findings():
    files = []
    for base in sa.SCAN_ROOTS:
        for dp, dn, fn in os.walk(os.path.join(ROOT, base)):
            dn[:] = [x for x in dn if x not in ("Library", "obj", "bin", ".git")]
            for f in fn:
                if f.endswith(".cs"):
                    p = os.path.join(dp, f)
                    files.append((p, os.path.relpath(p, ROOT)))
    decls = []
    for p, r in sorted(files):
        decls.extend(sa.parse(p, r))
    out, _ = sa.evaluate(decls)
    gated_n, _ = sa.ordering(decls)
    if gated_n:
        out["N"] = gated_n
    return out, len(files), len(decls)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print(f"ruleset: {sa.RULESET_VERSION}")
    passed = failed = 0

    def report(ok, label, detail):
        nonlocal passed, failed
        passed += ok
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        if not ok or args.verbose:
            print(f"        {detail}")

    print("\n-- must-flag (synthetic) --")
    for rule, snippet, why in MUST_FLAG:
        got = rules_for(snippet)
        report(rule in got, f"[{rule}] {why}",
               f"expected rule {rule} to fire; fired: {sorted(got) or 'nothing'}")

    print("\n-- must-be-silent (synthetic) --")
    for rule, snippet, why in MUST_BE_SILENT_SYNTHETIC:
        got = rules_for(snippet)
        report(rule not in got, f"[{rule}] {why.splitlines()[0]}",
               f"expected rule {rule} silent; fired: {sorted(got) or 'nothing'}")

    print("\n-- must-be-silent (live repo) --")
    findings, nfiles, ndecls = live_findings()
    print(f"        (scanned {nfiles} files, {ndecls} declarations)")
    for rule, path_frag, member_frag, why in MUST_BE_SILENT_LIVE:
        hits = [x for x in findings.get(rule, [])
                if path_frag in x[0] and (not member_frag or member_frag in x[2])]
        report(not hits, f"[{rule}] {path_frag} {member_frag}".rstrip(),
               f"{why}; hits: {hits[:2] or 'none'}")

    leaks = [x[0] for rule, v in findings.items() if rule != "L" for x in v
             if "/Tests/" in x[0] or "Samples~" in x[0]]
    report(not leaks, "exempt-area scoping (all but cross-area summary-width rule L)",
           f"{len(leaks)} leak(s), e.g. {leaks[:2]}")

    total = sum(len(v) for v in findings.values())
    print(f"\n{passed} passed, {failed} failed   (live audit currently reports {total} gated)")
    if failed:
        print("\nA failure here means the checker's own logic is wrong, or this fixture has drifted.")
        print("Resolve which before acting on any count -- see the bug-class table in SKILL.md.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
