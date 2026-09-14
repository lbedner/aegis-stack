# Deployment

Deploy your Aegis Stack project to a remote server with a single command. The deployment system handles file syncing, Docker builds, and service orchestration over SSH.

## Prerequisites

- **A VPS or server** with SSH access (Ubuntu, Debian, or Fedora)
- **SSH key authentication** configured for your server
- **rsync** installed locally (included on macOS and most Linux distributions)
- **A domain** (optional, required for TLS/HTTPS)

## Quick Start

```bash
# 1. Initialize deployment config
aegis deploy-init --host 192.168.1.100

# 2. Provision the server (installs Docker, configures firewall)
aegis deploy-setup

# 3. Deploy your application
aegis deploy
```

Your application is now running at `http://your-server-ip`.

## Configuration

Deployment settings are stored in `.aegis/deploy.yml`, created by `deploy-init`:

```yaml
# .aegis/deploy.yml
server:
  host: 192.168.1.100
  user: root
  path: /opt/my-project

docker:
  context: my-project-remote

# Optional: backup settings (defaults shown)
backup:
  keep_count: 5           # Number of backups to retain
  include_database: true  # pg_dump before deploy

# Optional: health check after deploy (defaults shown)
health_check:
  retries: 3              # Number of retry attempts
  auto_rollback: true     # Rollback on failed health check
```

| Field | Description |
|-------|-------------|
| `server.host` | Server IP address or hostname |
| `server.user` | SSH user (default: `root`) |
| `server.path` | Application directory on server (default: `/opt/{project-name}`) |
| `docker.context` | Docker context name (used by generated Makefile `deploy-*` targets) |
| `backup.keep_count` | Number of backups to keep on server (default: `5`) |
| `backup.include_database` | Include PostgreSQL dump in backup (default: `true`) |
| `health_check.retries` | Number of health check attempts (default: `3`) |
| `health_check.auto_rollback` | Auto-rollback on failed health check (default: `true`) |

All `backup` and `health_check` fields are optional, missing fields use defaults. Existing `deploy.yml` files work without changes.

!!! tip "Git-ignore deploy config"
    Add `.aegis/` to your `.gitignore` to keep deployment config out of version control. `deploy-init` will remind you if it's missing.

---

## Command Reference

### aegis deploy-init

Initialize deployment configuration for a project.

**Usage:**
```bash
aegis deploy-init [OPTIONS]
```

**Options:**

- `--host, -h TEXT`, Server IP address or hostname (prompted if not provided)
- `--user, -u TEXT`, SSH user for deployment (default: `root`)
- `--path, -p TEXT`, Deployment path on server (default: `/opt/{project-name}`)
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
# Interactive (prompts for host)
aegis deploy-init

# Specify host directly
aegis deploy-init --host 192.168.1.100

# Custom user and path
aegis deploy-init --host myserver.com --user deploy --path /srv/myapp
```

---

### aegis deploy-setup

Provision a remote server for deployment. Run this **once** on a fresh server before your first deploy.

**Usage:**
```bash
aegis deploy-setup [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)
- `--public-key PATH`, Public key to install in the deploy user's `authorized_keys` (idempotent). Lets you skip the manual `ssh-copy-id` step.

**What it does:**

1. Verifies SSH connectivity (adds host key if needed)
2. Copies `scripts/server-setup.sh` to the server
3. Runs the setup script, which:
    - Installs Docker and Docker Compose plugin
    - Installs `uv` (Python package manager)
    - Installs build tools (`build-essential` / `gcc`)
    - Configures firewall (ports 22, 80, 443)
    - Sets up Docker daemon with log rotation
    - Creates application directory with proper permissions
    - Applies system optimizations (file limits, TCP BBR)
4. If `--public-key` was passed, appends that key to the deploy user's `~/.ssh/authorized_keys` (idempotent — re-running with the same key is a no-op).

**Examples:**
```bash
aegis deploy-setup
aegis deploy-setup --public-key ~/.ssh/id_ed25519.pub
```

!!! note "Requires ingress component"
    The `server-setup.sh` script is generated when the ingress component is included. If you see "Server setup script not found", add ingress first: `aegis add ingress`.

---

### aegis deploy-cd-setup

