---
name: unity-package-release
description: Use when preparing or validating a changelog, opening or refreshing a release PR, publishing, tagging, shipping, or auditing a GameLovers UPM package under `Packages/`.
---

# Unity Package Release

Prepares and releases one UPM package from `Packages/` to its own GitHub repo, reproducing the established release shape. Changelog preparation belongs to this skill because the pending entry becomes both the release PR body and the published release notes. The workflow **halts for the user to merge the PR** — the agent never promotes `develop` → `master`.

All mechanics live in `scripts/`. **Run those scripts; do not reimplement their checks in prose or ad-hoc shell.** They encode 38 verification gates derived from real defects in this repo's release history, and a paraphrase will miss them.

## When to Use

- "Release `<package>`", "publish `<package>` `X.Y.Z`", "ship the new statechart version"
- "Prepare/fix the package changelog", "make the pending release notes consumer-facing"
- "Refresh the release PR body from the changelog"
- "Tag and release the pending versions" (all six packages currently have unreleased versions)
- Resuming a release after merging the PR — even in a brand-new session
- "Audit the published releases" / checking artifacts for wrong-org attestations

Do NOT trigger for host-repo-only changes unrelated to a package release.

## Preconditions and Hard Rules

- **NEVER merge `develop` → `master`.** The agent opens the PR and stops. The user merges. This is a standing rule, and the whole phase machine depends on it.
- **NEVER force-push. NEVER delete or move an existing tag.** A tag on the wrong commit is a HALT with printed remediation, never a self-heal.
- **NEVER publish an unverified release.** Always draft → verify digest → publish.
- **Commit/tag identity MUST be `CoderGamester <game.gamester@gmail.com>`.** The scripts set this explicitly.
- **Every `gh` call MUST carry the CoderGamester token.** The machine's *active* `gh` account is a different one; the scripts inject `GH_TOKEN` per invocation and re-assert identity before every write. Never call bare `gh` for a write.
- **The agent never touches the host repo** except through `release.py bump-host`, which is serialized and runs once at the end.
- **The package repository is the PR source of truth.** An empty host-repository PR list says nothing about package releases; query each submodule's canonical remote.
- **Only the pending changelog region may change.** Historical release bytes, BOM, line endings, and EOF convention are invariants.
- Tags are **bare SemVer, no `v` prefix**; annotated with an **empty message**; on the **2-parent merge commit**.

## Workflow

Always start here. `status` derives every fact from the package git/GitHub repository and resolves the phase — there is no state file, so this is what makes resuming work:

```bash
python3 .claude/skills/unity-package-release/scripts/release.py status <package>
```

`<package>` accepts `statechart` or `com.gamelovers.statechart`.

| Phase | Meaning | Next |
|---|---|---|
| `P1_PACK_PR` | ready to cut | Step 1 |
| `P2_SYNC_NOTES` | open PR body is stale | Step 0.5 |
| `P2_AWAIT_MERGE` | PR open | **halt** — tell the user to merge |
| `P2x_PR_CLOSED` | PR closed unmerged | **halt** — ambiguous, ask the user |
| `P3_TAG` | merged, not tagged | Step 3 |
| `P4_RELEASE` | tagged, no release | Step 4 |
| `P4b_PUBLISH_DRAFT` | draft exists | Step 4 |
| `P5_FIX_ASSET` | release has wrong assets | **halt** — mutating a published release needs explicit user approval |
| `P6_HOST_BUMP` | released, pointer stale | Step 5 |
| `P7_DONE` | complete | report and stop |
| `P0_NOT_READY` | version not ahead of `master` | **halt** — bump version + CHANGELOG first |

### Step 0 — Prepare the changelog

Do this before packing, and whenever a user asks to improve pending release notes. Treat the current changelog and commit subjects as draft evidence, not as the source of truth.

