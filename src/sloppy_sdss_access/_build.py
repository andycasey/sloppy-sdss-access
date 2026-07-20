"""Compile SDSS-5 ``tree`` config files into a single static registry.

This is an *offline build step*, not a runtime dependency. It reads the legacy
``tree`` ``.cfg`` files and emits ``src/sloppy_sdss_access/data/registry.json``.

The important trick is here: every ``$ENVVAR`` in a tree path template is itself
defined *inside the same config file* (as ``%(...)s`` interpolations rooted at
``FILESYSTEM``). So we can resolve them all at build time and store each template
as a plain path relative to the SAS root. The runtime then needs **zero**
environment variables, and nothing ever touches ``os.environ``.

Usage::

    sloppy-sdss-access-build-registry                    # rebuild from the vendored cfgs
    sloppy-sdss-access-build-registry --fetch            # pull the latest cfgs from sdss/tree first
    sloppy-sdss-access-build-registry --fetch --ref 6.1.0  # ...pinned to a tag/branch/SHA
    sloppy-sdss-access-build-registry --check            # CI: fail if the registry is stale

``--fetch`` downloads ``data/*.cfg`` from github.com/sdss/tree over the raw
endpoint (no auth, no gh CLI needed) into ``tools/``, which is where the
vendored copies live. The provenance of a build -- the ref and the per-file
SHA256 -- is recorded in the registry under ``"source"`` so you can tell which
tree revision a given registry.json came from.
"""

from __future__ import annotations

import json
import os
import re
import string
from configparser import ConfigParser, DEFAULTSECT
from pathlib import Path

# Sentinel standing in for the SAS root while we resolve interpolations.
FILESYSTEM_SENTINEL = "\x00SAS\x00"

_PKG = Path(__file__).parent
_REPO = _PKG.parent.parent          # <repo>/src/sloppy_sdss_access -> <repo>
_VENDORED = _REPO / "tools"         # where the .cfg files are kept in-repo

# Config directory: the in-repo tools/ when running from a checkout, otherwise
# a cache dir (an installed package has no tools/, and uses --fetch anyway).
HERE = _VENDORED if _VENDORED.is_dir() else (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "sloppy-sdss-access-tree-cfg"
)
HERE.mkdir(parents=True, exist_ok=True)

OUT = _PKG / "data" / "registry.json"

# Where the upstream configs come from.
TREE_REPO = "sdss/tree"
TREE_RAW = "https://raw.githubusercontent.com/{repo}/{ref}/data/{name}.cfg"

# The SDSS-5 releases. Everything else (DR7-DR17) is legacy SDSS-1..4 and is
# deliberately out of scope -- that is the whole point of the split.
RELEASES = ["sdsswork", "ipl1", "ipl2", "ipl3", "ipl4", "dr18", "dr19", "dr20",
            "dr13", "dr14", "dr15", "dr16", "dr17"]  # EXPERIMENT: SDSS-4

# Environment variables that legitimately point *outside* the SAS data tree --
# svn/github software product checkouts, set by module files. Products using
# these are marked ``external`` and are opt-in at runtime.
SOFTWARE_PRODUCT_VARS = {
    "PLATELIST_DIR",
    "SPECLOG_DIR",
    "SPECFLAT_DIR",
    "SDSSCORE_DIR",
    "PLATEDESIGN_DIR",
    # SDSS-4 svn/git product checkouts, all rooted at $PRODUCT_ROOT, which
    # tree.py injects at runtime from the user's environment.
    "PRODUCT_ROOT",
    "BOSSTILELIST_DIR",
    "MANGACORE_DIR",
    "MANGAPREIM_DIR",
    "MANGA_SANDBOX",
    "IDLSPEC2D_DIR",
    "PHOTOOP_DIR",
    "RUN1D_DIR",
    "RUN2D_DIR",
}

# Env vars that a derivation needs at runtime (spectrodir picks between them).
DERIVATION_ENV = ("SPECTRO_REDUX", "BOSS_SPECTRO_REDUX")

