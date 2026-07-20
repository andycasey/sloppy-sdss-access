---
title: Authentication
weight: 7
---

# Authentication

**Public data releases need no credentials at all.** Path resolution never needs
them under any circumstances.

```python
from sloppy_sdss_access import SDSS, Access
a = Access(SDSS("dr19"))
a.is_public, a.credentials
```

```
(True, None)
```

`credentials` returns `None` for public releases and short-circuits before any
lookup. Nothing is read from your environment, and no netrc file is opened.

This is [#95](https://github.com/sdss/sdss_access/issues/95).

## Public vs collaboration

| release | access | host |
|---|---|---|
| `dr13`–`dr19` | **public** | `data.sdss.org` |
| `dr20` | collaboration *(until 2026-07-30)* | `data.sdss5.org` |
| `ipl1`–`ipl4` | collaboration — **never public** | `data.sdss5.org` |
| `sdsswork` | collaboration — **never public** | `data.sdss5.org` |

```python
Access(SDSS("sdsswork")).host, Access(SDSS("sdsswork")).is_public
```

```
('data.sdss5.org', False)
```

Collaboration data sits behind HTTP Basic auth. Verified against the live SAS:

```bash
$ python -c "
import urllib.request, urllib.error
u='https://data.sdss5.org/sas/sdsswork/mwm/spectro/astra/0.6.0/summary/astraAllStarASPCAP-0.6.0.fits.gz'
try: urllib.request.urlopen(urllib.request.Request(u, method='HEAD'))
except urllib.error.HTTPError as e: print(e.code, e.headers.get('WWW-Authenticate'))"
```

```
401 Basic realm="SDSS-V Science Archive Server (SAS)"
```

## The DR20 date nuance

> [!WARNING]
> **A DR is only public once its release date has actually passed.** Publicness is
> computed, not hardcoded.
>
> `dr20` is dated **2026-07-30**, so today it still needs collaboration credentials —
> and it will become public on its own, with no code change, once that date passes.

```python
from sdss_access.auth import is_public
import datetime

is_public("dr19", "2025-07-10")                            # True
is_public("dr20", "2026-07-30")                            # False  (today: 2026-07-20)
is_public("dr20", "2026-07-30", datetime.date(2026, 8, 1)) # True
is_public("sdsswork", None)                                # False
is_public("ipl3", "2023-11-01")                            # False
```

The rule, from `auth.is_public`:

1. the release name must start with `dr` — so `sdsswork` and the IPLs are **never**
   public regardless of date;
2. it must have a release date; and
3. that date must be **on or before** today.

This also drives `url()`, which picks `data.sdss.org` for public releases and
`data.sdss5.org` otherwise — matching what `sdss_access` does, so the compat shim's
`url()` agrees with the legacy one.

## The four-source chain

Credentials resolve from the **first** source that supplies them:

| # | source | intended for |
|---|---|---|
| 1 | passed explicitly — `Access(..., username=..., password=...)` | scripts, notebooks, tests |
| 2 | `$SDSS_USER` / `$SDSS_PASSWORD` | CI, containers |
| 3 | `~/.netrc` keyed by host | the existing `sdss_access` setup |
| 4 | an interactive prompt | **opt-in only** |

```python
Access(SDSS("sdsswork"), username="...", password="...")   # 1. explicit
Access(SDSS("sdsswork"))                                   # 2/3. env, then netrc
Access(SDSS("sdsswork"), allow_prompt=True)                # 4. ask on a terminal
```

Resolution happens **once** and is cached on the `Access` instance.

### Verified end to end

With a real `~/.netrc` entry for `data.sdss5.org`:

```python
a = Access(SDSS("sdsswork"))
print(a.credentials)
with a.open("astraAllStarASPCAP", v_astra="0.6.0") as fp:
    head = fp.read(64)
print(head[:2] == b"\x1f\x8b")
```

```
Credentials(username='sdss5', password=<hidden>)
True
```

Key resolution → path → compression probe → auth → range read, against the live
collaboration-only SAS.

### Prompting is opt-in

> [!INFO]
> **Nothing prompts implicitly.** Unlike `sdss_access.sync.auth`, an interactive
> prompt requires `allow_prompt=True`, and is skipped anyway when `stdin` is not a
> terminal.
>
> A library that blocks on `input()` in the middle of a batch job is a bug.

### When nothing is found

```python
Access(SDSS("sdsswork")).credentials
```

```
AuthError: No SDSS credentials for 'data.sdss5.org'. Provide them by any of:
  - Access(..., username=..., password=...)
  - export SDSS_USER=... SDSS_PASSWORD=...
  - a ~/.netrc entry:
        machine data.sdss5.org
        login <user>
        password <password>
    (then chmod 600 ~/.netrc)
  - Access(..., allow_prompt=True) to be asked interactively
```

The error spells out all four options rather than making you go and read the source.

## netrc format

```
machine data.sdss5.org
login <user>
password <password>
```

```bash
chmod 600 ~/.netrc
```

On Windows, `_netrc` is also checked. The file is located at
`~/.netrc`, then `~/_netrc`, unless you override it:

```python
Access(SDSS("sdsswork"), netrc_path="/secrets/netrc")
```

> [!WARNING]
> **A world-readable netrc warns.** If the file is group- or other-readable you get:
>
> ```
> UserWarning: /Users/you/.netrc is readable by other users; run `chmod 600 /Users/you/.netrc`
> ```
>
> A malformed netrc warns and returns `None` rather than raising, so a broken file
> degrades to "no credentials from this source" rather than killing the process.

## Passwords stay out of output

```python
from sloppy_sdss_access import Credentials
c = Credentials("me", "secret")
repr(c)
str(c)
c.as_header()
```

```
"Credentials(username='me')"
"Credentials(username='me', password=<hidden>)"
'Basic bWU6c2VjcmV0'
```

`Credentials` is a frozen dataclass with `field(repr=False)` on the password, so it
cannot leak into logs, tracebacks, or notebook output. `as_header()` naturally still
contains it — that is its job.

Credentials are sent as an explicit `Authorization` header folded into the fsspec
`storage_options`, rather than `aiohttp.BasicAuth`, which is deprecated in aiohttp 4.

> [!INFO]
> Auth is folded in **only for `http`/`https`**. `protocol="file"` skips credential
> resolution entirely, and `protocol="s3"` has [no credential path]({{< relref "/docs/limitations" >}}).

## Migrating from legacy auth

| legacy | here |
|---|---|
| `Auth(netloc, public=..)` / `set_auth(inquire=True)` | `sdss_access.auth.resolve(host, ...)` |
| implicit prompt on missing credentials | `allow_prompt=True`, and only on a TTY |
| `HttpAccess().set_auth(user, pass)` | supported on the shim; sets `Access.username`/`.password` |
| `public=True` on `Path` | accepted and **ignored** — publicness is computed from the release date |