1. Read the package's `AGENTS.md`, `package.json`, pending changelog entry, and relevant consumer documentation.
2. Fetch the package remote and inspect the complete `origin/master...origin/develop` diff. Inventory public API, runtime behavior, dependencies, Unity/platform compatibility, samples, migrations, and consumer documentation. Do not infer package PRs from the host repository.
3. Reconcile every inventory item against the pending entry. A missing breaking change, migration, dependency, sample-compilation fix, or observable runtime change blocks release.
4. Rewrite only the pending region. Merge `Unreleased` into the existing unpublished version; do not create another version for work that has not shipped.
5. Validate structure and preservation. The date must be the intended publication date; re-run this on the actual release day if publication is delayed.

The editorial contract:

- Use `**New**:`, `**Changed**:`, `**Fixed**:`, plus `**Removed**:`, `**Migration**:`, and `**Docs**:` only when relevant.
- Consumer-facing does **not** mean generic. Give each independently useful capability or observable change its own concise bullet.
- For an initial, major, or consolidation release, use one labeled `**New**:` bullet per public subsystem (for example `- **Notifications**: ...`). Never blend distinct public subsystems into one umbrella sentence.
- Keep actionable public type and feature names. State breaking changes, removals, migration mappings, supported alternatives, platform/pipeline baselines, required dependencies, and sample impacts explicitly.
- Combine private implementation details that support one outcome. Omit test names/counts, audit terminology, contributor files, CI cleanup, XML-comment mechanics, private helpers, and internal refactors.
- Mention automated coverage at most once, generically, and only when it materially improves confidence. Mention documentation only when it changes what consumers can successfully adopt.

Use the bounded writer when an `Unreleased` and target-version entry must be merged. Author only the replacement body in a temporary Markdown file, then run:

```bash
python3 .claude/skills/unity-package-release/scripts/changelog.py \
  rewrite-pending Packages/<package>/CHANGELOG.md <version> <YYYY-MM-DD> <BODY.md>
```

Validate the result against an `origin/master` CHANGELOG snapshot. A pre-edit copy can already contain accidental historical drift and is not release evidence:

```bash
python3 .claude/skills/unity-package-release/scripts/changelog.py \
  validate-pending Packages/<package>/CHANGELOG.md <version> <YYYY-MM-DD> \
  --baseline <BASELINE-CHANGELOG.md>
git -C Packages/<package> diff --check
git -C Packages/<package> diff -- CHANGELOG.md
```

The validator checks the target version/date, removal of `Unreleased`, canonical labels, duplicate structure, and byte-identical published history. Editorial completeness still requires the diff inventory; a structural checker cannot decide whether release notes omitted a public feature.

Commit and push each package independently, staging only its `CHANGELOG.md`. Before syncing notes, prove local `HEAD == origin/develop`; the script additionally proves that the open PR head is the same commit. Leave unrelated host dirt untouched.

### Step 0.5 — Synchronize an existing release PR

After any changelog edit, compare the open package PR body with the pending entry:

```bash
release.py notes-status <package>
release.py sync-pr-body <package>
```

`notes-status` exits nonzero for stale notes. `sync-pr-body` requires a clean, pushed package tree, re-asserts the `CoderGamester` GitHub identity, updates the existing PR rather than opening another, re-reads it, and requires exact body equality after newline normalization. `status` reports `P2_SYNC_NOTES` until this is done, then `P2_AWAIT_MERGE`.

### Step 1 — Preflight and pack

```bash
release.py preflight <package>          # gates G0-G16, no mutation
release.py pack <package>               # tier 1 -> 2 -> 3, then gates G20-G27
```

`pack` tries tiers in order and reports which it used:

| Tier | Mechanism | Attestation | `repository` block | tar owner |
|---|---|---|---|---|
| 1 | `upm pack --organization-id 129325` | ✅ Tropa Elite | ✅ | leaks local username |
| 2 | Unity `Client.Pack` batchmode (~17s) | ❌ | ✅ | leaks local username |
| 3 | `npm pack` | ❌ | ❌ *degraded* | normalized |

Tier 1 needs `UPM_SERVICE_ACCOUNT_KEY_ID` + `UPM_SERVICE_ACCOUNT_KEY_SECRET` for the Tropa Elite org. Without them the skill silently uses tier 2, which is still correct — it just carries no provenance signature. **Report the tier used**; if tier 3 was used, say the artifact is degraded fidelity.

