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

- **Read-only.** The first cut answers `GET` for the container list, stats, logs, `/info` and `/system/df`. Every other path and every other method is refused, including the reads that would leak data: container inspect (`/containers/{id}/json` returns a container's whole environment, secrets included, for any container on the host), `/containers/{id}/export` and `/containers/{id}/archive`.
- **No network.** The proxy runs with `network_mode: none` and listens on a Unix socket in the `docker-proxy` volume, which the app containers mount. Nothing on the compose network can reach it.
- **No privileges.** A read-only root filesystem, every Linux capability dropped, `no-new-privileges`. It runs as uid 0 only so it can open the host's socket on any host without knowing the host's `docker` group id.
- **Same in prod.** The service carries both the `dev` and `prod` profiles; `aegis deploy` starts it with the rest of the stack.

The proxy is [wollomatic/socket-proxy](https://github.com/wollomatic/socket-proxy), a small Go binary on a scratch image. Its allowlist is a regular expression per HTTP method, in `docker-compose.yml`:

```yaml
command:
  - "-proxysocketendpoint=/var/run/docker-proxy/docker.sock"
  - '-allowGET=(/v1\.[0-9]+)?/(containers/json|containers/[a-zA-Z0-9_.-]+/(stats|logs)|info|system/df)'
```

Write actions (restarting a container) will come as explicit additions to this allowlist, admin-only, confirmed and audited; nothing is writable today.

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

Every Overseer page with a container behind it (Server, Worker, Scheduler, Redis, Database on Postgres, Storage, Ingress, Inference) has a **Container** section, in Overseer's htmx pages and Flet modals alike. It shows one row per instance: state and health, CPU, memory used against its limit, network in and out, disk I/O, restarts, uptime, and the image with its build. It renders from the containers sampler's last reading (`app.core.series`), so it opens full, then refreshes every second while it is open, with CPU and memory charts over the last 15 minutes, 30 minutes or hour.

Without the deploy component the backend is `none`: the section says so and points at `aegis add deploy` instead of showing the app's own process as if it were a container. A page with nothing running behind it (a SQLite database, which is a file) says that too, and a runtime that does not answer says why.

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
