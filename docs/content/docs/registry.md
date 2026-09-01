---
title: Regenerating the registry
weight: 9
---

# Regenerating the registry

The registry is a **compiled artifact of [`sdss/tree`](https://github.com/sdss/tree)**.
It is not hand-written, and it is not a runtime dependency — the shipped package
contains only `src/sloppy_sdss_access/data/registry.json`.

```bash
sloppy-sdss-access-build-registry
```

> [!INFO]
> The console script is `sloppy-sdss-access-build-registry` (the **distribution** name),
> even though the module you import is `sloppy_sdss_access`. Running
> `python tools/build_registry.py` from a checkout is equivalent.

## What the build does

The important trick is one line of insight: every `$ENVVAR` in a tree path template
is itself defined inside the same config file, as `%(...)s` interpolations rooted at
`FILESYSTEM`. So the builder:

1. reads each release's `.cfg` with interpolation **disabled**, preserving key case
   (environment variables are case-sensitive);
2. follows the `base =` chain and merges parents underneath children — **per
   variable**, not per section, which is how `BOSS_GALAXY_REDUX`
   [survives]({{< relref "/docs/releases#the-bosseboss-section-deletion" >}});
3. resolves every interpolation against a `FILESYSTEM` sentinel, so each template
   becomes a path relative to the SAS root;
4. classifies each product — `required` / `optional` keys, `derivations`,
   `any_of` groups, `compression` / `may_be_compressed`, `external`, `broken`;
5. writes one JSON blob with a `"source"` provenance block.

Variables that legitimately point *outside* the SAS (`$PRODUCT_ROOT`,
`$PLATELIST_DIR`, `$MANGACORE_DIR`, `$SPECLOG_DIR`, …) are listed in
`SOFTWARE_PRODUCT_VARS` and mark their products `external`. Variables that are simply
undefined in the release chain mark their products `broken`.

## Flags

| flag | effect |
|---|---|
| *(none)* | rebuild from the vendored `tools/*.cfg` |
| `--fetch` | download the latest cfgs from `sdss/tree` first |
| `--ref REF` | git ref to fetch — tag, branch, or SHA. Default `main` |
| `--check` | do not write; **exit 1** if the committed registry is stale |
| `--output PATH` | write somewhere other than `src/sloppy_sdss_access/data/registry.json` |

```bash
sloppy-sdss-access-build-registry                      # rebuild from vendored cfgs
sloppy-sdss-access-build-registry --fetch              # pull latest cfgs first
sloppy-sdss-access-build-registry --fetch --ref 6.1.0  # ...pinned to a tag/branch/SHA
sloppy-sdss-access-build-registry --check              # CI: exit 1 if stale
```

### `--fetch` follows inheritance

`--fetch` downloads `data/*.cfg` over the raw GitHub endpoint — **no auth, no `gh`
CLI required** — and follows `base =` chains. Asking for DR17 also pulls DR16…DR8,
which is **18 configs** in total for the current release list.

Files land in `tools/` when running from a checkout, or in
`$XDG_CACHE_HOME/sloppy-sdss-access-tree-cfg` when running from an installed package
(which has no `tools/`).

### Provenance

The ref and each file's SHA256 are recorded under `"source"` in the registry, so any
given `registry.json` says exactly which tree revision produced it:

```json
"source": {"ref": "main", "configs": {"dr19": "<sha256>", "dr18": "...", ...}}
```

### `--check` ignores provenance

`--check` compares the **payload only** — it pops `"source"` before diffing, because
provenance changes on every fetch and would otherwise report a spurious staleness.

```
  registry is up to date
```

or

```
  registry is STALE -- run: sloppy-sdss-access-build-registry --fetch
```

## Build report

A successful build prints per-release counts and every product whose template
references an undefined variable:

```
  sdsswork    463 products  (15 external, 3 broken)
  ipl1        103 products  (0 external, 0 broken)
  ipl2        107 products  (0 external, 0 broken)
  ipl3        215 products  (14 external, 13 broken)
  ipl4        228 products  (15 external, 12 broken)
  dr18         96 products  (9 external, 0 broken)
  dr19        334 products  (14 external, 4 broken)
  dr20        412 products  (15 external, 5 broken)
  dr13        316 products  (34 external, 0 broken)
  dr14        318 products  (34 external, 0 broken)
  dr15        327 products  (34 external, 0 broken)
  dr16        373 products  (34 external, 2 broken)
  dr17        420 products  (34 external, 2 broken)

  Products referencing env vars undefined in their own release chain:
    sdsswork   apogee-rc                -> $APOGEE_RC
    sdsswork   cannonStar               -> $APOGEE_CANNON
    sdsswork   cannonStar-1m            -> $APOGEE_CANNON
    ipl3       allPlates                -> $APOGEE_ASPCAP
    ipl3       apogee-rc                -> $APOGEE_RC
    ...
    dr20       gcam_lco                 -> $GCAM_DATA_S
    dr16       cannonStar               -> $APOGEE_CANNON
    dr17       cannonStar-1m            -> $APOGEE_CANNON

  3712 product definitions
  -> src/sloppy_sdss_access/data/registry.json  (1653 KB)
```

This report is how the `broken` list in
[Migrating]({{< relref "/docs/migrating#bugs-this-surfaced" >}}) is generated.

## The GitHub Action

`.github/workflows/update-registry.yml` automates the whole thing.

### Job 1 — `update`

Runs **weekly** (Mondays 06:00 UTC) and on demand via `workflow_dispatch`, which
takes a `ref` input so you can build from a specific tree tag. The file-level `on:`
also carries `pull_request` / `push` triggers used by Job 2, so this job is guarded
to run only on the schedule and manual dispatch:

```yaml
on:
  pull_request:            # used by Job 2 (check-consistency)
  push:
    branches: [main]       # ditto
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:
    inputs:
      ref:
        description: "git ref of sdss/tree to build from (tag, branch, or SHA)"
        default: "main"

jobs:
  update:
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
```

Steps:

1. rebuild the registry with `--fetch --ref <ref>`, teeing to `build.log`;
2. run `pytest -q` against the new registry;
3. run the differential check against the real `sdss_access` — installed
   `continue-on-error`, so a broken upstream release cannot wedge the update;
4. re-run `--check`, so nothing lands unless the rebuilt registry agrees with the
   cfgs that were just fetched;
5. **commit straight to `main`** if the compiled output changed — the build
   report's per-release counts go in the commit body, the full log is linked to
   the run.

> [!WARNING]
> **This used to open a PR, and it never worked.** The reasoning was sound — one
> `tree` edit can move thousands of paths, which deserves a human diff — but
> GitHub refuses the API call unless the repository opts in under
> *Settings → Actions → General → "Allow GitHub Actions to create and approve pull
> requests"*. Every scheduled run therefore pushed a `registry-update` branch and
> then died on `create-pull-request`, so no update ever landed:
>
> ```
> ##[error]GitHub Actions is not permitted to create or approve pull requests.
> ```
>
> Committing directly is what the job can actually do without that setting. The
> gate is now that nothing is pushed unless `--check` passes *and* the test suite
> passes against the new registry; the diff is read afterwards, with
> `git log -p -- src/sloppy_sdss_access/data/registry.json`. Turn the setting on
> if you would rather have the PR back.

### Job 2 — `check-consistency`

Runs `sloppy-sdss-access-build-registry --check` and **fails CI on any PR whose
committed registry does not match its vendored cfgs**. So an edited `.cfg` cannot be
merged without a rebuild.

## Running the differential check

The parity harness is the real guarantee that a tree change did not silently alter
path semantics. It needs the legacy stack, which cannot share an interpreter with
this package:

```bash
pip install sdss-access     # for the differential parity check
python tools/parity_check.py
```

```
  TOTAL: legacy unresolved=275  match=16820  skipped=293

  Derivation coverage: 18/24 exercised
    every derivation ran and produced >=2 distinct outputs

  RESULT: PASS
```

See [Migrating → how the equivalence was checked]({{< relref "/docs/migrating#how-the-equivalence-was-checked" >}}).

> [!INFO]
> **This workflow _is_ the CI.** There is [no other CI]({{< relref "/docs/limitations" >}})
> for the project beyond this file, so it is worth knowing exactly what it does:
>
> * The weekly `update` job commits `src/sloppy_sdss_access/data/registry.json` and
>   the vendored cfgs to `main` itself, rebasing if `main` moved while it built.
> * `check-consistency` has no `if:` guard, so the file-level `pull_request` / `push`
>   triggers run it on **every PR and every push to `main`** — an edited `.cfg` cannot
>   be merged without a matching rebuild. It does *not* run on the `update` job's own
>   push, because commits made with `GITHUB_TOKEN` do not trigger workflows; that is
>   why `update` runs the same `--check` inline before pushing.

## Longer term

> [!WARNING]
> **The registry being a build artifact of `tree` is itself a limitation.** Long term
> the templates should live somewhere versioned in their own right rather than being
> scraped out of a config format designed for a different purpose.
>
> Relatedly, the `DERIVATION_KEYS` table lives in the **builder**, not next to the
> functions in `derive.py`, so the two can drift. A test catches unused derivations but
> not wrong key sets.


## Running it from an installed package

This command compiles `sdss/tree` `.cfg` files, and those ship only in a source
checkout — an installed wheel contains just the compiled `registry.json`.

> [!WARNING]
> Without `--fetch`, the command refuses to run when the configs are absent, and
> exits non-zero rather than writing anything. That guard matters: in 0.1.0 a bare
> invocation inside an installed environment rebuilt an **empty** registry over the
> shipped one, leaving the package resolving zero products. Fixed in 0.1.1.

| invocation | from a checkout | from an installed package |
|---|---|---|
| *(no args)* | rebuilds from `tools/*.cfg` | refuses, exit **1** |
| `--fetch` | downloads, then rebuilds | downloads, then rebuilds |
| `--check` | compares, exit 0/1 | cannot compare, exit **2** |

`--fetch` caches the configs under `$XDG_CACHE_HOME/sloppy-sdss-access-tree-cfg`,
so a later `--check` in the same environment works normally.