Force a tier with `--tier N` — that disables fallback so a failure is loud.

### Step 2 — Open the PR, then HALT

```bash
release.py open-pr <package>
```

Re-runs preflight, requires a verified tarball, and opens `develop` → `master` titled `Release X.Y.Z` with the CHANGELOG section as the body **verbatim and nothing else** — matching Unity-Services #34, Statechart-HFSM #19, Unity-GameData #18. Do not embellish the body; it doubles as the release notes. If a matching PR already exists, do not open another; use Step 0.5.

Every release PR is **assigned to `CoderGamester`** so it can't be lost track of. It is an *assignee*, not a reviewer: GitHub refuses to request review from a PR's own author, and `gh pr edit --add-reviewer <author>` exits 0 while silently doing nothing. The script verifies the assignment afterwards rather than trusting the exit code.

Then **stop and tell the user**: give them the PR URL, and say the release completes only after they merge it — with a **merge commit**, not squash or rebase. Squash and rebase are both still enabled on all six repos, and a mis-click breaks the tag model (`G30` will catch it, but after the fact).

### Step 3 — Tag the merge commit (post-merge only)

```bash
release.py tag <package>
```

Refuses unless the phase is `P3_TAG`. Enforces `G30` (2-parent merge), `G31` (merge preserved the tree), `G32` (`master` carries the version), `G32b` (the tarball's `repository.revision` == the merge commit's develop-side parent), then pushes an annotated tag and re-reads it (`G33`).

### Step 4 — Publish the release

```bash
release.py publish <package>
```

Creates a **draft** with `--verify-tag`, verifies the uploaded asset's `sha256` digest against the local tarball (`G35` — the only gate that catches "right filename, wrong bytes"), publishes, then re-reads and re-verifies (`G37`).

If the tarball is gone (new session), re-run `pack` first — the pack dir is cached under `~/Library/Caches/GameLovers/upm-release/`, so it normally survives.

### Step 5 — Bump the host pointer (serialized, once)

```bash
release.py bump-host <package>...        # omit args for all six
```

Verifies each release is genuinely good, stages only `Packages/<pkg>` and `.architecture-log.md`, writes **one** `.architecture-log.md` entry, makes **one** commit (`chore: bump submodule pointers (...)`), and pushes host `develop`.

## Parallel Releases

For several packages at once, fan out **one agent per package** — max 6, and never parallelize *within* a package.

```
Phase A  6 agents ─▶ preflight → pack → open-pr → halt
              ════ BARRIER 1: the user merges all PRs ════
Phase B  6 agents ─▶ tag → publish
              ════ BARRIER 2: one orchestrator ════
                    release.py bump-host <all>
```

Why the barriers are mandatory:

- **The cached Unity packer project is a single lock.** Two concurrent tier-2 packs on the same `-projectPath` corrupt its `Library/`. Tier 1 has no project and no lock, so it is naturally parallel-safe — prefer it for parallel runs. `release.py` also takes a per-package `mkdir`-based advisory lock, so a double-invocation refuses rather than races.
- **The host repo cannot take 6 concurrent commits.** They collide on `.git/index.lock` and lose writes to the shared `.architecture-log.md`. Hence one serialized `bump-host`.
- **Fail isolation**: one package failing its gates must not block the others. `bump-host` skips packages whose release isn't verified and says so.

`status --json` and `verify-tarball` print only JSON on stdout (progress goes to stderr), so agents can pipe them.

## Auditing Published Artifacts

```bash
release.py audit                        # all six repos, all releases
release.py audit statechart --limit 5
```

Read-only. Downloads each release asset, verifies the PKCS#7 attestation payload, and tabulates `tag → ownerOrgId / ownerOrgName / tar-owner`, flagging wrong-org attestations and asset-name mismatches. Embarrassingly parallel — no locks — so it can fan out much wider than 6.

