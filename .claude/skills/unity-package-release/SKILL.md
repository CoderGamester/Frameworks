---
name: unity-package-release
description: Use when preparing or validating a changelog, opening or refreshing a release PR, publishing, tagging, shipping, or auditing a GameLovers UPM package under `Packages/`.
---

# Unity Package Release

Prepares and releases one UPM package from `Packages/` to its own GitHub repo, reproducing the established release shape. Changelog preparation belongs to this skill because the pending entry becomes both the release PR body and the published release notes. The workflow **halts for the user to merge the PR** — the agent never promotes `develop` → `master`.

All mechanics live in `scripts/`. **Run those scripts; do not reimplement their checks in prose or ad-hoc shell.** Every gate they encode came from a real defect in this repo's release history — a wrong tarball on a published release, a work-identity org signed into a public artifact, uncommitted files shipped to consumers, git-lfs stubs masquerading as audio — and a paraphrase will miss them.

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
- **The agent never touches the host repo** except through `release.py bump-host` (directly or through `complete`), which is serialized and runs once at the end.
- **The package repository is the PR source of truth.** An empty host-repository PR list says nothing about package releases; query each submodule's canonical remote.
- **Only the pending changelog region may change.** Historical release bytes, BOM, line endings, and EOF convention are invariants.
- **Sample and native-build changes require the sample-builder gate.** If the release diff touches `Samples~`, sample scene/build preparation, temporary sample configuration, or package-owned native generation, run `unity-package-sample-builder` and retain its applicable imported-artifact, identity, cleanup, and idempotence evidence before packing.
- **Documentation, dependency, and compatibility changes require the docs-audit gate.** Run `package-docs-audit` before packing and retain its clean-install, link/anchor, sample-inventory, metadata, and claim-evidence results.
- **Release work happens on an attached package branch.** A detached submodule `HEAD` may be inspected, but do not author or commit release work there. Prove the intended branch and its upstream before the first mutation.
- **Unity assets must carry stable metadata.** A release that adds a sample file or folder without its `.meta` is incomplete even if a later local Editor open would generate one.
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
3. Reconcile every inventory item against the pending entry. A missing breaking change, migration, dependency, sample-compilation fix, or observable runtime change blocks release. If the minimum Unity version, dependency graph, install manifest, or sample inventory changed, require current clean-host evidence for the exact source identity before wording the change as supported or validated.
4. Rewrite only the pending region. Merge `Unreleased` into the existing unpublished version; do not create another version for work that has not shipped.
5. Validate structure and preservation. The date must be the intended publication date; re-run this on the actual release day if publication is delayed.

The editorial contract:

- Use `**New**:`, `**Changed**:`, `**Fixed**:`, plus `**Removed**:`, `**Migration**:`, and `**Docs**:` only when relevant.
- Consumer-facing does **not** mean generic. Give each independently useful capability or observable change its own concise bullet.
- For an initial, major, or consolidation release, use one labeled `**New**:` bullet per public subsystem (for example `- **Notifications**: ...`). Never blend distinct public subsystems into one umbrella sentence.
- Keep actionable public type and feature names. State breaking changes, removals, migration mappings, supported alternatives, platform/pipeline baselines, required dependencies, and sample impacts explicitly.
- Combine private implementation details that support one outcome. Omit test names/counts, audit terminology, contributor files, CI cleanup, XML-comment mechanics, private helpers, and internal refactors.
- Mention automated coverage at most once, generically, and only when it materially improves confidence. Mention documentation only when it changes what consumers can successfully adopt.

After completing the editorial inventory, use the bounded preparation command. It updates only `package.json` and the pending CHANGELOG region, preserves published bytes and file conventions, and promotes a single `Unreleased` body when the target entry does not yet exist:

```bash
release.py prepare <package> <version> <YYYY-MM-DD>
release.py prepare <package> <version> <YYYY-MM-DD> --body-file <BODY.md>
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

Commit and push each package independently, staging only `CHANGELOG.md` and `package.json`. Before syncing notes, prove local `HEAD == origin/develop`; the script additionally proves that the open PR head is the same commit. Leave unrelated host dirt untouched. A generic request to commit and push does not authorize opening a PR; `open-pr` is the sole release-PR path.

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
release.py pack <package>               # tier 1 -> 2 -> 3, then gates G20-G28
release.py pack <package> --ref <sha>   # pack a specific commit (post-merge repack)
```

`pack` refuses a dirty or untracked working tree and an unpushed `HEAD`, with no
override: the tarball is built from the **working tree**, not from a git ref, so
anything uncommitted ships to consumers unreproducibly. Caught in the wild — 7
untracked WIP files under `uiservice Samples~/UrpRendering/` were packed into a
tarball that had already passed verification.

