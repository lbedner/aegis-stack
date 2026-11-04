# Overseer

Overseer is your app's control room, built in. Every Aegis Stack app ships with
it already wired, and there is nothing to set up. It shows what the app is (the
[Twin](twin.md), drawn as a map), what it is doing (health, logs, errors,
resources, requests), and what can be done to it (settings, secrets, deploys).
Your coding agents and Illiana read the same data it shows you.

It lives at `/overseer` with the htmx web frontend
([`aegis add htmx`](../components/web-frontend/index.md)); without it, the Flet
dashboard at `/dashboard` shows each part's health.

![Overseer Dashboard](../images/overseer-demo.gif)

## In every stack

These pages are there whatever components and services the stack has. Each
component and service adds a page of its own beside them (the worker's queues,
the database's tables, the AI service's spend).

| Page | What it shows |
|------|---------------|
| [Overview and the Map](map.md) | Every part's health as cards, a map or the flow of work; zoom into the Server or a service; traffic heat; where the code breaks its rules; replay one request hop by hop |
| [Health](health.md) | What each part reports, how a status rolls up, and adding your own |
| [Server](server.md) | Performance, traffic, cache, connections, load tests, routes (send a request from the page) and the app's lifecycle |
| [Logs and Errors](logs-and-errors.md) | Every container's logs, credited to the service that wrote them, and errors grouped by cause with their stack traces |
| [Code](code.md) | The app's source, read-only: every stack trace frame links to its line |
| [Resources](resources.md) | CPU, memory, network and disk I/O for the host, this stack and each part, over time |
| [Patterns](patterns.md) | How this app is built: its routes, tasks and shared UI pieces, for a person or an agent to read before building |
| [Secrets and Settings](secrets-and-settings.md) | Every credential and setting the app declares, and where each is set |
| [Deployments](../deployment/overseer.md) | Where the app runs, and a new server, deploy, back up and roll back from the page |

Under every page:

- **Live, never polled.** A page that changes is pushed over SSE while it is
  open, and only what changed is sent
  ([Live updates](../components/web-frontend/live-updates.md)).
- **One read for every reader.** Overseer, Illiana, MCP clients and the API
  read the same typed models, so a part, a request or a line of code is named
  the same everywhere.
- **Every page has its address.** Filters, windows and an open file or error
  are in the URL, so a link lands where it was sent.

## Who can open it

Without the auth service, Overseer is open to read, like any route a stack
serves without auth, and changes (a restart, a secret, a saved setting) are
made only on the local dev build opened at `localhost`. With auth, every page,
stream and action is for admins only: an account in `ADMIN_USER_EMAILS`, or
with the `admin` role under `auth[rbac]`. A deployed server's Overseer and
admin paths also admit only the networks in `ADMIN_IP_ALLOWLIST`. Details:
[Who can open the Overseer](../components/web-frontend/index.md#who-can-open-the-overseer).

## More

- **[The Twin](twin.md)**: the model of the app every page reads
- **[Why Overseer](why.md)**: the shrug, and how Overseer came to be
- **[Adding a health check](health.md#adding-your-own)**: report your own components and services
