# Docker Compose

## What it is

Docker Compose describes and runs a group of containers from one file, `docker-compose.yml` (format: `tech/yaml.md`). Instead of typing a long `docker run` command per container, you declare **services** (each becomes a container), their images, ports, environment variables and start order, and then run `docker compose up`. It ships with Docker Desktop as the command `docker compose`.

## Why this repository uses it

The lesson needs a real PostgreSQL and, optionally, the hardened app image next to it. One file defines both, in the same way on a laptop and in CI, and deleting everything afterwards is one command (`docker compose down -v`).

## Where it appears

| Path | What it does |
| --- | --- |
| `docker-compose.yml` | Two services: `postgres` (always) and `app` (only with the `app` profile). 40 lines. |
| `Makefile` | `up` (`docker compose up -d --wait postgres`), `docker-run`, `down`, plus `docker compose exec` for `psql`. |
| `.github/workflows/ci.yml` | `make up` and `make down` in the `database` job. |
| `.env` / `.env.example` | The values Compose substitutes (not readable here; see the README for the variable names). |

## How it works underneath

1. Compose reads `docker-compose.yml` and a `.env` file in the same folder. Variables in `.env` fill `${NAME}` placeholders in the YAML.
2. It creates a private virtual network for the project (the `name:` key names it). Services reach each other by service name: the app connects to host `postgres`.
3. For each service it pulls or builds the image, creates a container and starts it, in dependency order.
4. `--wait` blocks until services with a health check report healthy.
5. `down` stops and removes the containers and the network; `-v` also deletes their volumes (the database files live in the volume that the `postgres` image declares for its data directory; this file defines no volume of its own).

## Walkthrough of this repository's use

```yaml
name: security-threat-model-and-harden
```
The project name; prefixes container and network names.

### The `postgres` service

```yaml
postgres:
  image: postgres:18
  ports:
    - "127.0.0.1:${POSTGRES_PORT:-5471}:5432"
```
Use the official PostgreSQL 18 image. Publish container port 5432 on host port 5471 (the default, overridable via `POSTGRES_PORT`; `${VAR:-default}` means "use VAR, or the default"). The leading `127.0.0.1:` binds the published port to the loopback address only, so other machines on your network cannot reach the database.

```yaml
  environment:
    POSTGRES_USER: ${POSTGRES_USER:-notes_owner}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?copy .env.example to .env first}
    POSTGRES_DB: ${POSTGRES_DB:-notes}
```
The image reads these on its first start to create the owner role and database. `${VAR:?message}` makes Compose stop with that message if the variable is empty: no password is written in the file, and a forgotten `.env` fails loudly.

```yaml
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
    interval: 3s
    timeout: 5s
    retries: 20
```
`pg_isready` asks the server whether it accepts connections. `CMD-SHELL` runs it through a shell, and `$$` hides the variable from Compose so the shell inside the container expands it. `-h 127.0.0.1` forces a TCP check: during first start the image runs a temporary server that listens only on a socket, and a socket-based check would report "ready" too early (a race fixed while building this repository). Check every 3 seconds; after 20 failures the service is unhealthy.

### The `app` service

```yaml
app:
  profiles: ["app"]
  build: .
  image: security-threat-model-and-harden:dev
  depends_on:
    postgres:
      condition: service_healthy
```
`profiles` means it starts only when you ask (`--profile app`), so `make up` starts just the database. `build: .` builds the Dockerfile in this folder and tags it. `depends_on ... service_healthy` waits for PostgreSQL's health check before starting the app.

```yaml
  env_file: .env
  environment:
    APP_HOST: 0.0.0.0
    NOTES_DB_HOST: postgres
    NOTES_DB_PORT: 5432
```
`env_file` loads every variable of `.env` into the container. `environment` then overrides three: listen on all interfaces *inside* the container (otherwise the published port would not reach it), and reach the database by service name on its internal port 5432 (not the host's 5471).

```yaml
  ports:
    - "127.0.0.1:${APP_PORT:-8047}:${APP_PORT:-8047}"
  read_only: true
  tmpfs:
    - /tmp
  cap_drop:
    - ALL
  security_opt:
    - no-new-privileges:true
```
Publish the app on the loopback only. Read-only root file system with a RAM-backed `/tmp` for anything that must be written. Drop every Linux capability. Forbid privilege gain. See `tech/docker.md`.

### The commands the Makefile uses

- `docker compose up -d --wait postgres`: start only `postgres`, detached, wait for healthy.
- `docker compose exec -T postgres psql ...`: run `psql` inside the running container (`-T` = no terminal, so file redirects work).
- `docker compose --profile app up -d --wait --build app`: build and start the app, wait for its image health check.
- `docker compose --profile app down -v`: remove containers, network and the database volume.

## Try it yourself

1. Check the file without starting anything:
   ```bash
   docker compose --profile app config --quiet && echo valid
   ```
   Expect `valid` (this needs the Docker CLI but not a running engine, and a `.env`; run `make env` to create one).
2. See the fully resolved configuration:
   ```bash
   docker compose --profile app config | head -40
   ```
   Expect `app` and `postgres` with the placeholders replaced by values from `.env`. (It prints local passwords: do not paste it anywhere.)
3. Start the database and look at its state:
   ```bash
   make up && docker compose ps
   ```
   Expect `postgres` `running (healthy)`.
4. Prove the loopback-only binding:
   ```bash
   docker compose ps --format '{{.Ports}}'
   ```
   Expect `127.0.0.1:5471->5432/tcp`.
5. Clean up: `make down`.

## Mistakes people make

- Publishing a database port on all interfaces (`"5432:5432"`). Here it is loopback only.
- Writing passwords in the compose file. Here they come from `.env`, which is git-ignored.
- Using `depends_on` without a health condition: "started" is not "ready".
- Using the host port (5471) from another container. Inside the network it is `postgres:5432`.
- Leaving volumes behind and wondering why an old schema is still there. `make down` uses `-v`, and `make up` only runs the schema on an empty database.

## Check yourself

1. What does a profile do?
   *The service starts only when that profile is requested.*
2. Why `127.0.0.1:` in front of the port mapping?
   *The port is reachable only from the same machine.*
3. What does `${POSTGRES_PASSWORD:?msg}` do?
   *Stops with the message if the variable is empty.*
4. How does the app find the database?
   *By service name `postgres` on the Compose network, port 5432.*
5. What does `down -v` remove besides containers?
   *The containers' volumes, so the database files are deleted.*

## Further reading

- Compose file reference: https://docs.docker.com/reference/compose-file/
- Interpolation (`:-`, `:?`): https://docs.docker.com/reference/compose-file/interpolation/
- Profiles: https://docs.docker.com/compose/how-tos/profiles/
- `docker compose` CLI: https://docs.docker.com/reference/cli/docker/compose/