Use `--ref` when `develop` has moved on after a merge: it packs from a detached
worktree at that commit, so the artifact reproduces exactly what was merged and
`G32b` holds. The real working tree is untouched, so `G25` still applies. G25
prints exact before-only/after-only porcelain lines; isolated `--ref` packing
tolerates attributable concurrent changes under other package paths only.

Before preflight, run the documentation verifier's polarity fixture and its `--base origin/master` package check. The base-aware check requires `.meta` siblings for Unity-visible sample assets added anywhere in the release diff. These checks prevent a clean pack from faithfully packaging incomplete documentation or sample assets.

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

The package's `release-preflight` workflow also observes the merged event and
dispatches a `status` run to the host repository. This hand-off requires a
fine-grained `FRAMEWORKS_DISPATCH_TOKEN` package secret with access to
`CoderGamester/Frameworks`; when the secret is absent the workflow emits a
warning and leaves the already-merged PR green. The host run remains read-only
at this stage. Tagging and publishing still require the explicit phases below.

### Step 3 — Tag the merge commit (post-merge only)

Normally resume all post-merge work with:

```bash
release.py complete <package> [--tier N] [--allow-removals]
```

It derives the current phase on every iteration, recreates a missing tarball from
the merge commit's develop-side parent, tags, publishes, and performs the guarded
host bump. The individual commands below remain available for diagnosis and
deliberately bounded recovery.

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

Requires synchronized host `develop`, an empty index, and a clean architecture log. It verifies each release and package source, stages exactly `Packages/<pkg>` plus `.architecture-log.md`, proves the committed path set, writes **one** entry, makes **one** commit (`chore: bump submodule pointers (...)`), pushes host `develop`, and verifies the remote tip. The host pointer records the packaged develop-side source commit; the release tag remains on the two-parent `master` merge commit.

## The PR gate

Each package repo carries `.github/workflows/release-preflight.yml`, installed and
kept in sync by:

```bash
release.py install-preflight [<package>...]   # idempotent; --no-push to stage only
```

It runs on every `pull_request` into `master`, checks out the package with
`lfs: true` plus the shared tooling from `Frameworks`, and runs:

```bash
release.py preflight-pr --path . --base origin/master --event "$GITHUB_EVENT_PATH"
```

That is the package-local subset — `G7`, `G8`/`G9`, `G10`, `G11`, `G15`, `G17`, `G28` —
so it needs no token, no submodules and no network, and works on a bare clone.
Remote-state gates (`G0`-`G6`, `G12`-`G14`) and the tarball chain (`G20`-`G28`)
stay local.

**It exists because a human review gate is impossible here.** GitHub returns
`HTTP 422 "Review cannot be requested from pull request author"`, so a solo repo
cannot have a reviewer on its own PR. A required status check is the substitute;
the PR is assigned to `CoderGamester` purely as a tracking marker.

**Not every `develop → master` PR is a release.** When the version matches the
base, `preflight-pr` treats it as a non-release PR: it skips `G11`/`G15` and
instead asserts `CHANGELOG.md` is untouched, since a published section must not
be edited after the fact.

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

### Re-attesting a published release

```bash
release.py reattest <package> <tag>          # dry run: repack + diff, no mutation
release.py reattest <package> <tag> --yes    # replace the published asset
```

Rebuilds a published tarball so it is attested to the right org. Packs from the
tag's develop-side parent — the commit the original was packed from — so
`repository.revision` and the file list are preserved; only the org, tar mtimes
and tar owner change.

**This is a re-publication, not a repair.** Tarballs are not byte-reproducible,
so anyone who pinned the old `sha256` sees a new digest. Always dry-run first,
show the user the diff, and get per-release approval before `--yes`.

`reattest` **refuses when the repack would lose a file** versus the published
asset. That guard has already prevented two bad replacements:

- `services 2.0.1` ships `VersionServicesSyncLoadTest.cs.meta` that was **never
  committed** — the original was packed from a tree with an uncommitted file.
  Dropping a `.meta` makes Unity reassign the asset's GUID on import. No clean
  fix exists; leave it.
- `statechart 0.9.4` had a **case-only mismatch in git** (`GameLovers.StateChart…
  .meta` against the lowercase `Statechart` asmdef). The published tarball had
  the correctly-paired lowercase names because the original packing machine held
  them lowercase on disk — macOS never renames on a case-only change. Fixing
  `develop` does **not** fix this, because the repack reads the *tag's* commit;
  it required applying the same case correction inside the historical worktree.

Backfill outcome: 8 leaking releases → 1 (`services 2.0.1`).

## Common Pitfalls

