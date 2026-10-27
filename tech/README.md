# Technology notes

These notes teach every technology this repository uses, from zero, through the repository's own files. You do not need to know any of them first. Each note says what the technology is, why it is here, where it appears, how it works underneath, walks through this repository's actual lines, gives commands to try, lists common mistakes and ends with five questions.

Notes describe the code as committed. Commands that need the database say `needs make up`; commands that need Docker say so. Where a command was not re-run when the note was written, the note says that too.

## Ten minutes? Read these three

1. [stride-threat-modeling.md](stride-threat-modeling.md): the method behind the whole lesson.
2. [http-cookies-csrf-and-headers.md](http-cookies-csrf-and-headers.md): the browser-facing controls.
3. [sql.md](sql.md): why values and statements travel separately.

## Reading order

**1. The language and the command line**

| Note | Role here |
| --- | --- |
| [python.md](python.md) | Python 3.12: the language of the app, the tests and the scripts. |
| [bash.md](bash.md) | The demo script and the shell fragments inside the Makefile. |
| [make.md](make.md) | The `Makefile`: one short command per task. |
| [git.md](git.md) | History, and `.gitignore` for files that must never be committed. |
| [editorconfig.md](editorconfig.md) | Editor settings shared by everyone. |

**2. Files and formats**

| Note | Role here |
| --- | --- |
| [toml.md](toml.md) | The format of `pyproject.toml`. |
| [yaml.md](yaml.md) | The format of the compose file and the workflow. |
| [dotenv.md](dotenv.md) | `.env` files and environment variables: where configuration and secrets come from. |
| [pyproject-and-setuptools.md](pyproject-and-setuptools.md) | Turning `src/` into an installable package with two commands. |
| [uv-and-lock-files.md](uv-and-lock-files.md) | venv, pip, uv and the hash-pinned lock files. |

**3. The web application**

| Note | Role here |
| --- | --- |
| [flask.md](flask.md) | The web framework: routes, hooks, error handlers. |
| [werkzeug.md](werkzeug.md) | The library under Flask: proxy handling, errors, the test client. |
| [jinja2-templates.md](jinja2-templates.md) | HTML templates and output encoding. |
| [gunicorn.md](gunicorn.md) | The production server and graceful shutdown. |
| [http-cookies-csrf-and-headers.md](http-cookies-csrf-and-headers.md) | Sessions, cookies, CSRF tokens, security headers. |
| [argon2.md](argon2.md) | Password hashing. |

**4. The data**

| Note | Role here |
| --- | --- |
| [postgresql.md](postgresql.md) | The database server, roles, constraints, the append-only trigger. |
| [sql.md](sql.md) | The `sql/` files and parameterized statements. |
| [psycopg.md](psycopg.md) | The Python driver and connection pool. |

**5. Containers and delivery**

| Note | Role here |
| --- | --- |
| [docker.md](docker.md) | The Dockerfile and a hardened image. |
| [docker-compose.md](docker-compose.md) | PostgreSQL and the app as one stack. |
| [github-actions.md](github-actions.md) | CI that runs the same `make` targets. |

**6. Tests, quality and supply chain**

| Note | Role here |
| --- | --- |
| [pytest.md](pytest.md) | The four test levels and the coverage gate. |
| [stride-threat-modeling.md](stride-threat-modeling.md) | The threat model and the "remove the control" proof. |
| [ruff.md](ruff.md) | Linting (with security rules) and formatting. |
| [mypy.md](mypy.md) | Static type checking. |
| [import-linter.md](import-linter.md) | Architecture rules enforced as a build step. |
| [pip-audit.md](pip-audit.md) | Known-vulnerability check on the locked dependencies. |
| [cyclonedx.md](cyclonedx.md) | The software bill of materials. |
| [httpx.md](httpx.md) | Pinned in the dev extras but never imported: an honest note on an unused dependency. |
