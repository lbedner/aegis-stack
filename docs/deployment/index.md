# Deployment

Deploy your Aegis Stack project to a server you own, over SSH: no PaaS, and the
server, the bill and the data stay yours. One command, or one button in
Overseer, rents a server in your Hetzner or DigitalOcean account, names it,
turns on HTTPS and deploys. Or point it at any VPS you already have.

Every deploy backs up first, checks the app's health after, and rolls back on
its own if the check fails. A nightly encrypted copy can leave the server for
S3-compatible storage, and a restore drill proves it comes back.

## Prerequisites

- **SSH key authentication** configured for your server (Overseer's deploys
  sign with your machine's ssh-agent)
- **rsync** installed locally (included on macOS and most Linux distributions)
- **A server** (Ubuntu, Debian, or Fedora) with SSH access, **or** a Hetzner
  Cloud or DigitalOcean account to make one in
- **A domain** (optional: without one the app gets an `sslip.io` name)

## Quick start

**No server yet?** Make one in your own account:

```bash
export HCLOUD_TOKEN=...      # Hetzner Cloud API token, read & write
aegis deploy-provision --email you@example.com

# or on DigitalOcean
export DIGITALOCEAN_TOKEN=...
aegis deploy-provision --provider digitalocean --email you@example.com
```

It shows the monthly price first, creates the server, points a name at it
(`<ip>.sslip.io`, or yours with `--domain`), turns on HTTPS with Let's Encrypt,
and runs `aegis deploy`. `aegis deploy-destroy` removes the server and its DNS
record. Tokens and their scopes: [Cloud accounts and keys](cloud.md).

**Have a server?** Three commands:

```bash
aegis deploy-init --host 192.168.1.100   # write .aegis/deploy.yml
aegis deploy-setup                       # install Docker, configure the firewall
aegis deploy                             # back up, sync, build, start, health check
```

Your application is now running at `http://your-server-ip`, or at the name
`aegis deploy-provision` gave it. Overseer (`/overseer`, or `/dashboard/` with
the Flet frontend) admits only private networks until you add your address to
`ADMIN_IP_ALLOWLIST` (see [Ingress](../components/ingress.md)) and redeploy.

## Where to go next

| Page | What it covers |
|------|----------------|
| [From Overseer](overseer.md) | Overseer > Deployments: a new server at its price, deploy, back up, roll back, destroy, from the page |
| [Cloud accounts and keys](cloud.md) | The provider and DNS tokens, the scopes each needs, where to set them |
| [Backups and restore](backups.md) | The backup on every deploy, off-site copies, rehearsing a restore |
| [From the CLI](cli.md) | `.aegis/deploy.yml`, the everyday commands, monitoring |
| [From CI](ci.md) | GitHub Actions deploys with a dedicated key, and shipping the production env |
| [HTTPS and domains](https.md) | Let's Encrypt through Traefik, your own domain, DNS |
| [How it works and security](security.md) | What a deploy does, step by step, and what can touch production |

Every option of every command: [CLI Reference](../cli-reference.md#deployment-commands).