**Why this exists:** the published `statechart 0.9.4` attestation carries `ownerOrgName: "miguel-cartier-supercell-com"`, a work-identity-derived Unity org, inside a public OSS artifact. `G26` prevents recurrence; the audit sizes the historical damage.

**Repairing history is NOT part of this skill.** Tarballs are not byte-reproducible (real tar mtimes, plus the local username as tar owner), so replacing a historical asset is a *re-publication* that breaks anyone who pinned a digest. Present the audit table and let the user decide. If they want a specific release fixed, re-pack from `git rev-list --parents -n1 <tag>` field 3 (the develop-side parent that was originally packed) and get explicit per-release approval before touching the asset.

## Common Pitfalls

- **Stale `origin` URLs.** `services` → `Unity-Services` and `uiservice` → `Unity-UiService` were renamed; `.gitmodules` still has the old names. `G1` halts both. This is not cosmetic — Unity bakes `origin`'s URL into the artifact's `package.json`, and published `uiservice 1.2.1` already carries the wrong one. Fix the remote and `.gitmodules`, don't bypass the gate.
- **Bare `gh` for a write** → the release gets authored by the wrong account. Always go through the scripts.
- **`gh release create` without `--verify-tag`** → if the tag push silently failed, `gh` invents a tag at the branch head and you publish a release pointing at the wrong commit.
- **A stale `.tgz` in the pack dir** → this is exactly how `Unity-Services 2.0.2` shipped `com.gamelovers.services-2.0.1.tgz`. `G20` refuses on any sibling tarball; `pack` empties the dir first.
- **Reusing a tarball across versions.** `G22` reads the version from *inside* the tarball. Never hand-upload an asset.
- **`--notes "$(...)"`** mangles backticks and `$` in changelog text. The scripts use `--notes-file`.
- **Two CLIs that report failure while exiting 0.** `gh pr edit --add-reviewer <author>` silently no-ops, and `upm pack` prints `Invalid service account credentials provided.` with `rc=0` and no tarball. Both are guarded by verifying the *artifact*, not the exit code — apply that habit to any new CLI call.
- **Historical CHANGELOG dialect drift is not a problem** — leave it byte-identical. Pending entries use the canonical bold-label dialect. `changelog.py` preserves BOM, CRLF/LF, history, and EOF conventions; hand-rolled whole-file rewrites do not.
- **A clean host PR list is not package evidence.** Release PRs live in six separate submodule repositories. `status` resolves the canonical repo from each package remote.
- **Pushing notes is not enough.** Require local `HEAD`, `origin/develop`, and the PR head SHA to agree, then re-read the body; a successful CLI exit alone does not prove the right PR was updated.
- **`.attestation.p7m` in a file-list diff** is a packer artifact, not package content. `G24` excludes it; `G26` checks it separately.
- **Unity `.meta` pollution.** The packer project lives in `~/Library/Caches`, outside any repo, precisely so a pack can't create `.meta` files in the host tree. `G25` asserts both working trees are unchanged after packing.

## Done When

- `release.py status <package>` reports `P7_DONE`.
- The tag is annotated, bare SemVer, on a 2-parent merge commit, tagger `CoderGamester <game.gamester@gmail.com>`.
- The release is titled `Release X.Y.Z`, is not a draft, and has exactly one asset `<id>-<version>.tgz` whose `sha256` digest matches the local tarball.
- The host `develop` carries the submodule pointer bump and one `.architecture-log.md` entry, and is pushed.
- The pending changelog passes `validate-pending`, and any open PR body exactly matches that entry.
- The tier used was reported to the user, and any `G23`/`G27` degradation warnings were surfaced rather than swallowed.

## Reference

- Scripts: `scripts/release.py`, `scripts/changelog.py`, `scripts/UpmPack.cs`
- CHANGELOG dialect: root `AGENTS.md` §6.5 — canonical is `**New**:` / `**Changed**:` / `**Fixed**:` / `**Docs**:`
- Pre-publication versioning: root `AGENTS.md` §2.7 — do not open a new `## [X.Y.Z]` section until actually cutting a release
- Submodule workflow: root `AGENTS.md` §5
