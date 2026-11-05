# From the CLI

Every deploy action is an `aegis deploy-*` command, run in the project
directory. Overseer and CI run the same commands.

## First deployment

```bash
# 1. Create a project with ingress
aegis init my-app --components ingress
cd my-app

# 2. Run it locally
make serve

# 3. Set up deployment
aegis deploy-init --host your-server-ip
aegis deploy-setup

# 4. Deploy
aegis deploy
```

Or replace step 3 with `aegis deploy-provision` to make the server
([Cloud accounts and keys](cloud.md)).

**`aegis deploy-setup`** runs once on a fresh server. It verifies SSH (adding
the host key if needed) and runs the project's `scripts/server-setup.sh` there,
which installs Docker, the Compose plugin, `uv` and build tools, opens ports
22, 80 and 443 in the firewall, sets up Docker log rotation, creates the
application directory, applies system tuning (file limits, TCP BBR), and under
4 GB of RAM adds a swapfile unless the box has swap. `--public-key` also
installs a key in the deploy user's `authorized_keys`, so you can skip
`ssh-copy-id`. The script comes with the ingress component: `aegis add ingress`
if it is missing.

## Redeploying

```bash
aegis deploy              # back up, sync, build, start, health check
aegis deploy --no-build   # config-only change: reuse the built images
aegis deploy --rolling    # no downtime
```

What each step does: [How it works](security.md#what-a-deploy-does).

## Monitoring

```bash
aegis deploy-status               # docker compose ps on the server
aegis deploy-logs                 # follow every service's logs
aegis deploy-logs -s webserver    # one service, with --no-follow to stop
aegis deploy-shell                # a shell in the webserver (-s redis, -s traefik)
aegis deploy-restart              # docker compose restart
aegis deploy-stop                 # docker compose down
```

## Configuration

`aegis deploy-init` writes `.aegis/deploy.yml`:

```yaml
server:
  host: 192.168.1.100
  user: root
  path: /opt/my-project

docker:
  context: my-project-remote
```

| Field | Description |
|-------|-------------|
| `server.host` | Server IP address or hostname |
| `server.user` | SSH user (default: `root`) |
| `server.path` | Application directory on the server (default: `/opt/{project-name}`) |
| `docker.context` | Docker context name (used by the generated Makefile's `deploy-*` targets) |

The `backup` and `health_check` settings are on
[Backups and restore](backups.md#settings). Every field is optional beyond
`server.host`; a missing one takes its default.

!!! tip "Git-ignore deploy config"
    Add `.aegis/` to your `.gitignore` to keep deployment config out of version control. `deploy-init` will remind you if it's missing.

## Every command

| Command | Does |
|---------|------|
| [`deploy-init`](../cli-reference.md#aegis-deploy-init) | Write `.aegis/deploy.yml` |
| [`deploy-setup`](../cli-reference.md#aegis-deploy-setup) | Prepare a fresh server |
| [`deploy-provision`](../cli-reference.md#aegis-deploy-provision) | Make a server in your cloud account, and deploy |
| [`deploy-destroy`](../cli-reference.md#aegis-deploy-destroy) | Remove the server it made |
| [`deploy`](../cli-reference.md#aegis-deploy) | Deploy or redeploy |
| [`deploy-backup`](../cli-reference.md#aegis-deploy-backup) | Back up the server now |
| [`deploy-backups`](../cli-reference.md#aegis-deploy-backups) | List the server's backups |
| [`deploy-rollback`](../cli-reference.md#aegis-deploy-rollback) | Restore a backup |
| [`deploy-restore-drill`](../cli-reference.md#aegis-deploy-restore-drill) | Rehearse a restore of the off-site copy |
| [`deploy-upload-db`](../cli-reference.md#aegis-deploy-upload-db), [`deploy-upload-storage`](../cli-reference.md#aegis-deploy-upload-storage) | Send this machine's database, or the stored files the server lacks |
| [`deploy-cd-setup`](../cli-reference.md#aegis-deploy-cd-setup) | Wire GitHub Actions deploys |
| [`deploy-cd-env`](../cli-reference.md#aegis-deploy-cd-env) | Push the production env for them |
| [`deploy-agent`](../cli-reference.md#aegis-deploy-agent) | Run what Overseer asks for |
| [`deploy-status`](../cli-reference.md#aegis-deploy-status), [`deploy-logs`](../cli-reference.md#aegis-deploy-logs), [`deploy-shell`](../cli-reference.md#aegis-deploy-shell), [`deploy-exec`](../cli-reference.md#aegis-deploy-exec) | Look at the server |
| [`deploy-restart`](../cli-reference.md#aegis-deploy-restart), [`deploy-stop`](../cli-reference.md#aegis-deploy-stop) | Restart or stop its services |
| [`ingress-enable`](../cli-reference.md#aegis-ingress-enable) | Turn on HTTPS |
