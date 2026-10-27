# httpx 0.28 (pinned, not imported)

## What it is

httpx is a Python library for **making** HTTP requests, the way `requests` does, with support for both normal and `async` code. Pinned: `httpx==0.28.1` in the development lock file (`requirements-dev.lock`). In `pyproject.toml` it is listed under the `dev` extras as `"httpx>=0.27,<1"`.

## Why this repository uses it

The honest answer: **nothing in this repository imports it.** A search of `src/`, `tests/` and `scripts/` finds no `import httpx`. It was added to the development dependencies in case a test wanted an HTTP client, and the tests ended up using Flask's own test client (`tech/werkzeug.md`) and the standard library (`urllib`, `http.client`) instead. It is therefore an unused development dependency. It does no harm, but it adds packages to the lock file that the dependency audit has to cover.

If you want to remove it, delete the line from `pyproject.toml`, regenerate the lock files with `uv pip compile` (see `tech/uv-and-lock-files.md`), and run `make audit`. That is left as a follow-up; this note describes the repository as it is.

## Where it appears

| Path | What it does with httpx |
| --- | --- |
| `pyproject.toml` | Declares `httpx>=0.27,<1` in `[project.optional-dependencies] dev`. |
| `requirements-dev.lock` | Pins `httpx==0.28.1` with hashes (along with its own dependencies such as `anyio`, `certifi`, `h11`, `httpcore`, `idna`). |

## How it works underneath

1. You create a `Client` (it keeps a pool of connections and a cookie jar).
2. `client.get(url)` opens a TCP connection (and a TLS session for `https`), writes the request as text, reads the response, and returns a `Response` with `.status_code`, `.headers`, `.text`, `.json()`.
3. The `AsyncClient` version does the same inside an `async def` function without blocking.

The repository's real clients are the ones below, so compare:

| Client | Where | Why not httpx |
| --- | --- | --- |
| Flask test client | `tests/support.py` (`Browser`) | No network at all; calls the app directly; has a cookie jar. |
| `http.client` | `src/notes_app/interfaces/demo_cli.py` | The scenario sets a `Secure` cookie by hand over plain `http://127.0.0.1`; a small standard-library client keeps full control and needs no dependency in the runtime image. |
| `urllib.request` | `interfaces/health_cli.py`, `tests/e2e/test_scenario.py` | One GET to `/readyz`; the health check must work in a runtime image that has only the locked runtime dependencies. |

## Walkthrough of this repository's use

There is none to walk through. The relevant code is the health check, which is what an httpx call would replace:

```python
url = f"http://127.0.0.1:{port}/readyz"
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        ok = response.status == 200
except (urllib.error.URLError, OSError) as error:
    print(f"unhealthy: {error}", file=sys.stderr)
    return 1
```
`urlopen` opens the URL and returns a response object usable in a `with` block. `timeout=3` is essential: without it a hung server hangs the health check. The `except` catches network errors and returns exit code 1 (unhealthy). It talks to `127.0.0.1` on purpose: inside the container the server listens there, and the check must not depend on DNS.

## Try it yourself

1. Confirm nothing imports it:
   ```bash
   grep -rn "httpx" src tests scripts
   ```
   Expect no matches (only the generated egg-info files mention it if you search the whole tree).
2. See it is installed in the dev environment:
   ```bash
   .venv/bin/python -c "import httpx; print(httpx.__version__)"
   ```
   Expect `0.28.1`.
3. Try it against the running server (`make up`, `make run`):
   ```bash
   .venv/bin/python -c "import httpx; r = httpx.get('http://127.0.0.1:8047/healthz'); print(r.status_code, r.json())"
   ```
   Expect `200 {'status': 'ok'}`.

## Mistakes people make

- Leaving unused dependencies in a lock file. Each one is code to audit and update. (This is the repository's own example.)
- Forgetting timeouts. httpx has a default timeout of 5 seconds; the standard-library calls here set one explicitly.
- Using a client in production code that is only pinned for development.

## Check yourself

1. Is httpx imported anywhere in this repository?
   *No; it is pinned in the dev extras only.*
2. Which clients does the repository really use?
   *Flask's test client, `urllib.request` and `http.client`.*
3. Why does the health check use `127.0.0.1` and a timeout?
   *To avoid DNS and to avoid hanging on a stuck server.*
4. What would removing httpx involve?
   *Delete the line in `pyproject.toml`, recompile the lock files, run `make audit`.*
5. What is the cost of an unused dependency?
   *More packages to audit and update, and a bigger supply-chain surface.*

## Further reading

- httpx 0.28 documentation: https://www.python-httpx.org/
- Quickstart: https://www.python-httpx.org/quickstart/
