#!/usr/bin/env python3
"""Release driver for the GameLovers UPM packages.

Single-package and stateless by design: every phase is derived from git/GitHub
state, never from a state file, so a run that halts for a human PR merge resumes
correctly hours later in a different session. Parallelism is one agent per
package -- see SKILL.md for the orchestration and the two barriers.

    release.py status <pkg> [--json]        derive the facts and resolve the phase
    release.py notes-status <pkg>           compare open PR body with pending notes
    release.py sync-pr-body <pkg>           update and verify an existing PR body
    release.py preflight <pkg>              gates G0-G16, no mutation
    release.py pack <pkg> [--tier N]        produce and verify the tarball
    release.py verify-tarball <tgz> <id> <version> [--tier N] [--head-sha SHA]
    release.py open-pr <pkg>                push develop, open the PR, halt
    release.py tag <pkg>                    tag the merge commit (post-merge only)
    release.py publish <pkg>                draft -> verify digest -> publish
    release.py bump-host <pkg>...           ONE serialized host commit (orchestrator)
    release.py audit [<pkg>...] [--limit N] read-only attestation/identity audit

`<pkg>` is a folder name under Packages/, with or without the `com.gamelovers.`
prefix (`services` and `com.gamelovers.services` both work).

Every `gh` invocation runs with GH_TOKEN for the CoderGamester account, and the
identity assertion re-runs in that same environment immediately before each
write -- the machine's active gh account is a different one, and a single
forgotten token silently misattributes a release.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import changelog  # noqa: E402

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

GH_ACCOUNT = "CoderGamester"
GIT_NAME = "CoderGamester"
GIT_EMAIL = "game.gamester@gmail.com"

# Unity org that must own every attestation. The published statechart 0.9.4
# carries ownerOrgName "miguel-cartier-supercell-com" -- a work-identity-derived
# org leaked into a public OSS artifact. G26 exists to stop that recurring.
UNITY_ORG_ID = "129325"
FORBIDDEN_ORG_SUBSTRINGS = ("supercell",)

WORK_BRANCH = "develop"
RELEASE_BRANCH = "master"

# Cache, not scratch: the pack dir must survive across sessions so the post-merge
# phase can resume without repacking from a different working tree.
CACHE = pathlib.Path.home() / "Library/Caches/GameLovers/upm-release"
PACK_ROOT = CACHE / "pack"
RUN_ROOT = CACHE / "run"
PACKER_PROJECT = pathlib.Path.home() / "Library/Caches/GameLovers/UpmPacker"

UNITY_HUB = pathlib.Path("/Applications/Unity/Hub/Editor")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class Fail(Exception):
    """A gate refused. The message is the user-facing explanation."""


# A git-lfs pointer is a tiny text stub. A checkout done without `git lfs pull`
# leaves these on disk and the packer copies them verbatim, so a consumer gets a
# 129-byte "audio file". Shared by G28 (tarball) and preflight-pr (working tree)
# so the two can never drift apart.
LFS_POINTER_MAGIC = b"version https://git-lfs"
LFS_POINTER_MAX_BYTES = 200


def is_lfs_pointer(head: bytes) -> bool:
    return head.startswith(LFS_POINTER_MAGIC)


def lfs_pointers_in_tree(root: pathlib.Path) -> list[str]:
    """Unresolved lfs stubs under `root`, as paths relative to it."""
    found = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            if path.stat().st_size > LFS_POINTER_MAX_BYTES:
                continue
            with path.open("rb") as fh:
                if is_lfs_pointer(fh.read(len(LFS_POINTER_MAGIC))):
                    found.append(str(path.relative_to(root)))
        except OSError:
            continue
    return sorted(found)


# --------------------------------------------------------------------------- #
# Process helpers
# --------------------------------------------------------------------------- #


def run(
    args: list[str],
    cwd: str | pathlib.Path | None = None,
    check: bool = True,
    env: dict | None = None,
) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        env=env,
    )
    if check and proc.returncode != 0:
        raise Fail(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"  stdout: {proc.stdout.strip()}\n  stderr: {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


_TOKEN: str | None = None


def gh_env() -> dict:
    """Environment carrying the CoderGamester token for every gh call."""
    global _TOKEN
    if _TOKEN is None:
        proc = subprocess.run(
            ["gh", "auth", "token", "--user", GH_ACCOUNT],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            raise Fail(
                f"G0: no gh token for '{GH_ACCOUNT}'. Run `gh auth login` for that "
                f"account (the active account is a different one)."
            )
        _TOKEN = proc.stdout.strip()
    env = dict(os.environ)
    env["GH_TOKEN"] = _TOKEN
    env.pop("GITHUB_TOKEN", None)
    return env


def gh(args: list[str], check: bool = True) -> str:
    return run(["gh", *args], check=check, env=gh_env())


def assert_identity() -> None:
    """G0. Re-run immediately before every write, in the same env as the write."""
    login = gh(["api", "user", "-q", ".login"], check=False)
    if login != GH_ACCOUNT:
        raise Fail(
            f"G0: releases must be authored by '{GH_ACCOUNT}' but the token resolves "
            f"to '{login or '<none>'}'. Refusing to write."
        )


def git(pkg_path: pathlib.Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(pkg_path), *args], check=check)


def git_bytes(pkg_path: pathlib.Path, *args: str) -> bytes:
    """Run git without universal-newline conversion when byte identity matters."""
    command = ["git", "-C", str(pkg_path), *args]
    proc = subprocess.run(command, capture_output=True)
    if proc.returncode != 0:
        raise Fail(
            f"command failed ({proc.returncode}): {' '.join(command)}\n"
            f"  stderr: {proc.stderr.decode(errors='replace').strip()}"
        )
    return proc.stdout


def notes_match(actual: str, expected: str) -> bool:
    """Compare notes exactly after GitHub's newline transport normalization."""
    def canonical(value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")

    return canonical(actual) == canonical(expected)


# --------------------------------------------------------------------------- #
# Package resolution
# --------------------------------------------------------------------------- #


def host_root() -> pathlib.Path:
    if override := os.environ.get("FRAMEWORKS_ROOT"):
        return pathlib.Path(override).resolve()
    # scripts/ -> unity-package-release/ -> skills/ -> .claude/ -> repo root
    return pathlib.Path(__file__).resolve().parents[4]


class Package:
    def __init__(self, name: str):
        root = host_root()
        folder = name if name.startswith("com.gamelovers.") else f"com.gamelovers.{name}"
        path = root / "Packages" / folder
        if not (path / "package.json").is_file():
            raise Fail(f"no package.json at {path} -- '{name}' is not a package folder")

        self.host = root
        self.folder = folder
        self.path = path
        manifest = json.loads((path / "package.json").read_text(encoding="utf-8-sig"))
        self.id: str = manifest["name"]
        self.version: str = manifest["version"]
        self.changelog = path / "CHANGELOG.md"
        self._repo: str | None = None

    @property
    def origin_slug(self) -> str:
        url = git(self.path, "remote", "get-url", "origin")
        return re.sub(r"\.git$", "", re.sub(r".*github\.com[/:]", "", url))

    @property
    def repo(self) -> str:
        """Canonical owner/name. Resolves past GitHub's rename redirect.

        `.gitmodules` is stale for two packages (services -> Unity-Services,
        uiservice -> Unity-UiService), and Unity's packer bakes origin's URL into
        the artifact, so this must never be derived from the folder name.
        """
        if self._repo is None:
            self._repo = gh(["api", f"repos/{self.origin_slug}", "-q", ".full_name"])
        return self._repo

    @property
    def pack_dir(self) -> pathlib.Path:
        return PACK_ROOT / self.id / self.version

    @property
    def tarball(self) -> pathlib.Path:
        return self.pack_dir / f"{self.id}-{self.version}.tgz"

    def remote_tags(self) -> list[str]:
        # --refs is essential: every tag is annotated, so without it each appears
        # twice (X.Y.Z and the peeled X.Y.Z^{}).
        out = git(self.path, "ls-remote", "--tags", "--refs", "origin")
        return [
            line.split("refs/tags/", 1)[1]
            for line in out.splitlines()
            if "refs/tags/" in line
        ]


# --------------------------------------------------------------------------- #
# Fact gathering and phase resolution
# --------------------------------------------------------------------------- #


def fetch(pkg: Package) -> None:
    git(pkg.path, "fetch", "origin", "--prune", "--prune-tags", "--tags", "--quiet")


def remote_version(pkg: Package, ref: str) -> str | None:
    raw = git(pkg.path, "show", f"{ref}:package.json", check=False)
    if not raw:
        return None
    try:
        return json.loads(raw).get("version")
    except json.JSONDecodeError:
        return None


def facts(pkg: Package) -> dict:
    fetch(pkg)
    tags = pkg.remote_tags()

    tag_line = git(pkg.path, "ls-remote", "--tags", "--refs", "origin", f"refs/tags/{pkg.version}")
    tag_sha = tag_line.split()[0] if tag_line else None

    prs = json.loads(
        gh(
            [
                "pr", "list", "--repo", pkg.repo, "--state", "all",
                "--head", WORK_BRANCH, "--base", RELEASE_BRANCH, "--limit", "30",
                "--json", "number,state,mergedAt,mergeCommit,headRefOid,url,title,body",
            ]
        )
        or "[]"
    )

    rel_raw = gh(
        ["release", "view", pkg.version, "--repo", pkg.repo,
         "--json", "isDraft,tagName,name,body,assets"],
        check=False,
    )
    release = json.loads(rel_raw) if rel_raw.startswith("{") else None

    develop_tip = git(pkg.path, "rev-parse", f"origin/{WORK_BRANCH}")
    pointer_line = run(["git", "-C", str(pkg.host), "ls-tree", "HEAD", "--", f"Packages/{pkg.folder}"])
    pointer = pointer_line.split()[2] if pointer_line else None

    open_pr = next((p for p in prs if p["state"] == "OPEN"), None)
    merged_prs = [p for p in prs if p.get("mergedAt")]
    expected_notes = changelog.section_for(
        pkg.changelog, pkg.version, require_newest=True
    )["body"]

    return {
        "package": pkg.folder,
        "id": pkg.id,
        "version": pkg.version,
        "repo": pkg.repo,
        "origin_slug": pkg.origin_slug,
        "master_version": remote_version(pkg, f"origin/{RELEASE_BRANCH}"),
        "tag_sha": tag_sha,
        "tags": tags,
        "open_pr": open_pr,
        "pr_notes_current": (
            notes_match(open_pr.get("body") or "", expected_notes) if open_pr else None
        ),
        "merged_prs": merged_prs,
        "closed_unmerged": [p for p in prs if p["state"] == "CLOSED" and not p.get("mergedAt")],
        "release": release,
        "dirty": git(pkg.path, "status", "--porcelain"),
        "branch": git(pkg.path, "rev-parse", "--abbrev-ref", "HEAD"),
        "local_develop": git(pkg.path, "rev-parse", WORK_BRANCH, check=False),
        "develop_tip": develop_tip,
        "pointer": pointer,
        "pointer_current": pointer == develop_tip,
        "tarball_present": pkg.tarball.is_file(),
    }


def release_is_good(pkg: Package, f: dict) -> tuple[bool, str]:
    """Is the published release complete and correct? (G35 shape, digest excluded)"""
    rel = f["release"]
    if not rel:
        return False, "no release"
    if rel.get("isDraft"):
        return False, "release is a draft"
    assets = rel.get("assets") or []
    want = f"{pkg.id}-{pkg.version}.tgz"
    names = [a["name"] for a in assets]
    if names != [want]:
        return False, f"assets are {names}, expected exactly ['{want}']"
    if assets[0].get("state") != "uploaded":
        return False, f"asset state is {assets[0].get('state')!r}"
    return True, "ok"


def resolve_phase(pkg: Package, f: dict) -> tuple[str, str]:
    """First match wins, top to bottom. See SKILL.md for the full table."""
    good, why = release_is_good(pkg, f)

    if good and f["pointer_current"]:
        return "P7_DONE", f"release {pkg.version} published and host pointer current"
    if good:
        return "P6_HOST_BUMP", "release verified; host submodule pointer is stale"
    if f["release"] and f["release"].get("isDraft"):
        return "P4b_PUBLISH_DRAFT", "draft release exists -- verify assets then publish"
    if f["release"]:
        return "P5_FIX_ASSET", f"release exists but {why}"
    if f["tag_sha"]:
        return "P4_RELEASE", f"tag {pkg.version} exists at {f['tag_sha'][:9]}, no release yet"
    if f["master_version"] == pkg.version:
        return "P3_TAG", f"{RELEASE_BRANCH} already carries {pkg.version}; tag the merge commit"
    if f["open_pr"]:
        if not f["pr_notes_current"]:
            return (
                "P2_SYNC_NOTES",
                f"PR #{f['open_pr']['number']} body differs from the [{pkg.version}] changelog entry",
            )
        return "P2_AWAIT_MERGE", f"PR #{f['open_pr']['number']} open: {f['open_pr']['url']}"
    if f["closed_unmerged"]:
        nums = ", ".join(f"#{p['number']}" for p in f["closed_unmerged"])
        return "P2x_PR_CLOSED", f"PR {nums} closed without merging -- needs a human decision"

    master_v = f["master_version"]
    if master_v and changelog.semver(master_v) and changelog.semver(pkg.version):
        if changelog.semver(pkg.version) <= changelog.semver(master_v):
            return "P0_NOT_READY", (
                f"package.json is {pkg.version} but {RELEASE_BRANCH} already has {master_v}; "
                f"bump the version and add a CHANGELOG section first"
            )
    return "P1_PACK_PR", f"ready to pack and open a release PR for {pkg.version}"


# --------------------------------------------------------------------------- #
# Locking (macOS has no flock(1); mkdir is atomic)
# --------------------------------------------------------------------------- #


class Lock:
    def __init__(self, name: str):
        self.dir = RUN_ROOT / "locks" / name
        self.held = False

    def __enter__(self):
        self.dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.dir.mkdir()
        except FileExistsError:
            pid_file = self.dir / "pid"
            owner = pid_file.read_text().strip() if pid_file.is_file() else "?"
            if owner.isdigit() and _alive(int(owner)):
                raise Fail(
                    f"another release run (pid {owner}) holds the lock for "
                    f"{self.dir.name}. Wait for it, or remove {self.dir} if stale."
                )
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir.mkdir()
        (self.dir / "pid").write_text(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc):
        if self.held:
            shutil.rmtree(self.dir, ignore_errors=True)
        return False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


# Progress goes to stderr so stdout carries only real output (JSON, URLs, tables).
# That keeps `verify-tarball` and `status --json` machine-parseable for the
# orchestrator even when a gate emits a warning.
def ok(msg: str) -> None:
    print(f"  ok   {msg}", file=sys.stderr)


def note(msg: str) -> None:
    print(f"  ..   {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"  WARN {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Preflight gates G0-G16
# --------------------------------------------------------------------------- #


def preflight(pkg: Package, f: dict, run_tests: bool = False) -> None:
    v = pkg.version

    assert_identity()
    ok(f"G0  gh identity is {GH_ACCOUNT}")

    if pkg.repo != pkg.origin_slug:
        raise Fail(
            f"G1: origin points at '{pkg.origin_slug}' but GitHub's canonical name is "
            f"'{pkg.repo}'. Fix the submodule remote and .gitmodules before releasing -- "
            f"Unity bakes origin's URL into the tarball's package.json."
        )
    ok(f"G1  origin is canonical: {pkg.repo}")

    if f["branch"] != WORK_BRANCH:
        raise Fail(f"G2: expected branch '{WORK_BRANCH}', on '{f['branch']}'.")
    ok(f"G2  on {WORK_BRANCH}")

    if f["dirty"]:
        n = len(f["dirty"].splitlines())
        raise Fail(
            f"G3: {n} uncommitted change(s) in {pkg.folder}. The tarball is built from "
            f"the working tree; commit or stash first.\n{f['dirty']}"
        )
    ok("G3  working tree clean")

    if f["local_develop"] != f["develop_tip"]:
        raise Fail(
            f"G4: local {WORK_BRANCH} {f['local_develop'][:9]} != "
            f"origin/{WORK_BRANCH} {f['develop_tip'][:9]}. Push or pull first."
        )
    ok(f"G4  {WORK_BRANCH} in sync with origin")

    unique = git(
        pkg.path, "rev-list", "--count", "--no-merges",
        f"origin/{WORK_BRANCH}..origin/{RELEASE_BRANCH}",
    )
    if unique != "0":
        raise Fail(
            f"G5: {RELEASE_BRANCH} has {unique} non-merge commit(s) absent from "
            f"{WORK_BRANCH}; merging would produce a tree that differs from what was packed."
        )
    ok(f"G5  {RELEASE_BRANCH} has no unique content")

    ahead = git(pkg.path, "rev-list", "--count", f"origin/{RELEASE_BRANCH}..origin/{WORK_BRANCH}")
    if ahead == "0":
        raise Fail(f"G6: {WORK_BRANCH} has nothing to release.")
    ok(f"G6  {WORK_BRANCH} is {ahead} commit(s) ahead")

    if not SEMVER_RE.match(v):
        raise Fail(
            f"G7: version '{v}' is not bare X.Y.Z. Every one of the 127 historical tags "
            f"is bare SemVer -- no v-prefix, no prerelease suffix."
        )
    ok(f"G7  version {v} is bare SemVer")

    # G8/G9/G10: the pending entry must be unique, newest, canonical, free of an
    # Unreleased split, and dated for the day it is actually being released.
    try:
        section = changelog.validate_pending(
            pkg.changelog,
            v,
            expected_date=dt.date.today().isoformat(),
            baseline_bytes=git_bytes(
                pkg.path, "show", f"origin/{RELEASE_BRANCH}:CHANGELOG.md"
            ),
        )
    except changelog.ChangelogError as exc:
        raise Fail(f"G8-G10: {exc}") from exc
    ok(f"G8  package.json {v} == CHANGELOG heading at line {section['line']}")
    ok("G9  pending CHANGELOG is canonical; published history is byte-identical")
    ok(f"G10 CHANGELOG date {section['date']} is today's release date")

    master_v = f["master_version"]
    if master_v and changelog.semver(master_v) and changelog.semver(v) <= changelog.semver(master_v):
        raise Fail(f"G11: version {v} is not greater than {RELEASE_BRANCH}'s {master_v}.")
    ok(f"G11 {v} advances past {RELEASE_BRANCH}'s {master_v}")

    if f["tag_sha"]:
        raise Fail(
            f"G12: tag {v} already exists on origin ({f['tag_sha'][:9]}). Bump the "
            f"version, or resume the post-merge phase with `status`."
        )
    ok(f"G12 tag {v} is free on origin")

    if f["release"]:
        raise Fail(f"G13: release {v} already exists.")
    ok(f"G13 release {v} does not exist")

    if f["open_pr"]:
        raise Fail(
            f"G14: PR #{f['open_pr']['number']} is already open "
            f"{WORK_BRANCH}->{RELEASE_BRANCH}: {f['open_pr']['url']}"
        )
    ok("G14 no competing open PR")

    changed = git(
        pkg.path, "diff", "--name-only",
        f"origin/{RELEASE_BRANCH}", f"origin/{WORK_BRANCH}",
    ).splitlines()
    missing = [n for n in ("package.json", "CHANGELOG.md") if n not in changed]
    if missing:
        raise Fail(
            f"G15: the {WORK_BRANCH}..{RELEASE_BRANCH} diff does not touch {missing} -- "
            f"this does not look like a release commit."
        )
    ok("G15 diff touches package.json and CHANGELOG.md")

    if run_tests:
        note("G16 EditMode tests: not run automatically (opt-in, see SKILL.md)")


# --------------------------------------------------------------------------- #
# Packing: tier 1 upm CLI (attested) / tier 2 Unity editor / tier 3 npm
# --------------------------------------------------------------------------- #


def unity_editor() -> pathlib.Path | None:
    version_file = host_root() / "ProjectSettings/ProjectVersion.txt"
    wanted = None
    if version_file.is_file():
        m = re.search(r"m_EditorVersion:\s*(\S+)", version_file.read_text())
        wanted = m.group(1) if m else None

    candidates = []
    if wanted and (UNITY_HUB / wanted).is_dir():
        candidates.append(wanted)
    if UNITY_HUB.is_dir():
        candidates += sorted((d.name for d in UNITY_HUB.iterdir() if d.is_dir()), reverse=True)

    for name in candidates:
        exe = UNITY_HUB / name / "Unity.app/Contents/MacOS/Unity"
        if exe.is_file():
            return exe
    return None


def upm_cli() -> pathlib.Path | None:
    """Locate a `upm` CLI for tier-1 attested packing.

    Prefer the STANDALONE distribution (`~/.upm/bin/upm`, or anything on PATH):
    it ships independently of the editor, tracks a newer version (9.31.1 vs the
    6000.5.5f1 editor's 9.26.1), needs no license, and is a short-lived process
    with no project lock -- which is what makes parallel packing safe. Fall back
    to the copy bundled inside the editor.
    """
    standalone = pathlib.Path.home() / ".upm/bin/upm"
    if standalone.is_file():
        return standalone
    if found := shutil.which("upm"):
        return pathlib.Path(found)

    editor = unity_editor()
    if not editor:
        return None
    cli = editor.parent.parent / "Helpers/PackageManager/Server/UnityPackageManager"
    return cli if cli.is_file() else None


def have_service_account() -> bool:
    return bool(
        os.environ.get("UPM_SERVICE_ACCOUNT_KEY_ID")
        and os.environ.get("UPM_SERVICE_ACCOUNT_KEY_SECRET")
    )


def pack(pkg: Package, tier: int | None = None) -> tuple[pathlib.Path, int]:
    """Produce the tarball. Returns (path, tier_used)."""
    out = pkg.pack_dir
    # G20 depends on this: a stale sibling tarball from a previous version is the
    # root cause of the published 2.0.2/2.0.1 mismatch.
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    order = [tier] if tier else [1, 2, 3]
    errors = []

    for t in order:
        try:
            if t == 1:
                return _pack_upm(pkg, out), 1
            if t == 2:
                return _pack_unity(pkg, out), 2
            if t == 3:
                return _pack_npm(pkg, out), 3
        except Fail as exc:
            errors.append(f"tier {t}: {exc}")
            if tier:  # explicit tier -> do not silently fall back
                raise
            warn(f"tier {t} unavailable -- {exc}")
            for stale in out.glob("*.tgz"):
                stale.unlink()

    raise Fail("all pack tiers failed:\n  " + "\n  ".join(errors))


def _pack_upm(pkg: Package, out: pathlib.Path) -> pathlib.Path:
    cli = upm_cli()
    if not cli:
        raise Fail("UnityPackageManager CLI not found")
    if not have_service_account():
        raise Fail(
            "UPM_SERVICE_ACCOUNT_KEY_ID / _SECRET not set (needed to attest as "
            f"org {UNITY_ORG_ID})"
        )
    note(f"tier 1: upm pack --organization-id {UNITY_ORG_ID} ({cli})")
    # Do NOT let run() raise on a non-zero exit: this CLI puts the useful diagnosis
    # on stdout, and the exit code is inconsistent between builds (the editor-bundled
    # 9.26.1 exits 0 on bad credentials; the standalone 9.31.1 exits 1). Inspect the
    # output either way, so the failure is actionable rather than a bare rc.
    proc = subprocess.run(
        [str(cli), "pack", str(pkg.path),
         "--destination", str(out), "--organization-id", UNITY_ORG_ID],
        capture_output=True, text=True,
    )
    output = f"{proc.stdout}\n{proc.stderr}".strip()
    lowered = output.lower()
    for marker in (
        "invalid service account",
        "credentials are missing",
        "credentials provided",
        "does not have permission to sign",
        "failed to pack",
    ):
        if marker in lowered:
            hint = ""
            if "permission to sign" in lowered:
                hint = (
                    f"\n  The credentials authenticate but the service account lacks a "
                    f"package-signing role in org {UNITY_ORG_ID}. Grant it in Unity Cloud "
                    f"-> Tropa Elite -> Service Accounts -> the account -> add an org role "
                    f"with package management rights."
                )
            raise Fail(f"upm pack refused: {output.strip()}{hint}")
    return _sole_tarball(out)


def _pack_unity(pkg: Package, out: pathlib.Path) -> pathlib.Path:
    editor = unity_editor()
    if not editor:
        raise Fail("no Unity editor found under the Hub")
    ensure_packer_project(editor)

    log = out / "unity-pack.log"
    result = out / "pack-result.txt"
    note(f"tier 2: Unity batchmode Client.Pack ({editor.parent.parent.parent.parent.name})")

    proc = subprocess.run(
        [
            str(editor),
            "-batchmode", "-nographics", "-silent-crashes",
            "-disable-assembly-updater",
            "-projectPath", str(PACKER_PROJECT),
            "-logFile", str(log),
            "-executeMethod", "UpmPack.Run",
            "-packageFolder", str(pkg.path),
            "-outDir", str(out),
            "-resultFile", str(result),
            "-timeoutSeconds", "300",
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )

    # Verify by artifact, never by exit code alone.
    first = result.read_text().splitlines()[0].strip() if result.is_file() else "<no result file>"
    if proc.returncode != 0 or first != "OK":
        hint = ""
        if log.is_file():
            text = log.read_text(errors="replace")
            if "Licens" in text:
                hint = " (log mentions licensing -- editor may be offline or unlicensed)"
            elif "could not be found" in text:
                hint = " (executeMethod not found -- packer project failed to compile)"
        raise Fail(f"Unity pack failed rc={proc.returncode} result={first!r}{hint}; log at {log}")

    return _sole_tarball(out)


def _pack_npm(pkg: Package, out: pathlib.Path) -> pathlib.Path:
    note("tier 3: npm pack (DEGRADED -- no attestation, no repository block)")
    run(["npm", "pack", "--pack-destination", str(out)], cwd=pkg.path)
    return _sole_tarball(out)


def _sole_tarball(out: pathlib.Path) -> pathlib.Path:
    found = sorted(out.glob("*.tgz"))
    if len(found) != 1:
        raise Fail(f"expected exactly one .tgz in {out}, found {[p.name for p in found]}")
    return found[0]


def ensure_packer_project(editor: pathlib.Path) -> None:
    """Cached Unity project outside any git repo.

    Deliberately not inside the host repo: it has no Assets/Editor today, and a
    Unity run there would generate .meta files the repo rules say must only ever
    be committed after the editor makes them. Keeping Library/ cached also cuts
    boot from ~40-70s to ~10-20s.
    """
    assets = PACKER_PROJECT / "Assets/Editor"
    settings = PACKER_PROJECT / "ProjectSettings"
    packages = PACKER_PROJECT / "Packages"
    for d in (assets, settings, packages):
        d.mkdir(parents=True, exist_ok=True)

    src = pathlib.Path(__file__).resolve().parent / "UpmPack.cs"
    dst = assets / "UpmPack.cs"
    if not dst.is_file() or dst.read_text() != src.read_text():
        shutil.copyfile(src, dst)

    # Explicitly empty: an empty {} invites Unity to populate registry defaults
    # and hit the network.
    manifest = packages / "manifest.json"
    if not manifest.is_file():
        manifest.write_text('{\n  "dependencies": {}\n}\n')

    version_file = settings / "ProjectVersion.txt"
    editor_version = editor.parent.parent.parent.parent.name
    if not version_file.is_file() or editor_version not in version_file.read_text():
        version_file.write_text(f"m_EditorVersion: {editor_version}\n")


# --------------------------------------------------------------------------- #
# Tarball verification G20-G27
# --------------------------------------------------------------------------- #


def read_attestation(tgz: pathlib.Path) -> dict | None:
    """Extract and verify the PKCS#7 attestation payload, if present.

    The outer signature is Unity's own DigiCert cert; the org identity we care
    about lives in the signed JSON payload.
    """
    with tarfile.open(tgz, "r:gz") as tf:
        try:
            member = tf.extractfile("package/.attestation.p7m")
            blob = member.read() if member else None
        except KeyError:
            return None
    if not blob:
        return None

    proc = subprocess.run(
        ["openssl", "smime", "-verify", "-inform", "DER", "-noverify"],
        input=blob,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise Fail(f"G26: attestation present but PKCS#7 verification failed: "
                   f"{proc.stderr.decode(errors='replace').strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise Fail(f"G26: attestation payload is not JSON: {exc}")


def verify_tarball(
    tgz: pathlib.Path,
    want_id: str,
    want_version: str,
    tier: int | None = None,
    head_sha: str | None = None,
) -> dict:
    problems: list[str] = []
    want_name = f"{want_id}-{want_version}.tgz"

    # G20 -- exactly one tarball in the pack dir. This is the gate that makes the
    # published 2.0.2/2.0.1 asset mismatch impossible to reproduce.
    siblings = sorted(p.name for p in tgz.parent.glob("*.tgz"))
    if siblings != [want_name]:
        problems.append(
            f"G20 OUTDIR: expected exactly ['{want_name}'] in {tgz.parent}, found "
            f"{siblings}. A stale tarball from a previous version can be uploaded by "
            f"mistake -- the pack dir MUST be emptied before packing."
        )

    if tgz.name != want_name:
        problems.append(f"G21 FILENAME: expected '{want_name}', got '{tgz.name}'")

    with tarfile.open(tgz, "r:gz") as tf:
        names = tf.getnames()
        members = tf.getmembers()
        try:
            fh = tf.extractfile("package/package.json")
            manifest = json.loads(fh.read()) if fh else None
        except KeyError:
            manifest = None
            problems.append("G22 STRUCTURE: tarball has no 'package/package.json' member")

    if manifest is not None:
        if manifest.get("name") != want_id:
            problems.append(
                f"G22 ID: package/package.json name is {manifest.get('name')!r}, "
                f"expected {want_id!r}"
            )
        if manifest.get("version") != want_version:
            problems.append(
                f"G22 VERSION: package/package.json version is "
                f"{manifest.get('version')!r}, expected {want_version!r} -- "
                f"THIS TARBALL IS FROM A DIFFERENT RELEASE. Do not upload it."
            )

    stray = [n for n in names if n != "package" and not n.startswith("package/")]
    if stray:
        problems.append(f"G22c PREFIX: {len(stray)} member(s) outside 'package/': {stray[:5]}")

    # G23 -- provenance. Unity injects repository{url,type,revision}; npm does not.
    revision = ((manifest or {}).get("repository") or {}).get("revision")
    if head_sha:
        if revision is None:
            warn(
                "G23 no repository.revision in the packed manifest -- packed by the npm "
                "fallback, not Unity. This is a DEGRADED-FIDELITY artifact."
            )
        elif revision != head_sha:
            problems.append(
                f"G23 PROVENANCE: tarball was built from commit {revision[:9]} but "
                f"HEAD is {head_sha[:9]}"
            )

    # G27 -- tar hygiene. The published uiservice 1.2.1 embeds owner name
    # 'miguel.cartier' in every entry: an identity leak independent of the
    # attestation.
    owners = {m.uname for m in members if m.uname}
    leaked = {o for o in owners if any(b in o.lower() for b in FORBIDDEN_ORG_SUBSTRINGS)}
    personal = {o for o in owners if o not in ("", "root", "0")}
    if leaked:
        problems.append(f"G27 TAR OWNER: entries carry a forbidden owner name {sorted(leaked)}")
    elif personal:
        warn(f"G27 tar entries carry a personal owner name {sorted(personal)} (not normalised)")

    # G28 -- no unresolved git-lfs pointers. A checkout done without `git lfs pull`
    # leaves ~130-byte pointer stubs on disk, and the packer copies them verbatim:
    # consumers then get a 129-byte "audio file". Caught in the wild -- uiservice
    # 1.3.0 packed 5 pointers (2 sample .wav, 3 doc images) where the published
    # 1.2.1 had shipped real content, so it was a silent REGRESSION, not a
    # long-standing gap. Fix with `git lfs fetch origin <branch> && git lfs checkout`.
    with tarfile.open(tgz, "r:gz") as tf:
        pointers = []
        for member in tf.getmembers():
            if not member.isfile() or member.size > LFS_POINTER_MAX_BYTES:
                continue
            fh = tf.extractfile(member)
            if fh and is_lfs_pointer(fh.read(len(LFS_POINTER_MAGIC))):
                pointers.append(member.name.removeprefix("package/"))
    if pointers:
        problems.append(
            f"G28 LFS POINTERS: {len(pointers)} file(s) are unresolved git-lfs stubs "
            f"rather than real content: {pointers[:5]}. Run `git lfs fetch origin "
            f"<branch> && git lfs checkout` in the package, then repack."
        )

    # G26 -- attestation identity.
    attestation = read_attestation(tgz)
    if attestation:
        org_id = str(attestation.get("ownerOrgId", ""))
        org_name = str(attestation.get("ownerOrgName", ""))
        if any(b in org_name.lower() for b in FORBIDDEN_ORG_SUBSTRINGS):
            problems.append(
                f"G26 ORG LEAK: attestation ownerOrgName is {org_name!r}. This is the "
                f"exact defect found in the published statechart 0.9.4 and must never "
                f"recur -- a work-identity org inside a public OSS artifact."
            )
        elif org_id != UNITY_ORG_ID:
            problems.append(
                f"G26 ORG: attestation ownerOrgId is {org_id!r}, expected {UNITY_ORG_ID!r}"
            )
        if attestation.get("packageName") != want_id:
            problems.append(f"G26 attestation packageName is {attestation.get('packageName')!r}")
        if attestation.get("packageVersion") != want_version:
            problems.append(
                f"G26 attestation packageVersion is {attestation.get('packageVersion')!r}, "
                f"expected {want_version!r}"
            )
    elif tier == 1:
        problems.append("G26: tier 1 was requested but the tarball has no attestation")

    if problems:
        raise Fail("tarball verification FAILED:\n  " + "\n  ".join(problems))

    digest = hashlib.sha256(tgz.read_bytes()).hexdigest()
    return {
        "tarball": str(tgz),
        "sha256": digest,
        "files": len(names),
        "revision": revision,
        "attestation": attestation,
        "tar_owners": sorted(owners),
    }


def diff_previous(pkg: Package, tgz: pathlib.Path, prev: str | None) -> None:
    """G24 -- file-list diff against the previous release. Refuse on removals."""
    if not prev:
        note("G24 no previous release to diff against")
        return

    workdir = tgz.parent / "prev"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    gh(
        ["release", "download", prev, "--repo", pkg.repo, "--pattern", "*.tgz",
         "--dir", str(workdir)],
        check=False,
    )

    old = sorted(workdir.glob("*.tgz"))
    if not old:
        note(f"G24 previous release {prev} has no tarball asset to diff")
        return

    def listing(path: pathlib.Path) -> set[str]:
        with tarfile.open(path, "r:gz") as tf:
            names = {n.removeprefix("package/") for n in tf.getnames()}
        # The attestation is a packer artifact whose presence is governed by the
        # pack tier, not by package content -- G26 asserts it separately. Leaving
        # it in would make every tier-2/3 pack fail against a tier-1 predecessor.
        return names - {".attestation.p7m"}

    before, after = listing(old[0]), listing(tgz)
    removed = sorted(before - after)
    added = sorted(after - before)

    if removed:
        detail = "\n".join(f"    - {r}" for r in removed[:20])
        if os.environ.get("RELEASE_ALLOW_REMOVALS"):
            warn(f"G24 {len(removed)} file(s) removed vs {prev} (allowed by env):\n{detail}")
        else:
            raise Fail(
                f"G24: {len(removed)} file(s) present in {prev} are MISSING from "
                f"{pkg.version}:\n{detail}\n"
                f"  Refusing. If intentional, re-run with RELEASE_ALLOW_REMOVALS=1."
            )
    if added:
        note(f"G24 {len(added)} new file(s) vs {prev} (e.g. {added[:3]})")
    elif not removed:
        ok(f"G24 file list identical to {prev}")


# --------------------------------------------------------------------------- #
# Post-merge gates G30-G33
# --------------------------------------------------------------------------- #


def find_merge_commit(pkg: Package, f: dict) -> str:
    """The merge commit to tag, with G30/G31/G32 enforced."""
    master = git(pkg.path, "rev-parse", f"origin/{RELEASE_BRANCH}")

    if f["master_version"] != pkg.version:
        raise Fail(
            f"G32: {RELEASE_BRANCH}'s package.json says {f['master_version']}, "
            f"expected {pkg.version}."
        )

    parents = git(pkg.path, "rev-list", "--parents", "-n1", master).split()
    if len(parents) != 3:
        raise Fail(
            f"G30: {master[:9]} has {len(parents) - 1} parent(s) -- the PR was squash- or "
            f"rebase-merged, not merge-committed. Every one of the 127 historical tags "
            f"sits on a 2-parent merge commit. Resolve this manually."
        )
    ok(f"G30 {master[:9]} is a 2-parent merge commit")

    develop_parent = parents[2]
    master_tree = git(pkg.path, "rev-parse", f"{master}^{{tree}}")
    parent_tree = git(pkg.path, "rev-parse", f"{develop_parent}^{{tree}}")
    if master_tree != parent_tree:
        raise Fail(
            f"G31: {RELEASE_BRANCH}'s tree {master_tree[:9]} != the merged commit's tree "
            f"{parent_tree[:9]}. The merge altered content; the tarball no longer matches."
        )
    ok(f"G31 merge preserved the tree exactly ({master_tree[:9]})")

    # G32b -- link the artifact to the tag. The packed repository.revision is the
    # develop-side commit, which is always the merge commit's SECOND parent
    # (verified: uiservice 1.2.1's revision 8efd299 is the develop parent of 18df2a3).
    if pkg.tarball.is_file():
        with tarfile.open(pkg.tarball, "r:gz") as tf:
            fh = tf.extractfile("package/package.json")
            packed = json.loads(fh.read()) if fh else {}
        revision = (packed.get("repository") or {}).get("revision")
        if revision and revision != develop_parent:
            raise Fail(
                f"G32b PROVENANCE CHAIN: the tarball was packed from {revision[:9]} but "
                f"the merge commit's develop-side parent is {develop_parent[:9]}. The "
                f"artifact does not correspond to what was merged -- repack."
            )
        if revision:
            ok(f"G32b tarball revision {revision[:9]} == merged develop parent")

    ok(f"G32 {RELEASE_BRANCH} carries {pkg.version}")
    return master


def create_tag(pkg: Package, merge_sha: str) -> None:
    """Annotated, empty message, CoderGamester -- matching all 127 historical tags."""
    assert_identity()
    env = dict(os.environ)
    env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"] = GIT_NAME
    env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"] = GIT_EMAIL

    proc = subprocess.run(
        ["git", "-C", str(pkg.path), "tag", "-a", pkg.version, "-m", "", merge_sha],
        capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        # Some git builds reject an empty -m; the message is cosmetic, not functional.
        warn("empty tag message rejected; falling back to 'Release <version>'")
        run(
            ["git", "-C", str(pkg.path), "tag", "-a", pkg.version,
             "-m", f"Release {pkg.version}", merge_sha],
            env=env,
        )

    run(["git", "-C", str(pkg.path), "push", "origin", f"refs/tags/{pkg.version}"])

    # G33 -- confirm the tag landed on the intended commit with the right tagger.
    body = git(pkg.path, "cat-file", "-p", pkg.version)
    if f"object {merge_sha}" not in body:
        raise Fail(f"G33: tag {pkg.version} does not point at {merge_sha[:9]}:\n{body}")
    if GIT_EMAIL not in body:
        raise Fail(f"G33: tag {pkg.version} tagger is not {GIT_EMAIL}:\n{body}")

    remote = git(pkg.path, "ls-remote", "--tags", "--refs", "origin", f"refs/tags/{pkg.version}")
    if not remote:
        raise Fail(f"G33: tag {pkg.version} is not on origin after push.")
    ok(f"G33 tag {pkg.version} -> {merge_sha[:9]}, tagger {GIT_EMAIL}, pushed")


def publish_release(pkg: Package, f: dict) -> str:
    """Draft -> verify digest -> publish. Never publish unverified."""
    if not pkg.tarball.is_file():
        raise Fail(
            f"no verified tarball at {pkg.tarball}. Run `pack {pkg.folder}` first "
            f"(the pack dir is cached, so this survives across sessions)."
        )

    head = git(pkg.path, "rev-parse", f"origin/{WORK_BRANCH}")
    info = verify_tarball(pkg.tarball, pkg.id, pkg.version, head_sha=None)
    digest = info["sha256"]

    prev = changelog.prev_tag(pkg.remote_tags(), pkg.version)
    section = changelog.section_for(pkg.changelog, pkg.version, require_newest=False)
    body = changelog.release_body(section, pkg.repo, pkg.version, prev)

    if prev and prev not in pkg.remote_tags():
        raise Fail(f"G36: compare base '{prev}' is not an existing tag on origin.")

    notes = pkg.pack_dir / "release-notes.md"
    notes.write_text(body)  # --notes-file, never --notes "$(...)"

    existing = f["release"]
    if not existing:
        assert_identity()
        latest = "true" if changelog.prev_tag(pkg.remote_tags(), "999.999.999") == pkg.version else "false"
        gh([
            "release", "create", pkg.version,
            "--repo", pkg.repo,
            "--title", f"Release {pkg.version}",
            "--notes-file", str(notes),
            "--target", RELEASE_BRANCH,
            "--verify-tag",      # G34: without this, gh invents a tag at branch head
            "--draft",
            f"--latest={latest}",
            str(pkg.tarball),
        ])
        ok(f"G34 draft release created from existing tag {pkg.version}")

    # G35 -- content-addressed. The only gate that catches "right name, wrong bytes",
    # which is exactly the published 2.0.2 defect.
    rel = json.loads(gh([
        "release", "view", pkg.version, "--repo", pkg.repo,
        "--json", "isDraft,tagName,name,assets",
    ]))
    _assert_asset(pkg, rel, digest)
    ok(f"G35 asset digest matches sha256:{digest[:16]}...")

    assert_identity()
    gh(["release", "edit", pkg.version, "--repo", pkg.repo, "--draft=false"])

    # G37 -- re-read AFTER publishing; publish is what can mutate state.
    final = json.loads(gh([
        "release", "view", pkg.version, "--repo", pkg.repo,
        "--json", "isDraft,tagName,name,assets,url",
    ]))
    if final.get("isDraft"):
        raise Fail("G37: release is still a draft after publishing.")
    if final.get("tagName") != pkg.version:
        raise Fail(f"G37: tagName is {final.get('tagName')!r}, expected {pkg.version!r}")
    if final.get("name") != f"Release {pkg.version}":
        raise Fail(f"G37: title is {final.get('name')!r}, expected 'Release {pkg.version}'")
    _assert_asset(pkg, final, digest)
    ok(f"G37 published and re-verified: {final.get('url')}")
    return final.get("url", "")


def _assert_asset(pkg: Package, rel: dict, digest: str) -> None:
    want = f"{pkg.id}-{pkg.version}.tgz"
    assets = rel.get("assets") or []
    names = [a["name"] for a in assets]
    if names != [want]:
        raise Fail(
            f"G35: release {pkg.version} has assets {names}, expected exactly ['{want}']. "
            f"(This is the exact defect in Unity-Services 2.0.2, which carries "
            f"com.gamelovers.services-2.0.1.tgz.)"
        )
    asset = assets[0]
    if asset.get("state") != "uploaded":
        raise Fail(f"G35: asset state is {asset.get('state')!r}, expected 'uploaded'")
    got = (asset.get("digest") or "").removeprefix("sha256:")
    if got and got != digest:
        raise Fail(
            f"G35 DIGEST MISMATCH: the uploaded asset is sha256:{got[:16]}... but the "
            f"local tarball is sha256:{digest[:16]}... The wrong file was uploaded."
        )
    if not got:
        warn("G35 GitHub reported no digest for the asset; falling back to name+state only")


# --------------------------------------------------------------------------- #
# PR creation and host bump
# --------------------------------------------------------------------------- #


def open_pr(pkg: Package, f: dict) -> str:
    """G4 already guarantees develop is pushed, so this only opens the PR.

    House style, verified against Unity-Services #34, Statechart-HFSM #19 and
    Unity-GameData #18: title is `Release X.Y.Z` and the body is the CHANGELOG
    section VERBATIM with nothing else -- no added headings, no checklist, no
    footer. Do not embellish it; the body is reused as the release notes.
    """
    assert_identity()
    try:
        section = changelog.validate_pending(
            pkg.changelog,
            pkg.version,
            expected_date=dt.date.today().isoformat(),
            baseline_bytes=git_bytes(
                pkg.path, "show", f"origin/{RELEASE_BRANCH}:CHANGELOG.md"
            ),
        )
    except changelog.ChangelogError as exc:
        raise Fail(f"refusing to open a PR with invalid release notes: {exc}") from exc

    notes = pkg.pack_dir / "pr-body.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(f"{section['body']}\n")

    url = gh([
        "pr", "create",
        "--repo", pkg.repo,
        "--base", RELEASE_BRANCH,
        "--head", WORK_BRANCH,
        "--title", f"Release {pkg.version}",
        "--body-file", str(notes),
        "--assignee", GH_ACCOUNT,
    ])
    url = url.strip().splitlines()[-1] if url else ""

    # Assignee, not reviewer: GitHub refuses to request a review from the PR's own
    # author, and `gh pr edit --add-reviewer <author>` exits 0 while silently doing
    # nothing. Verify rather than trust the exit code.
    number = url.rstrip("/").rsplit("/", 1)[-1]
    assignees = gh([
        "pr", "view", number, "--repo", pkg.repo,
        "--json", "assignees", "-q", "[.assignees[].login]|join(\",\")",
    ], check=False)
    if GH_ACCOUNT not in assignees:
        warn(
            f"could not assign {GH_ACCOUNT} to PR #{number} (got {assignees or '<none>'}); "
            f"assign it manually so the release is not lost track of"
        )
    else:
        ok(f"PR #{number} assigned to {GH_ACCOUNT}")
    return url


def sync_pr_body(pkg: Package, f: dict) -> str:
    """Replace an existing release PR body and prove it matches the changelog."""
    pr = f["open_pr"]
    if not pr:
        raise Fail(f"no open {WORK_BRANCH}->{RELEASE_BRANCH} PR exists for {pkg.repo}")
    if f["dirty"]:
        raise Fail(
            "refusing to sync notes from an uncommitted package working tree; "
            "commit and push the CHANGELOG first"
        )
    local_head = git(pkg.path, "rev-parse", "HEAD")
    if local_head != f["develop_tip"] or pr.get("headRefOid") != f["develop_tip"]:
        raise Fail(
            f"release notes must describe the pushed PR head: local={local_head[:9]}, "
            f"origin/{WORK_BRANCH}={f['develop_tip'][:9]}, "
            f"PR={str(pr.get('headRefOid') or '<none>')[:9]}"
        )

    try:
        section = changelog.validate_pending(
            pkg.changelog,
            pkg.version,
            expected_date=dt.date.today().isoformat(),
            baseline_bytes=git_bytes(
                pkg.path, "show", f"origin/{RELEASE_BRANCH}:CHANGELOG.md"
            ),
        )
    except changelog.ChangelogError as exc:
        raise Fail(f"refusing to sync invalid release notes: {exc}") from exc
    notes = pkg.pack_dir / "pr-body.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(f"{section['body']}\n", encoding="utf-8")

    assert_identity()
    gh([
        "pr", "edit", str(pr["number"]), "--repo", pkg.repo,
        "--body-file", str(notes),
    ])
    reread = json.loads(
        gh([
            "pr", "view", str(pr["number"]), "--repo", pkg.repo,
            "--json", "body,headRefOid,url",
        ])
    )
    if reread.get("headRefOid") != f["develop_tip"]:
        raise Fail(
            f"PR #{pr['number']} moved while its body was being updated; "
            "re-run status before continuing"
        )
    if not notes_match(reread.get("body") or "", section["body"]):
        raise Fail(
            f"PR #{pr['number']} body still differs from the [{pkg.version}] changelog "
            "after GitHub reported success"
        )
    ok(
        f"PR #{pr['number']} body exactly matches [{pkg.version}] at "
        f"origin/{WORK_BRANCH} {f['develop_tip'][:9]}"
    )
    return reread.get("url") or pr["url"]


def bump_host(names: list[str]) -> None:
    """ONE serialized commit for all packages -- Barrier 2 of the parallel model.

    Six agents committing to the same host repo would collide on .git/index.lock
    and lose writes to the shared .architecture-log.md, so agents never touch the
    host repo; this runs once, alone.
    """
    root = host_root()
    bumped: list[tuple[Package, dict]] = []

    with Lock("__host__"):
        for name in names:
            pkg = Package(name)
            f = facts(pkg)
            good, why = release_is_good(pkg, f)
            if not good:
                warn(f"skipping {pkg.folder}: {why}")
                continue
            if f["pointer_current"]:
                note(f"{pkg.folder} pointer already current")
                continue
            bumped.append((pkg, f))

        if not bumped:
            print("nothing to bump")
            return

        paths = [f"Packages/{p.folder}" for p, _ in bumped]
        for path in paths:
            run(["git", "-C", str(root), "add", "--", path])

        _append_arch_log(root, bumped)
        run(["git", "-C", str(root), "add", "--", ".architecture-log.md"])

        if len(bumped) == 1:
            pkg = bumped[0][0]
            short = pkg.folder.removeprefix("com.gamelovers.")
            message = f"chore: bump {short} pointer ({pkg.version})"
        else:
            parts = ", ".join(
                f"{p.folder.removeprefix('com.gamelovers.')} {p.version}" for p, _ in bumped
            )
            message = f"chore: bump submodule pointers ({parts})"

        env = dict(os.environ)
        env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"] = GIT_NAME
        env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"] = GIT_EMAIL
        run(["git", "-C", str(root), "commit", "-m", message], env=env)
        ok(f"host commit: {message}")

        run(["git", "-C", str(root), "push", "origin", WORK_BRANCH])
        ok(f"pushed host {WORK_BRANCH}")


def _append_arch_log(root: pathlib.Path, bumped: list[tuple[Package, dict]]) -> None:
    log = root / ".architecture-log.md"
    if not log.is_file():
        warn(".architecture-log.md not found; skipping log entry")
        return

    today = dt.date.today().isoformat()
    titles = ", ".join(
        f"{p.folder.removeprefix('com.gamelovers.')} {p.version}" for p, _ in bumped
    )
    lines = [f"## {today} — Released {titles}", "", "### Structural Changes"]
    for pkg, f in bumped:
        url = (f["release"] or {}).get("url") or f"https://github.com/{pkg.repo}/releases/tag/{pkg.version}"
        lines.append(
            f"- `Packages/{pkg.folder}`: submodule pointer bumped to the `{pkg.version}` "
            f"release merge commit. Tag `{pkg.version}` on `{RELEASE_BRANCH}` of "
            f"`{pkg.repo}`, GitHub Release with the verified "
            f"`{pkg.id}-{pkg.version}.tgz` asset attached. {url}"
        )
    lines += ["", "---", ""]
    entry = "\n".join(lines)

    text = log.read_text(encoding="utf-8-sig")
    header = "# Architecture Log"
    if text.startswith(header):
        rest = text[len(header) :].lstrip("\n")
        log.write_text(f"{header}\n\n{entry}\n{rest}")
    else:
        log.write_text(f"{entry}\n{text}")
    ok(f".architecture-log.md entry added for {titles}")


# --------------------------------------------------------------------------- #
# Audit -- read-only
# --------------------------------------------------------------------------- #


ALL_PACKAGES = [
    "services", "statechart", "uiservice",
    "googlesheetimporter", "mobileservices", "gamedata",
]


def audit(names: list[str], limit: int | None) -> int:
    rows = []
    flagged = 0

    for name in names:
        pkg = Package(name)
        releases = json.loads(
            gh(["release", "list", "--repo", pkg.repo, "--limit", str(limit or 200),
                "--json", "tagName"]) or "[]"
        )
        for rel in releases:
            tag = rel["tagName"]
            row = {"package": pkg.folder, "repo": pkg.repo, "tag": tag,
                   "asset": None, "org_id": None, "org_name": None,
                   "tar_owner": None, "status": ""}
            workdir = CACHE / "audit" / pkg.folder / tag
            shutil.rmtree(workdir, ignore_errors=True)
            workdir.mkdir(parents=True, exist_ok=True)

            gh(["release", "download", tag, "--repo", pkg.repo,
                "--pattern", "*.tgz", "--dir", str(workdir)], check=False)
            found = sorted(workdir.glob("*.tgz"))
            if not found:
                row["status"] = "no asset"
                rows.append(row)
                continue

            tgz = found[0]
            row["asset"] = tgz.name
            if tgz.name != f"{pkg.id}-{tag}.tgz":
                # Distinguish a real defect from benign history. Several packages
                # were renamed (nativeui -> mobileservices, dataextensions ->
                # gamedata), so a differing *id* with a matching version is
                # expected. A differing *version* is the 2.0.2-class defect.
                stem = tgz.name.removesuffix(".tgz")
                asset_version = stem.rsplit("-", 1)[-1] if "-" in stem else ""
                if asset_version != tag:
                    row["status"] = f"VERSION MISMATCH (asset is {asset_version or '?'})"
                    flagged += 1
                else:
                    row["status"] = "renamed id (benign)"

            try:
                with tarfile.open(tgz, "r:gz") as tf:
                    owners = {m.uname for m in tf.getmembers() if m.uname}
                row["tar_owner"] = ",".join(sorted(o for o in owners if o not in ("", "root")))
                att = read_attestation(tgz)
                if att:
                    row["org_id"] = str(att.get("ownerOrgId", ""))
                    row["org_name"] = str(att.get("ownerOrgName", ""))
                    if any(b in row["org_name"].lower() for b in FORBIDDEN_ORG_SUBSTRINGS):
                        row["status"] = (row["status"] + " ORG LEAK").strip()
                        flagged += 1
                    elif row["org_id"] != UNITY_ORG_ID:
                        row["status"] = (row["status"] + " wrong org").strip()
                        flagged += 1
            except Exception as exc:  # noqa: BLE001 - audit must never abort mid-sweep
                row["status"] = f"read error: {exc}"

            shutil.rmtree(workdir, ignore_errors=True)
            rows.append(row)

    print(f"\n{'package':22} {'tag':8} {'org id':15} {'org name':34} {'tar owner':16} status")
    print("-" * 118)
    for r in rows:
        print(
            f"{r['package'].removeprefix('com.gamelovers.'):22} {r['tag']:8} "
            f"{(r['org_id'] or '-'):15} {(r['org_name'] or '-'):34} "
            f"{(r['tar_owner'] or '-'):16} {r['status']}"
        )

    print(f"\n{len(rows)} release(s) audited, {flagged} flagged")
    out = CACHE / "audit-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))
    print(f"report: {out}")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def cmd_status(args) -> int:
    pkg = Package(args.package)
    f = facts(pkg)
    phase, why = resolve_phase(pkg, f)

    if args.json:
        print(json.dumps({**f, "phase": phase, "reason": why}, indent=2))
        return 0

    print(f"package   {pkg.folder}  ({pkg.id})")
    print(f"repo      {pkg.repo}" + ("" if pkg.repo == pkg.origin_slug else f"   [origin says {pkg.origin_slug} -- STALE]"))
    print(f"version   {pkg.version}   {RELEASE_BRANCH}={f['master_version']}   latest tag={changelog.prev_tag(f['tags'], '999.999.999') or '-'}")
    print(f"branch    {f['branch']}   dirty={len(f['dirty'].splitlines())} file(s)")
    print(f"tag       {f['tag_sha'][:9] if f['tag_sha'] else '(none)'}")
    print(f"release   {'draft' if (f['release'] or {}).get('isDraft') else ('published' if f['release'] else '(none)')}")
    if f["release"]:
        print(f"assets    {[a['name'] for a in (f['release'].get('assets') or [])]}")
    print(f"open PR   {f['open_pr']['url'] if f['open_pr'] else '(none)'}")
    if f["open_pr"]:
        print(f"PR notes  {'current' if f['pr_notes_current'] else 'STALE'}")
    print(f"tarball   {'present' if f['tarball_present'] else 'absent'}  {pkg.tarball}")
    print(f"host ptr  {'current' if f['pointer_current'] else 'STALE'}")
    print(f"\nPHASE     {phase}\n          {why}")
    return 0


def cmd_notes_status(args) -> int:
    pkg = Package(args.package)
    f = facts(pkg)
    if not f["open_pr"]:
        print(f"NO_OPEN_PR {pkg.repo} {WORK_BRANCH}->{RELEASE_BRANCH}")
        return 0
    state = "CURRENT" if f["pr_notes_current"] else "STALE"
    print(
        f"{state} PR #{f['open_pr']['number']} body vs "
        f"CHANGELOG [{pkg.version}] at origin/{WORK_BRANCH} {f['develop_tip'][:9]}"
    )
    return 0 if f["pr_notes_current"] else 1


def cmd_sync_pr_body(args) -> int:
    pkg = Package(args.package)
    with Lock(pkg.folder):
        url = sync_pr_body(pkg, facts(pkg))
    print(f"\nPR notes synchronized and verified: {url}")
    return 0


def cmd_preflight(args) -> int:
    pkg = Package(args.package)
    preflight(pkg, facts(pkg), run_tests=args.tests)
    print("\npreflight PASSED")
    return 0


def cmd_preflight_pr(args) -> int:
    """Package-local gates only, for a CI check on a develop->master PR.

    Runs against a standalone checkout with no host repo, no submodules, no
    GitHub token and no network: everything here is decidable from the package
    directory plus the base ref. That keeps it usable as a required status check
    on a fork or a bare clone. The remote-state gates (G0-G6, G12-G14) belong to
    the local `preflight`, which runs before packing.
    """
    path = pathlib.Path(args.path).resolve()
    manifest_file = path / "package.json"
    if not manifest_file.is_file():
        raise Fail(f"no package.json at {path}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    pkg_id, version = manifest.get("name"), manifest.get("version")
    changelog_file = path / "CHANGELOG.md"
    print(f"preflight-pr: {pkg_id} {version}  (base {args.base})")

    if not SEMVER_RE.match(version or ""):
        raise Fail(
            f"G7: version {version!r} is not bare X.Y.Z. Every historical tag is bare "
            f"SemVer -- no v-prefix, no prerelease suffix."
        )
    ok(f"G7  version {version} is bare SemVer")

    if not changelog_file.is_file():
        raise Fail(f"G8: no CHANGELOG.md at {path}")

    # G8/G9/D1-D7: exists, unique, first, semver-max, non-empty, clean boundary.
    section = changelog.section_for(changelog_file, version, require_newest=True)
    ok(f"G8  package.json {version} == CHANGELOG heading at line {section['line']}")
    ok("G9  CHANGELOG section is the newest and the highest")

    if dt.date.fromisoformat(section["date"]) > dt.date.today():
        raise Fail(f"G10: CHANGELOG date {section['date']} for {version} is in the future.")
    ok(f"G10 CHANGELOG date {section['date']} is sane")

    # G28 -- the same check the tarball gets, but against the checkout, so CI fails
    # the PR instead of the packer failing later. In CI this is only meaningful when
    # the workflow checks out with `lfs: true`; it then doubles as proof that the
    # objects are actually FETCHABLE from the remote, which is the failure mode that
    # bit uiservice (published 1.2.1 had real content, the working tree had stubs).
    pointers = lfs_pointers_in_tree(path)
    if pointers:
        raise Fail(
            f"G28: {len(pointers)} unresolved git-lfs pointer(s) in the checkout: "
            f"{pointers[:5]}. These would be packed verbatim, shipping ~130-byte stubs "
            f"instead of real content. In CI, check out with `lfs: true`; locally run "
            f"`git lfs fetch origin <branch> && git lfs checkout`."
        )
    ok("G28 no unresolved git-lfs pointers")

    base_manifest = run(["git", "-C", str(path), "show", f"{args.base}:package.json"], check=False)
    if not base_manifest:
        warn(f"G11/G15 skipped: could not read {args.base}:package.json")
        print(f"\npreflight-pr PASSED for {pkg_id} {version}")
        return 0

    base_version = json.loads(base_manifest).get("version")
    changed = run(
        ["git", "-C", str(path), "diff", "--name-only", f"{args.base}...HEAD"], check=False
    ).splitlines()

    # Not every develop->master PR is a release. A CI- or docs-only PR leaves the
    # version untouched, and holding it to the release gates would fail it for the
    # wrong reason. Verify the invariants that still apply instead, so this stays
    # usable as a required status check on ANY PR into master.
    if version == base_version:
        note(f"not a release PR: version stays at {version}")
        if "CHANGELOG.md" in changed:
            raise Fail(
                f"G15: this PR edits CHANGELOG.md but does not bump the version "
                f"(still {version}). Either bump it, or drop the CHANGELOG edit -- a "
                f"published section must not change after the fact."
            )
        ok("G15 CHANGELOG.md untouched, consistent with an unchanged version")
        print(f"\npreflight-pr PASSED for {pkg_id} {version} (non-release PR)")
        return 0

    if changelog.semver(base_version) and changelog.semver(version) < changelog.semver(base_version):
        raise Fail(f"G11: version {version} goes BACKWARDS from {args.base}'s {base_version}.")
    ok(f"G11 {version} advances past {args.base}'s {base_version}")

    missing = [n for n in ("package.json", "CHANGELOG.md") if n not in changed]
    if missing:
        raise Fail(
            f"G15: this PR bumps the version but does not touch {missing}. A release "
            f"PR must bump the version and add a CHANGELOG section."
        )
    ok("G15 diff touches package.json and CHANGELOG.md")

    print(f"\npreflight-pr PASSED for {pkg_id} {version}")
    return 0


def cmd_pack(args) -> int:
    pkg = Package(args.package)
    with Lock(pkg.folder):
        f = facts(pkg)

        # The tarball is built from the WORKING TREE, not from a git ref, so a dirty
        # or untracked file ships to consumers and is unreproducible from git. This
        # is not merely preflight's G3: packing must enforce it independently, because
        # `pack` is reachable without `preflight`. Caught in the wild -- 7 untracked
        # WIP files under uiservice Samples~/UrpRendering/ were packed into a tarball.
        if f["dirty"]:
            raise Fail(
                f"G3: {len(f['dirty'].splitlines())} uncommitted/untracked path(s) in "
                f"{pkg.folder}. The tarball is built from the working tree, so this "
                f"content would ship to consumers without existing in git.\n"
                f"{f['dirty']}\n"
                f"  Commit it, stash it, or remove it -- there is deliberately no override."
            )

        # Local HEAD is what gets packed; assert it matches what is pushed, so the
        # artifact corresponds to a commit others can actually fetch.
        local_head = git(pkg.path, "rev-parse", "HEAD")
        if local_head != f["develop_tip"]:
            raise Fail(
                f"G4: HEAD {local_head[:9]} != origin/{WORK_BRANCH} "
                f"{f['develop_tip'][:9]}. Push or pull before packing, or the tarball's "
                f"repository.revision will point at a commit that is not on the remote."
            )

        head = local_head
        before_pkg, before_host = f["dirty"], run(["git", "-C", str(pkg.host), "status", "--porcelain"])

        tgz, tier = pack(pkg, args.tier)
        ok(f"packed via tier {tier}: {tgz.name}")

        info = verify_tarball(tgz, pkg.id, pkg.version, tier=tier, head_sha=head)
        ok(f"G20-G27 passed: {info['files']} files, sha256:{info['sha256'][:16]}...")
        if info["attestation"]:
            att = info["attestation"]
            ok(f"G26 attested as org {att.get('ownerOrgId')} ({att.get('ownerOrgName')})")

        diff_previous(pkg, tgz, changelog.prev_tag(f["tags"], pkg.version))

        # G25 -- packing must not touch either working tree.
        after_pkg = git(pkg.path, "status", "--porcelain")
        after_host = run(["git", "-C", str(pkg.host), "status", "--porcelain"])
        if after_pkg != before_pkg or after_host != before_host:
            raise Fail(
                "G25: packing changed a working tree (likely Unity .meta generation).\n"
                f"  submodule before/after: {len(before_pkg.splitlines())}/{len(after_pkg.splitlines())}\n"
                f"  host before/after:      {len(before_host.splitlines())}/{len(after_host.splitlines())}"
            )
        ok("G25 no working-tree side effects")
        print(f"\ntarball: {tgz}")
    return 0


def cmd_verify_tarball(args) -> int:
    info = verify_tarball(
        pathlib.Path(args.tarball), args.id, args.version,
        tier=args.tier, head_sha=args.head_sha,
    )
    print(json.dumps(info, indent=2))
    return 0


def cmd_open_pr(args) -> int:
    pkg = Package(args.package)
    with Lock(pkg.folder):
        f = facts(pkg)
        preflight(pkg, f)
        if not pkg.tarball.is_file():
            raise Fail(f"no verified tarball at {pkg.tarball}. Run `pack {pkg.folder}` first.")
        url = open_pr(pkg, f)
        print(f"\nPR opened: {url}")
        print(
            "\nHALT. Merge this PR yourself with a MERGE COMMIT (not squash, not rebase),\n"
            f"then re-run:  release.py status {args.package}"
        )
    return 0


def cmd_tag(args) -> int:
    pkg = Package(args.package)
    with Lock(pkg.folder):
        f = facts(pkg)
        phase, why = resolve_phase(pkg, f)
        if phase != "P3_TAG":
            raise Fail(f"refusing to tag: phase is {phase} ({why})")
        merge_sha = find_merge_commit(pkg, f)
        create_tag(pkg, merge_sha)
        print(f"\ntagged {pkg.version} -> {merge_sha[:9]}")
    return 0


def cmd_publish(args) -> int:
    pkg = Package(args.package)
    with Lock(pkg.folder):
        f = facts(pkg)
        phase, why = resolve_phase(pkg, f)
        if phase not in ("P4_RELEASE", "P4b_PUBLISH_DRAFT"):
            raise Fail(f"refusing to publish: phase is {phase} ({why})")
        url = publish_release(pkg, f)
        print(f"\nreleased: {url}")
    return 0


def cmd_install_preflight(args) -> int:
    """Copy the release-preflight workflow into a package repo and commit it.

    Each package intentionally tracks the workflow while listing `.github/` in
    `.gitignore`, which Unity's packer uses to exclude CI files from the tarball.
    """
    template = pathlib.Path(__file__).resolve().parent.parent / "workflows/release-preflight.yml"
    body = template.read_text()

    for name in args.packages or ALL_PACKAGES:
        pkg = Package(name)
        dest = pkg.path / ".github/workflows/release-preflight.yml"

        # Compare against HEAD, not the disk. A run that wrote the file but failed
        # before committing would otherwise look "already up to date" and be skipped
        # forever, leaving the change uncommitted. (Observed: the add without -f
        # failed after the write.)
        committed = git(
            pkg.path, "show", f"HEAD:.github/workflows/release-preflight.yml", check=False
        )
        if committed and committed.rstrip("\n") == body.rstrip("\n") and dest.is_file():
            note(f"{pkg.folder}: already up to date")
            continue

        # Ignore the workflow's own path when judging cleanliness: a previous partial
        # run may have left exactly that file modified, and refusing would deadlock.
        dirty = [
            line for line in git(pkg.path, "status", "--porcelain").splitlines()
            if ".github/workflows/release-preflight.yml" not in line
        ]
        if dirty:
            warn(f"{pkg.folder}: skipping, working tree is dirty\n" + "\n".join(dirty))
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)

        env = dict(os.environ)
        env["GIT_COMMITTER_NAME"] = env["GIT_AUTHOR_NAME"] = GIT_NAME
        env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_EMAIL"] = GIT_EMAIL
        # -f is required and correct: each package lists `.github/` in .gitignore so
        # Unity's packer keeps it out of the tarball, but the file must stay TRACKED
        # for the workflow to exist on GitHub. .gitignore cannot untrack an existing
        # path, so this only silences git's "explicitly named an ignored path" guard.
        run([
            "git", "-C", str(pkg.path), "add", "-f", "--",
            ".github/workflows/release-preflight.yml",
        ])
        subject = (
            "ci: update release-preflight check"
            if committed
            else "ci: add release-preflight check for develop->master PRs"
        )
        run(["git", "-C", str(pkg.path), "commit", "-m", subject], env=env)
        if not args.no_push:
            run(["git", "-C", str(pkg.path), "push", "origin", WORK_BRANCH])
        ok(f"{pkg.folder}: installed{'' if args.no_push else ' and pushed'}")
    return 0


def cmd_bump_host(args) -> int:
    bump_host(args.packages or ALL_PACKAGES)
    return 0


def cmd_audit(args) -> int:
    return audit(args.packages or ALL_PACKAGES, args.limit)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="release.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status"); p.add_argument("package"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("notes-status"); p.add_argument("package"); p.set_defaults(fn=cmd_notes_status)
    p = sub.add_parser("sync-pr-body"); p.add_argument("package"); p.set_defaults(fn=cmd_sync_pr_body)
    p = sub.add_parser("preflight"); p.add_argument("package"); p.add_argument("--tests", action="store_true"); p.set_defaults(fn=cmd_preflight)
    p = sub.add_parser("preflight-pr")
    p.add_argument("--path", default=".", help="package directory (standalone checkout)")
    p.add_argument("--base", default="origin/master", help="base ref of the PR")
    p.set_defaults(fn=cmd_preflight_pr)
    p = sub.add_parser("pack"); p.add_argument("package"); p.add_argument("--tier", type=int, choices=[1, 2, 3]); p.set_defaults(fn=cmd_pack)
    p = sub.add_parser("verify-tarball")
    p.add_argument("tarball"); p.add_argument("id"); p.add_argument("version")
    p.add_argument("--tier", type=int, choices=[1, 2, 3]); p.add_argument("--head-sha")
    p.set_defaults(fn=cmd_verify_tarball)
    p = sub.add_parser("open-pr"); p.add_argument("package"); p.set_defaults(fn=cmd_open_pr)
    p = sub.add_parser("tag"); p.add_argument("package"); p.set_defaults(fn=cmd_tag)
    p = sub.add_parser("publish"); p.add_argument("package"); p.set_defaults(fn=cmd_publish)
    p = sub.add_parser("install-preflight")
    p.add_argument("packages", nargs="*")
    p.add_argument("--no-push", action="store_true")
    p.set_defaults(fn=cmd_install_preflight)
    p = sub.add_parser("bump-host"); p.add_argument("packages", nargs="*"); p.set_defaults(fn=cmd_bump_host)
    p = sub.add_parser("audit"); p.add_argument("packages", nargs="*"); p.add_argument("--limit", type=int); p.set_defaults(fn=cmd_audit)

    args = parser.parse_args(argv[1:])
    try:
        return args.fn(args)
    except Fail as exc:
        print(f"\nFATAL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