# Compression handling. A template either already names a compression suffix, or
# it names an extension that the SAS *might* store compressed, or it names one
# that never is. Only the middle case is worth a probe at runtime -- see
# Access.resolve_uri.
COMPRESSION_SUFFIXES = (".gz", ".bz2", ".fz", ".zip", ".Z")

# Extensions that are never gzipped on the SAS: already-compressed containers,
# images, and web/markup formats.
NEVER_COMPRESSED = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".ps", ".eps",
    ".html", ".htm", ".xml", ".json", ".yaml", ".yml", ".md",
    ".apz",       # APOGEE's own compressed raw format
    ".h5", ".pkl", ".parquet",
}

ENVVAR_RE = re.compile(r"\$(\w+)")
INTERP_RE = re.compile(r"%\((\w+)\)s")
SPECIAL_RE = re.compile(r"@(\w+)\|")

# Which keys each derivation consumes, and whether they are required.
# In sdss_access this was recovered by AST-parsing the function source at
# runtime; declaring it is both faster and far easier to reason about.
#
# A key is optional ONLY where absence has a defined, meaningful result --
# not merely where the Python function happens to tolerate `None`.
#
# This distinction matters. `pad_fieldid` returns "" when `fieldid` is missing,
# but its output is interpolated into the *filename*, so treating `fieldid` as
# optional yields a silently malformed "spec--59797-...fits". Anything whose
# output lands in a path segment is therefore required; only genuine flags
# (a blank component, a merged-observatory coadd, a format that defaults to
# FITS) are optional.
DERIVATION_KEYS = {
    "healpixgrp": {"healpix": True},
    "cat_id_groups": {"cat_id": True},
    "sdss_id_groups": {"sdss_id": True},
    "configgrp": {"configid": True},
    "configsubmodule": {"configid": True},
    "tilegrp": {"tileid": True},
    "platedir": {"plateid": True},
    "plateid6": {"plateid": True},
    "plategrp": {"plate": True},
    "definitiondir": {"designid": True},
    "spectrodir": {"run2d": True},
    "isplate": {"run2d": True},
    "pad_fieldid": {"fieldid": True, "run2d": True},
    "fieldgrp": {"fieldid": True, "run2d": True},
    "sptypefolder": {"run2d": True},
    "epochflag": {"run2d": True},
    "spcoaddfolder": {"run2d": True, "coadd": True},
    "spcoaddgrp": {"run2d": True, "coadd": True},
    # Genuinely optional: a blank component means "no discernible companion".
    "component_default": {"component": False},
    # Genuinely optional: a blank obs means the merged (multi-observatory) coadd.
    "spcoaddobs": {"obs": False, "run2d": True},
    # Genuinely optional: ftype defaults to FITS; num is required for FITS.
    "mos_target_num": {"num": True, "ftype": False},
    "mos_target_num2": {"num": True, "ftype": False},
    "mos_target_num3": {"num": True, "ftype": False},
    # apgprefix accepts EITHER telescope OR instrument; see DERIVATION_ANY_OF.
    "apgprefix": {},
}

# Derivations satisfied by any one of a set of keys, rather than all of them.
DERIVATION_ANY_OF = {
    "apgprefix": ("telescope", "instrument"),
}


def fetch_configs(releases: list[str], ref: str = "main") -> dict[str, str]:
    """Download each release's cfg (and everything it inherits) from sdss/tree.

    Follows ``base =`` chains, so asking for dr17 also pulls dr16..dr8. Returns
    ``{name: sha256}`` for provenance.
    """
    import hashlib
    import urllib.error
    import urllib.request

    shas: dict[str, str] = {}
    queue = list(releases)
    seen: set[str] = set()

    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)

        url = TREE_RAW.format(repo=TREE_REPO, ref=ref, name=name)
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"cannot fetch {name}.cfg from {TREE_REPO}@{ref}: {exc}")

        (HERE / f"{name}.cfg").write_bytes(body)
        shas[name] = hashlib.sha256(body).hexdigest()

        # Queue whatever this config inherits from.
        for line in body.decode("utf-8", "replace").splitlines():
            if line.strip().startswith("base"):
                _, _, parent = line.partition("=")
                if parent.strip():
                    queue.append(parent.strip())
                break

    print(f"  fetched {len(shas)} configs from {TREE_REPO}@{ref}")
    return shas


