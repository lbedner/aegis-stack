# Deploy

Where the app runs, as a component. The deployment target is its axis: `compose` (Docker Compose on a host, what `aegis deploy` does) is the default and the only value today.

```bash
aegis add deploy             # the compose target (the default)
aegis add deploy[compose]    # the same, spelled out
aegis init my-app --components deploy
```

The base compose files are not part of it: every project ships them, because local development needs them regardless. The deploy component owns what depends on the target rather than on the app's features: how the Overseer reads the containers that are running.

## The socket proxy

Reading containers, their stats and their logs means talking to the Docker Engine, and the Docker socket is root on the host. So the webserver never mounts it. A `socket-proxy` service does, and it is the only container that does:

```
 webserver / worker / scheduler            socket-proxy                 Docker Engine
 +---------------------------+   unix    +------------------+   unix   +---------------+
 | /var/run/docker-proxy/    | --------> | GET allowlist    | -------> | /var/run/     |
 |   docker.sock             |  socket   | everything else  |  socket  |   docker.sock |
 +---------------------------+  (volume) |   refused (403)  |   (ro)   +---------------+
                                         +------------------+
```

- **Reads, and one write.** It answers `GET` for the container list, stats, logs, `/info` and `/system/df`. Every other path and every other method is refused, including the reads that would leak data: container inspect (`/containers/{id}/json` returns a container's whole environment, secrets included, for any container on the host), `/containers/{id}/export` and `/containers/{id}/archive`. The one write is `POST /containers/{name}/restart` (see Restart below).
- **No network.** The proxy runs with `network_mode: none` and listens on a Unix socket in the `docker-proxy` volume, which the app containers mount. Nothing on the compose network can reach it.
- **No privileges.** A read-only root filesystem, every Linux capability dropped, `no-new-privileges`. It runs as uid 0 only so it can open the host's socket on any host without knowing the host's `docker` group id.
- **Same in prod.** The service carries both the `dev` and `prod` profiles; `aegis deploy` starts it with the rest of the stack.

The proxy is [wollomatic/socket-proxy](https://github.com/wollomatic/socket-proxy), a small Go binary on a scratch image. Its allowlist is a regular expression per HTTP method, in `docker-compose.yml`:

```yaml
command:
  - "-proxysocketendpoint=/var/run/docker-proxy/docker.sock"
  - '-allowGET=(/v1\.[0-9]+)?/(containers/json|containers/[a-zA-Z0-9_.-]+/(stats|logs)|info|system/df)'
  - '-allowPOST=(/v1\.[0-9]+)?/containers/[a-zA-Z0-9_.-]+/restart'
```

A new write action is an explicit addition here, confirmed and audited, like Restart.

## Reading it from the app: `app.core.runtime`

Every project has `app.core.runtime`, one async interface for what is running and how it is doing, the same pattern as `app.core.storage` and `app.core.secrets`. The backend follows the target:

| Backend | When | Reads |
|---|---|---|
| `none` | No deploy component | The app's own process and machine (psutil); no container logs |
| `docker` | `deploy[compose]` | This compose project's containers, through the socket proxy |

```python
from app.core import runtime

for service in await runtime.services():        # webserver, worker-system, redis...
    print(service.name, service.page)           # the Overseer page it belongs on
    for instance in service.instances:          # state, health, uptime, image, build
        stats = await runtime.stats(instance.id)    # CPU %, memory used / limit, network, disk I/O
        lines = await runtime.logs(instance.id, tail=100)

async for line in runtime.follow(instance_id):  # new lines as they are written
    ...

usage = await runtime.disk()    # bytes per container and per volume
host = await runtime.host()     # CPUs, memory, Docker version, disk
```

- **Scoped to the project.** Containers and volumes are filtered by the `com.docker.compose.project` label, read from the app container's own labels (or `COMPOSE_PROJECT_NAME`), so other projects on the same host never show up.
- **Log lines** carry a timestamp and the stream (`stdout` / `stderr`). JSON lines (the production log format) are parsed into `level` and `event`; console lines have their colour codes stripped.
- **Service to page.** `webserver` maps to Server, `worker-*` to Worker, `scheduler`, `redis`, `postgres` to Database, `seaweedfs` to Storage, `traefik` to Ingress, `ollama` to Inference.
- **Failures are explicit.** A missing socket, a stopped proxy or a refused path raises `RuntimeUnavailableError`; nothing is guessed.

Everything about an instance comes from the container list, never from inspect:

- **Uptime** is read from the list's status (`Up 5 hours (healthy)`), so it is only as precise as Docker's rounded duration, and `started_at` is derived from it. Health comes from the same status.
- **Restarts** are not in the list, so `restarts` is `None` for the Docker backend.
- **Build** is the image's `org.opencontainers.image.revision` label. `aegis deploy` stamps `BUILD_ID` into the server's `.env`, compose passes it to the image build as a build arg, and the Dockerfile labels the image with it (`dev` locally). Without the label it falls back to the short image id.

## In Overseer: the Container section

Every Overseer page with a container behind it (Server, Worker, Scheduler, Redis, Database on Postgres, Storage, Ingress, Inference) has a **Container** section, in Overseer's htmx pages and Flet modals alike. It shows one card per instance: its name, state and health, uptime, restarts and the image with its build, then a fixed strip of CPU, memory used against its limit, network in and out, and disk read and write, so a figure changing width moves nothing else. It renders from the containers sampler's last reading (`app.core.series`), so it opens full, then refreshes every second while it is open, with charts over the last 15 minutes, 30 minutes or hour: CPU, memory, and network and disk I/O as bytes per second (the sampler keeps Docker's running totals; a chart reads the rate between readings, and drops the step where a restart reset them).

The Scheduler and Cache pages also open with a glance above their Overview: a line per container with its state, uptime, CPU, memory as a share of its limit (amber, then red, by the host memory check's rule), its Restart, and the way to its Container and Logs sections.

### Restart

Each card has a **Restart**, in htmx and Flet alike. It asks first, then calls `POST /api/v1/runtime/containers/{name}/restart`: with the auth service only an admin may call it, and without auth anyone who reaches the app may, like the rest of Overseer. Every attempt is audited (`runtime.container_restart`: who, from which address, which container, and whether it restarted, was refused or failed). The app refuses any container its own services do not list, since the proxy would restart any container on the host; without a deploy target there is nothing to restart. Restarting the webserver Overseer itself runs on answers first and restarts after: the confirm says the page will drop, the audit records `restarting`, and the page reconnects when the server is back.

Without the deploy component the backend is `none`: the section says so and points at `aegis add deploy` instead of showing the app's own process as if it were a container. A page with nothing running behind it (a SQLite database, which is a file) says that too, and a runtime that does not answer says why.

## Deploy history

With a database, the component keeps a `deployment` table (in its own `deploy` schema on Postgres, like the scheduler's and secrets'): one row per build that went live. Two writers fill the same row, keyed by the build id:

- **The app**, when a build it has not seen starts, writes the build id and when it started. This covers every way code reaches the server: `aegis deploy`, a CI deploy, a restart onto a new image. A plain restart of the same build writes nothing.
- **`aegis deploy`**, after each deploy and rollback (and `aegis deploy-rollback`), adds what only the deployer knows: who deployed (your git name and email), from which machine, the health check result, the backup taken before it, and the build a rollback went back to. It runs `deploy record` in the webserver container; a failed write warns and never changes the deploy's result.

```bash
my-app deploy record --build a1b2c3d --by "Ada <ada@example.org>" --health passed
```

What is live is always the running build (`BUILD_ID`), never the newest row. Without a database the component still reads containers and logs, and there is no history.

## In Overseer: the Logs section

The same pages have a **Logs** section after Container, in htmx and Flet alike (`app.services.system.ui_logs`). It reads the last 500 lines of every container behind the page, merged by time and newest first (oldest first on request), then adds new lines as the containers write them while it is open: Docker pushes them, so following polls nothing. A JSON line reads as its level, event and `key=value` fields; a plain line's level is read from a leading or bracketed tag (`INFO:`, `[warn]`). A traceback, plain or in a JSON line's `exception`, folds under the line it belongs to instead of filling the list.

The filters stay in the address: the window (15m, 1h, 6h, 1d, or All from each container's start), a level (that level and worse; a line with no level is left out) and text, matched against the line and its traceback. Without the deploy component it says so, like Container. The Docker backend keeps one connection to the socket proxy for the app's life and closes it on shutdown.

## In Overseer: Logs

**Logs** in the sidebar (and the Logs button in the Flet header) shows every service's lines in one view: the same reading, filters and following as the Logs section, merged across every container, with each line naming its service and linking to its page. A Services filter narrows it to the ones ticked. Following can be paused, in this view and in each page's Logs section; a line written while paused is not added.

## In Overseer: Deployments

**Deployments** in the sidebar (and the Deployments button in the Flet header) shows what is live and where it runs, read-only:

- **Running on**: the provider this server is on, with its location, server id and IP and a link to its console. The server reads it from its cloud's own metadata service (`169.254.169.254`, answered only on the server itself), once per process: Hetzner Cloud, DigitalOcean and AWS today. Nothing answering is **Local** before any deploy and **Self-hosted** after.
- **Deploys to**: where this project deploys to, from `aegis deploy-provision`'s record in `.aegis/deploy.yml`. That file stays on the machine you deploy from (it is never synced to the server), so this shows where you run Overseer locally.
- **Where it can run**: every provider `aegis` knows as a card, with what it can do there (Detect, Deploy, Provision) and the one in use marked. Picking a card shows the command to start with it and the token it reads from your environment.
- **Now**: the live build (`BUILD_ID`, which `aegis deploy` stamps with the short commit, or `dev` before any deploy), its commit and whether it carried uncommitted changes, when the server went live (its container's start), and the last health check.
- **Host**: the server's CPUs, memory, disk used and Docker version, through the socket proxy (this machine when there is no deploy target).
- **History**: each build that went live, newest first, from the deploy history: when it went live, who deployed it and from where, its health check, the backup taken before it, and the build a rollback went back to. **Now** also names who deployed the live build. A build that adds the table runs before it is migrated: the page says the history cannot be read yet instead of failing.
- **Backups**: the scheduled database backups on the backup volume, newest first, with size and age.

## Checking it

With the stack up, from inside the webserver container:

```bash
docker compose exec webserver curl -s --unix-socket /var/run/docker-proxy/docker.sock \
  http://docker/containers/json | head -c 200       # answered
docker compose exec webserver curl -s -o /dev/null -w '%{http_code}\n' \
  --unix-socket /var/run/docker-proxy/docker.sock http://docker/images/json   # 403
```

## Removing it

```bash
aegis remove deploy
```

The `socket-proxy` service and its volume leave the compose files; the base compose files and `aegis deploy` itself stay.