- **Stale `origin` URLs.** `services` → `Unity-Services` and `uiservice` → `Unity-UiService` were renamed; `.gitmodules` still has the old names. `G1` halts both. This is not cosmetic — Unity bakes `origin`'s URL into the artifact's `package.json`, and published `uiservice 1.2.1` already carries the wrong one. Fix the remote and `.gitmodules`, don't bypass the gate.
- **Bare `gh` for a write** → the release gets authored by the wrong account. Always go through the scripts.
- **Treating a restricted-network `gh auth status` failure as an expired token.** Retry the identity probe with network permission before asking the user to authenticate again. Never print the token while diagnosing it.
- **`gh release create` without `--verify-tag`** → if the tag push silently failed, `gh` invents a tag at the branch head and you publish a release pointing at the wrong commit.
- **A stale `.tgz` in the pack dir** → this is exactly how `Unity-Services 2.0.2` shipped `com.gamelovers.services-2.0.1.tgz`. `G20` refuses on any sibling tarball; `pack` empties the dir first.
- **Reusing a tarball across versions.** `G22` reads the version from *inside* the tarball. Never hand-upload an asset.
- **`--notes "$(...)"`** mangles backticks and `$` in changelog text. The scripts use `--notes-file`.
- **CLIs that report failure while exiting 0.** `gh pr edit --add-reviewer <author>` silently no-ops (HTTP 422 underneath). `upm pack` prints `Invalid service account credentials provided.` with `rc=0` in the editor-bundled build but `rc=1` in the standalone one, with the real diagnosis on stdout either way. Guard by verifying the *artifact*, never the exit code — and make any comparison prove its inputs were non-empty, since a probe that produced no tarball at all will happily report "0 matches" for whatever you were looking for.
- **Historical CHANGELOG dialect drift is not a problem** — leave it byte-identical. Pending entries use the canonical bold-label dialect. `changelog.py` preserves BOM, CRLF/LF, history, and EOF conventions; hand-rolled whole-file rewrites do not.
- **A clean host PR list is not package evidence.** Release PRs live in six separate submodule repositories. `status` resolves the canonical repo from each package remote.
- **Pushing notes is not enough.** Require local `HEAD`, `origin/develop`, and the PR head SHA to agree, then re-read the body; a successful CLI exit alone does not prove the right PR was updated.
- **`.attestation.p7m` in a file-list diff** is a packer artifact, not package content. `G24` excludes it; `G26` checks it separately.
- **Unity `.meta` pollution.** The packer project lives in `~/Library/Caches`, outside any repo, precisely so a pack can't create `.meta` files in the host tree. `G25` asserts both working trees are unchanged after packing.
- **`.github/` IS packed into the tarball.** The published `googlesheetimporter 0.7.2` asset still contains `package/.github/workflows/openai.yml`. Each package therefore lists `.github/` in its `.gitignore`, which the packer uses as its pack-ignore list; git keeps tracking the file, so `git add` needs `-f`. **Do not verify this on a copy with `.git` removed** — the packer behaves differently without a repo and will wrongly report `.github` as excluded. An earlier claim in this file was wrong for exactly that reason.
- **Unresolved git-lfs pointers.** A checkout without `git lfs pull` leaves ~130-byte stubs that the packer copies verbatim, so a consumer gets a 129-byte "audio file". `G28` refuses them in both the tarball and the PR checkout; the CI workflow uses `lfs: true` so the check also proves the objects are fetchable from the remote. `uiservice` shipped this way once — published 1.2.1 had real content, so it was a silent regression, not a long-standing gap.
- **Case-only filename drift is invisible on macOS.** `statechart` tracked two `.meta` files with a capital `C` while their assets were lowercase; the case-insensitive filesystem hid it entirely, and it only surfaced during a repack. Renaming requires two steps (`git mv X tmp && git mv tmp x`) — a direct case-only `git mv` is a silent no-op. Check with a case-insensitive duplicate scan over `git ls-files`, not by looking at the working tree.

## Done When

- `release.py status <package>` reports `P7_DONE`.
- The tag is annotated, bare SemVer, on a 2-parent merge commit, tagger `CoderGamester <game.gamester@gmail.com>`.
- The release is titled `Release X.Y.Z`, is not a draft, and has exactly one asset `<id>-<version>.tgz` whose `sha256` digest matches the local tarball.
- The host `develop` carries the submodule pointer bump and one `.architecture-log.md` entry, and is pushed.
- The pending changelog passes `validate-pending`, and any open PR body exactly matches that entry.
- The tier used was reported to the user, and any `G23`/`G27` degradation warnings were surfaced rather than swallowed.
- The published asset contains no git-lfs stubs (`G28`) and no `.github/` directory.

## Reference

- Scripts: `scripts/release.py`, `scripts/changelog.py`, `scripts/UpmPack.cs`
- Workflows: `workflows/release-preflight.yml` (per package, installed by `install-preflight`), `../../../.github/workflows/upm-release.yml` (host, dispatch-driven)
- CHANGELOG dialect: root `AGENTS.md` §6.5 — canonical is `**New**:` / `**Changed**:` / `**Fixed**:` / `**Docs**:`
- Pre-publication versioning: root `AGENTS.md` §2.7 — do not open a new `## [X.Y.Z]` section until actually cutting a release
- Submodule workflow: root `AGENTS.md` §5