def read_raw(name: str) -> ConfigParser:
    """Read a cfg with interpolation disabled so we can merge before resolving."""
    cp = ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # preserve case: env vars are case-sensitive
    cp.read(HERE / f"{name}.cfg")
    return cp


def chain(name: str) -> list[str]:
    """Resolve the ``base = ...`` inheritance chain, root first."""
    order: list[str] = []
    seen: set[str] = set()
    cur: str | None = name
    while cur and cur not in seen:
        seen.add(cur)
        order.append(cur)
        cp = read_raw(cur)
        cur = cp.defaults().get("base") or None
    return list(reversed(order))


def merge(name: str) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Merge every cfg in the inheritance chain. Child values win."""
    sections: dict[str, dict[str, str]] = {}
    defaults: dict[str, str] = {}
    for link in chain(name):
        cp = read_raw(link)
        defaults.update(cp.defaults())
        for section in cp.sections():
            merged = sections.setdefault(section, {})
            # cp.items() folds in DEFAULTSECT; use the raw section mapping only.
            for key, value in cp._sections[section].items():  # noqa: SLF001
                merged[key] = value
    # The leaf release's own name/identity must win over any inherited one.
    leaf = read_raw(name)
    defaults.update(leaf.defaults())
    return sections, defaults


def interpolate(value: str, local: dict[str, str], defaults: dict[str, str]) -> str:
    """Resolve ``%(X)s`` against section-local values, then DEFAULT."""
    for _ in range(10):  # bounded fixpoint; nesting is only a few levels deep
        match = INTERP_RE.search(value)
        if not match:
            break
        def sub(m: re.Match[str]) -> str:
            key = m.group(1)
            if key == "FILESYSTEM":
                return FILESYSTEM_SENTINEL
            return local.get(key, defaults.get(key, m.group(0)))
        new = INTERP_RE.sub(sub, value)
        if new == value:
            break
        value = new
    return value


# Sections that redefine variables owned by an earlier survey. The later entry
# wins on conflict. tree.py handles the BOSS/EBOSS case by deleting the whole
# [BOSS] section, which also discards BOSS-only variables such as
# BOSS_GALAXY_REDUX -- so sdss_access cannot resolve BOSS galaxy paths for DR13+
# at all, and returns a literal "$BOSS_GALAXY_REDUX". Overriding per-variable
# instead keeps those definitions while still pointing them at the EBOSS root.
SECTION_PRECEDENCE = ("BOSS", "EBOSS")


def env_map(name: str) -> dict[str, str]:
    """Every environment variable the release defines, fully resolved.

    Resolution is two-pass. First every section is flattened into one namespace,
    with SECTION_PRECEDENCE deciding conflicts; only then are ``%(...)s``
    references expanded. Doing it in that order matters: BOSS_GALAXY_REDUX is
    defined in [BOSS] as ``%(BOSS_SPECTRO_REDUX)s/galaxy``, and interpolating it
    section-locally would pick up [BOSS]'s own BOSS_SPECTRO_REDUX (rooted at
    $BOSS_ROOT) rather than the [EBOSS] one that actually wins (rooted at
    $EBOSS_ROOT). Verified against the archive: dr17/eboss/spectro/redux exists,
    dr17/boss/spectro/redux does not.
    """
    sections, defaults = merge(name)

    def rank(section: str) -> int:
        return SECTION_PRECEDENCE.index(section) if section in SECTION_PRECEDENCE else -1

    # Pass 1: flatten, honouring precedence.
    raw: dict[str, str] = {}
    owner: dict[str, str] = {}
    for section, items in sections.items():
        if section in ("PATHS", DEFAULTSECT):
            continue
        for key, value in items.items():
            if key in owner and rank(section) < rank(owner[key]):
                continue
            raw[key] = value
            owner[key] = section

    # Pass 2: expand against the flattened namespace, with the defining
    # section's locals available for non-env placeholders such as %(name)s.
    env: dict[str, str] = {}
    # Identity keys (name, phase, release_date, ...) live in DEFAULT and are
    # scoped per section/release -- they must NOT be flattened. dr19 inherits
    # from dr18, so letting an inherited section's `name` win rewrote every
    # dr19 path as dr18.
    flat_env = {k: v for k, v in raw.items() if k not in defaults}
    for key, value in raw.items():
        local = dict(sections.get(owner[key], {}))
        local.update(flat_env)  # winning env definitions outrank section-local
        env[key] = interpolate(value, local, defaults)
    return env


def template_keys(template: str) -> tuple[list[str], dict[str, str]]:
    """Extract ``{key}`` names and any ``:format`` specs from a template."""
    keys: list[str] = []
    formats: dict[str, str] = {}
    for literal, field, spec, _conv in string.Formatter().parse(template):
        del literal
        if field is None:
            continue
        keys.append(field)
        if spec:
            formats[field] = spec
    return keys, formats


def compression_of(template: str) -> tuple[str | None, bool]:
    """Classify a template's compression.

    Returns ``(suffix_in_template, may_be_compressed)``. ``may_be_compressed``
    is True only when the template names an extension the SAS might store
    gzipped -- those are the only products worth probing at runtime.
    """
    for suffix in COMPRESSION_SUFFIXES:
        if template.endswith(suffix):
            return suffix, False

    ext = os.path.splitext(template)[1].lower()
    # A templated extension (e.g. "{ftype}") is unknown until keys are bound;
    # don't guess, and don't pay for a probe.
    if not ext or "{" in ext or ext in NEVER_COMPRESSED:
        return None, False
    return None, True


def build_release(name: str) -> dict:
    sections, defaults = merge(name)
    env = env_map(name)
    paths = sections.get("PATHS", {})

    products: dict[str, dict] = {}
    unresolved: set[str] = set()

    for species, raw in paths.items():
        template = raw.strip()
        if not template:
            continue

        # 1. Resolve $ENVVAR -> concrete path.
        def sub_env(m: re.Match[str]) -> str:
            var = m.group(1)
            if var in env:
                return env[var]
            unresolved.add(var)
            return m.group(0)

        resolved = ENVVAR_RE.sub(sub_env, template)

        # 2. Strip the SAS-root sentinel so the template is root-relative.
        rooted = resolved.startswith(FILESYSTEM_SENTINEL)
        relative = resolved[len(FILESYSTEM_SENTINEL) :].lstrip("/") if rooted else resolved

        # 3. Pull apart the keys and the derivations.
        keys, formats = template_keys(relative)
        derivations = SPECIAL_RE.findall(relative)

        required = {k: True for k in keys}
        any_of: list[list[str]] = []
        for fn in derivations:
            for key, is_required in DERIVATION_KEYS.get(fn, {}).items():
                # A key already supplied literally in the template stays required.
                required.setdefault(key, is_required)
            group = DERIVATION_ANY_OF.get(fn)
            if group:
                # Satisfied by any one of the group; if the template already
                # supplies one literally, the constraint is already met.
                if not any(k in keys for k in group):
                    any_of.append(sorted(group))
                for key in group:
                    required.setdefault(key, False)

        # Any $VAR still standing is either an external software product, or a
        # genuine hole in the tree config for this release.
        leftover = set(ENVVAR_RE.findall(relative))
        external = sorted(leftover & SOFTWARE_PRODUCT_VARS)
        broken = sorted(leftover - SOFTWARE_PRODUCT_VARS)

        compression, may_be_compressed = compression_of(relative)

        entry = {
            "template": relative,
            "compression": compression,
            "may_be_compressed": may_be_compressed,
            "keys": sorted(required),
            "required": sorted(k for k, v in required.items() if v),
            "optional": sorted(k for k, v in required.items() if not v),
            "formats": formats,
            "derivations": sorted(set(derivations)),
            "any_of": any_of,
            "rooted": rooted,
        }
        if external:
            entry["external"] = external
        if broken:
            # Undefined in this release's inheritance chain. sdss_access leaves
            # these unexpanded and silently returns a path containing a literal
            # "$VAR"; we refuse to resolve them instead.
            entry["broken"] = broken

        products[species] = entry

    derivation_env = {
        var: env[var][len(FILESYSTEM_SENTINEL):].lstrip("/")
        for var in DERIVATION_ENV
        if var in env and env[var].startswith(FILESYSTEM_SENTINEL)
    }

    return {
        "release": name,
        "derivation_env": derivation_env,
        "phase": int(defaults.get("phase", 5)),
        "release_date": (defaults.get("release_date") or "").strip() or None,
        "current": defaults.get("current", "False").strip().lower() == "true",
        "inherits": chain(name)[:-1],
        "products": products,
        "_unresolved_envvars": sorted(unresolved),
    }


def build(shas: dict[str, str] | None = None, ref: str | None = None) -> dict:
    """Compile every release into one registry dict."""
    registry = {
        "schema": 1,
        "generated_from": TREE_REPO,
        "source": {"ref": ref, "configs": shas or {}},
        "releases": {name: build_release(name) for name in RELEASES},
    }
    return registry


def report(registry: dict) -> None:
    total = 0
    all_broken: dict[str, list[str]] = {}
    for name, rel in registry["releases"].items():
        products = rel["products"]
        total += len(products)
        ext = sum(1 for p in products.values() if "external" in p)
        broken = sorted(k for k, p in products.items() if "broken" in p)
        if broken:
            all_broken[name] = broken
        print(
            f"  {name:10s} {len(products):4d} products"
            f"  ({ext} external, {len(broken)} broken)"
        )

    if all_broken:
        print("\n  Products referencing env vars undefined in their own release chain:")
        for name, species in all_broken.items():
            for sp in species:
                var = ", ".join(registry["releases"][name]["products"][sp]["broken"])
                print(f"    {name:10s} {sp:24s} -> ${var}")

    print(f"\n  {total} product definitions")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="sloppy-sdss-access-build-registry",
        description="Compile sdss/tree configs into src/sloppy_sdss_access/data/registry.json",
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="download the latest cfgs from sdss/tree before building",
    )
    parser.add_argument(
        "--ref", default="main",
        help="git ref of sdss/tree to fetch (tag, branch, or SHA). Default: main",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="do not write; exit 1 if the committed registry differs (for CI)",
    )
    parser.add_argument(
        "--output", type=Path, default=OUT, help="where to write registry.json",
    )
    args = parser.parse_args()

    shas = fetch_configs(RELEASES, ref=args.ref) if args.fetch else None
    registry = build(shas=shas, ref=args.ref if args.fetch else None)
    serialised = json.dumps(registry, indent=1, sort_keys=True)

    if args.check:
        if not args.output.exists():
            print(f"  {args.output} does not exist")
            raise SystemExit(1)
        current = args.output.read_text()
        # Provenance changes on every fetch; compare the payload only.
        def payload(text: str) -> str:
            data = json.loads(text)
            data.pop("source", None)
            return json.dumps(data, indent=1, sort_keys=True)

        if payload(current) == payload(serialised):
            print("  registry is up to date")
            raise SystemExit(0)
        print("  registry is STALE -- run: sloppy-sdss-access-build-registry --fetch")
        raise SystemExit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialised)
    report(registry)
    print(f"  -> {args.output}  ({args.output.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