Wire up GitHub Actions continuous deployment in one command. Generates a dedicated SSH deploy key, installs the public key on your server, pushes the private key + host + user as repo secrets, and scaffolds `.github/workflows/deploy.yml`.

**Usage:**
```bash
aegis deploy-cd-setup [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)
- `--repo OWNER/NAME`, GitHub repo (default: auto-detect from `git remote get-url origin`)
- `--on-tag`, Also trigger the deploy workflow on `v*` tag pushes (default: `workflow_dispatch` only)
- `--force`, Overwrite existing secrets and `deploy.yml` (use to rotate the deploy key)
- `--dry-run`, Print the plan without making any changes
- `--keep-key PATH`, Save a copy of the generated private key locally (default: no local copy — the key only lives in GitHub secrets)

**Prerequisites:**

- `aegis deploy-init` has been run (this command reads `.aegis/deploy.yml` for host/user)
- The [GitHub CLI (`gh`)](https://cli.github.com/) is installed and authenticated (`gh auth login`)
- You can already SSH into the deploy server (the command uses your existing access to install the new CI key)

**What it does:**

1. Detects the GitHub repo from `git remote get-url origin` (or honors `--repo`)
2. Generates a fresh ed25519 keypair in a temp dir, no passphrase, comment `github-actions-deploy@OWNER/REPO`
3. Appends the public key to the deploy user's `authorized_keys` on the server (idempotent)
4. Pushes three secrets to the repo: `DEPLOY_SSH_KEY` (private key), `DEPLOY_HOST`, `DEPLOY_USER`
5. Writes `.github/workflows/deploy.yml` (workflow_dispatch by default; `--on-tag` adds the tag trigger)
6. Records the key fingerprint in `.aegis/deploy.yml` under `ci.github` so re-runs detect "already configured"
7. Securely deletes the temp private key (overwrites then unlinks)

**Examples:**
```bash
aegis deploy-cd-setup                # one-shot setup with workflow_dispatch trigger
aegis deploy-cd-setup --on-tag       # also auto-deploy on v* tag pushes
aegis deploy-cd-setup --dry-run      # see the plan without touching anything
aegis deploy-cd-setup --force        # rotate the existing deploy key
```

!!! tip "Why a dedicated deploy key"
    Don't reuse your personal SSH key for CI. A dedicated key has a smaller blast radius (only deploys this one project), can be rotated without touching your other servers, and shows up as a distinct identity in `auth.log`. This command generates one for you.

!!! warning "Backing up the deploy key"
    GitHub Actions secrets are **write-only** — once the private key is uploaded, you can't read it back from the API or UI. By default, `deploy-cd-setup` uploads the key and securely deletes the local copy, so the only place it exists is inside GitHub.

    **If you want a local backup** (for a password manager, disaster recovery, or to use the same key from another CI provider), pass `--keep-key PATH` at setup time:
    ```bash
    aegis deploy-cd-setup --keep-key ~/.ssh/aegis_deploy_ci
    ```

    **If you already ran setup without `--keep-key`** and want a copy now, rotate the key — there's no way to extract the existing one. Re-run with `--force --keep-key PATH`:
    ```bash
    aegis deploy-cd-setup --force --keep-key ~/.ssh/aegis_deploy_ci
    ```
    This generates a fresh key, replaces the public key on the server, overwrites the GitHub secret, and saves a local copy. The previous key is rotated out.

---

### aegis deploy

Deploy (or redeploy) the application to the configured server.

**Usage:**
```bash
aegis deploy [OPTIONS]
```

**Options:**

- `--build / --no-build`, Build Docker images before deploying (default: `--build`)
- `--backup / --no-backup`, Create backup before deploying (default: `--backup`)
- `--health-check / --no-health-check`, Run health check after deploying (default: `--health-check`)
- `--project-path TEXT`, Path to the project (default: current directory)

**What it does:**

1. **Creates a backup** of the current deployment (files + database)
2. **Syncs files** to the server via `rsync --delete`, so a file removed from the project is removed from the server too
3. **Copies `.env`** file separately (excluded from rsync for safety)
4. **Stops existing services** with `docker compose down`
5. **Builds and starts services** with production compose overrides
6. **Restarts Traefik** if the ingress component is present (ensures container re-discovery)
7. **Runs health check** against `/health/` endpoint
8. **Auto-rollback** if health check fails, restores the backup from step 1

**Excluded from sync:**

Files and directories excluded from the rsync transfer. The sync deletes, and
rsync never deletes an excluded path, so this list also protects server-side
state from removal:

- `.git`, Git history
- `__pycache__`, Python cache
- `.venv`, Virtual environment
- `*.pyc`, Compiled Python files
- `.pytest_cache`, Test cache
- `.ruff_cache`, Linter cache
- `data/`, Local database files
- `.env` and `.env.deploy`, Environment files (copied separately)
- `.aegis/`, Deploy configuration
- `backups/`, Server-side backups
- `node_modules/`, Node dependencies
- `traefik/acme/`, Let's Encrypt certificate store (deleting it forces
  re-issuance and can hit rate limits)

**Examples:**
```bash
# Full deploy with build (backup + health check enabled by default)
aegis deploy

# Skip image rebuild (faster, uses cached images)
aegis deploy --no-build

# Deploy without backup or health check (original behavior)
aegis deploy --no-backup --no-health-check
```

---

### aegis deploy-backup

Create a backup of the currently deployed application on the remote server.

**Usage:**
```bash
aegis deploy-backup [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**What it does:**

1. Creates a timestamped backup directory on the server
2. Copies all deployed files into the backup via server-side `rsync`
3. Dumps the PostgreSQL database if a postgres container is running
4. Prunes old backups beyond the retention count (default: 5)

SQLite databases are automatically included in the file backup since they live in the deploy directory.

**Examples:**
```bash
aegis deploy-backup
```

---

### aegis deploy-backups

List available deployment backups on the remote server.

**Usage:**
```bash
aegis deploy-backups [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Example output:**
```
Backups on 143.198.20.208 (3 total):

  Timestamp                Size         Database
  ──────────────────────── ──────────── ──────────
  2026-03-11_183045        42M          yes
  2026-03-10_120000        41M          no
  2026-03-09_090000        40M          yes

Rollback with: aegis deploy-rollback --backup <timestamp>
```

---

### aegis deploy-rollback

Rollback to a previous deployment backup.

**Usage:**
```bash
aegis deploy-rollback [OPTIONS]
```

**Options:**

- `--backup, -b TEXT`, Backup timestamp to rollback to (default: latest)
- `--project-path TEXT`, Path to the project (default: current directory)

**What it does:**

1. Stops all running services
2. Restores files from the backup snapshot
3. Restores the PostgreSQL database if a dump exists in the backup
4. Rebuilds and starts all services
5. Restarts Traefik if present

**Examples:**
```bash
# Rollback to the most recent backup
aegis deploy-rollback

# Rollback to a specific backup
aegis deploy-rollback --backup 2026-03-11_183045
```

---

### aegis deploy-logs

View logs from the deployed application.

**Usage:**
```bash
aegis deploy-logs [OPTIONS]
```

**Options:**

- `--follow / --no-follow, -f`, Follow log output in real-time (default: `--follow`)
- `--service, -s TEXT`, Show logs for a specific service
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
# Follow all service logs
aegis deploy-logs

# View logs without following
aegis deploy-logs --no-follow

# View logs for a specific service
aegis deploy-logs --service webserver
aegis deploy-logs -s traefik
aegis deploy-logs -s redis
```

---

### aegis deploy-status

Check the status of all deployed services.

**Usage:**
```bash
aegis deploy-status [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-status
```

Shows the output of `docker compose ps` on the remote server, including container status, ports, and health.

---

### aegis deploy-stop

Stop all deployed services.

**Usage:**
```bash
aegis deploy-stop [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-stop
```

Runs `docker compose down` on the remote server.

---

### aegis deploy-restart

Restart all deployed services.

**Usage:**
```bash
aegis deploy-restart [OPTIONS]
```

**Options:**

- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
aegis deploy-restart
```

Runs `docker compose restart` on the remote server.

---

### aegis deploy-shell

Open an interactive shell in a deployed container.

**Usage:**
```bash
aegis deploy-shell [OPTIONS]
```

**Options:**

- `--service, -s TEXT`, Service to connect to (default: `webserver`)
- `--project-path TEXT`, Path to the project (default: current directory)

**Examples:**
```bash
# Shell into the webserver (default)
aegis deploy-shell

# Shell into Redis
aegis deploy-shell --service redis

# Shell into Traefik
aegis deploy-shell -s traefik
```

Opens a `/bin/bash` session inside the container via SSH.

---

## TLS/HTTPS with Let's Encrypt

Enable automatic HTTPS on a deployed project using `aegis ingress-enable`.

### aegis ingress-enable

Configure TLS (HTTPS) with automatic Let's Encrypt certificates.

**Usage:**
```bash
aegis ingress-enable [OPTIONS]
```

**Options:**

- `--domain, -d TEXT`, Domain name for the TLS certificate (e.g., `example.com`)
- `--email, -e TEXT`, Email for Let's Encrypt certificate notifications
- `--project-path, -p TEXT`, Path to the project (default: current directory)
- `--yes, -y`, Skip confirmation prompts

**What it does:**

1. Adds the ingress component if not already present
2. Configures `traefik/traefik.yml` with HTTPS entrypoint and ACME resolver
3. Updates Docker Compose labels for TLS routing
4. Adds `traefik-letsencrypt` Docker volume for certificate storage
5. Configures HTTP → HTTPS redirect

**Examples:**
```bash
# Interactive (prompts for domain and email)
aegis ingress-enable

# Fully specified
aegis ingress-enable --domain example.com --email admin@example.com

# Non-interactive
aegis ingress-enable -d example.com -e admin@example.com -y

# On a different project
aegis ingress-enable -p ../my-project -d example.com
```

### Full TLS Workflow

```bash
# 1. Enable TLS on your project
aegis ingress-enable --domain example.com --email admin@example.com

# 2. Deploy to your server
aegis deploy

# 3. Ensure DNS is configured
#    Point your domain's A record to your server IP

# 4. Certificates auto-provision on first request
#    Traefik handles Let's Encrypt automatically
```

After deployment:

- `http://example.com` redirects to `https://example.com`
- Certificates renew automatically before expiration
- Certificate data persists in the `traefik-letsencrypt` Docker volume

!!! warning "DNS must be configured first"
    Let's Encrypt validates domain ownership via HTTP challenge. Your domain's A record must point to the server IP **before** requesting certificates.

---

## Deployment Workflow

### First Deployment

```bash
# 1. Create project with ingress
aegis init my-app --components ingress
cd my-app

# 2. Configure and test locally
uv sync && cp .env.example .env
make serve  # Verify everything works

# 3. Set up deployment
aegis deploy-init --host your-server-ip
aegis deploy-setup

# 4. Deploy
aegis deploy
```

### Subsequent Deployments

```bash
# Make changes, then redeploy (auto-backup + health check)
aegis deploy

# Or skip rebuild for config-only changes
aegis deploy --no-build
```

### Backup and Rollback

Every `aegis deploy` automatically creates a backup before making changes. If the health check fails after deploy, the previous version is restored automatically.

```bash
# Create a manual backup
aegis deploy-backup

# List available backups
aegis deploy-backups

# Rollback to the most recent backup
aegis deploy-rollback

# Rollback to a specific backup
aegis deploy-rollback --backup 2026-03-11_183045
```

**How backups work:**

- Backups are stored on the server at `{deploy_path}/backups/{timestamp}/`
- Each backup contains a full snapshot of deployed files
- PostgreSQL databases are dumped via `pg_dump` (SQLite files are included automatically)
- Old backups are pruned automatically (default: keep last 5)
- Backups are never synced or overwritten during deploys

**Auto-rollback flow:**

```
aegis deploy
  → backup current state
  → sync new code
  → docker compose up
  → health check (GET /health/)
    → pass: done
    → fail: restore backup automatically
```

### Monitoring

```bash
# Check service health
aegis deploy-status

# Follow logs in real-time
aegis deploy-logs

# Check a specific service
aegis deploy-logs --service webserver

# Debug inside a container
aegis deploy-shell
```

---

## Next Steps

- **[Ingress Component](../components/ingress.md)**, Traefik configuration, routing, and admin protection
- **[CLI Reference](../cli-reference.md)**, Complete command reference
- **[Evolving Your Stack](../evolving-your-stack.md)**, Adding components and deploying over time
