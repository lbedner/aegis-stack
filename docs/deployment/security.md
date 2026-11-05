# How it works and security

## What a deploy does

`aegis deploy`, from your machine, Overseer or CI:

1. **Backs up** the current deployment: database, files, object storage
   ([Backups and restore](backups.md))
2. **Syncs files** to the server with `rsync --delete`, so a file removed from
   the project is removed from the server too. Only files git tracks are sent:
   untracked files (`.env.backup-*`, notes, local dumps) stay on your machine,
   and one an earlier deploy left on the server is removed. Outside git, or
   before anything is tracked, the directory is sent as it is
3. **Copies the env file** separately (`.env.deploy`, else `.env`), as it is
   excluded from the sync
4. **Stops the services** with `docker compose down`
5. **Builds and starts them** with the production compose overrides
6. **Restarts Traefik**, when the ingress component is there, so it rediscovers
   the containers
7. **Checks health** against `/health/` (through HTTPS for the app's name when
   TLS is on)
8. **Rolls back** to the backup from step 1 if the check fails
9. **Records the deploy** in the app's [deploy history](../components/deploy.md#deploy-history),
   with the deploy component and a database: who deployed, from where, the
   health result, the backup and any rollback

`--rolling` swaps steps 4 and 5 for no downtime: it brings the database up to
the new code, pauses the worker queue so in-flight jobs finish, then swaps the
webserver for a healthy new replica (additive migrations only).

The sync deletes, and rsync never deletes an excluded path, so the exclusions
also protect what lives only on the server:

- `.git`, `__pycache__`, `.venv`, `*.pyc`, `.pytest_cache`, `.ruff_cache`,
  `node_modules/`
- `data/`, the database files
- `.env` and `.env.deploy`, copied separately
- `.aegis/`, the deploy configuration
- `backups/`, the server's backups
- `traefik/acme/`, the Let's Encrypt certificate store (deleting it forces
  re-issuance and can hit rate limits)

## What can reach production

Three things can change a deployed server: your machine (the CLI, or the dev
Overseer through its agent), and CI. Nothing on the server deploys to itself.

**The deployed app cannot deploy.** A deployed server's Overseer offers no
deploy actions; it points at the dev Overseer or CI. The deploy agent runs on
your machine, never on the server, and Overseer only asks it, through the
project's Redis ([From Overseer](overseer.md#the-deploy-agent)).

**Keys stay where they are.** The agent signs with your machine's ssh-agent,
never a key file. CI has [its own key](ci.md#the-deploy-key), for this project
only, rotatable with `aegis deploy-cd-setup --force`, and by default deleted
locally once it is in GitHub's write-only secrets.

**Cloud tokens are never kept.** Overseer sends a token with the one request
that needs it, beside its arguments, so it is never audited or shown; the agent
hands it to the command in its environment, masks it in the output and keeps it
nowhere; the CLI never stores or prints it
([Cloud accounts and keys](cloud.md#how-a-token-is-handled)).

**Only what you meant is shipped.** Only git-tracked files are sent; the env
file is copied on its own; the server's database, backups and certificates are
out of the sync's reach.

**An open env is refused.** An env that would put the app online open (sign-in
off on a project with auth, a development or unset `APP_ENV`, no `SECRET_KEY`)
stops `aegis deploy` before it reaches the server, `aegis deploy-provision`
before it buys one, and `aegis deploy-cd-env` before it reaches GitHub. And
`aegis deploy-cd-env` never pushes `.env` in place of a missing `.env.deploy`:
that is the dev env, and the next deploy would ship it to production.

**A failed deploy undoes itself.** The backup is taken first, and a failed
health check restores it.

**Every action leaves a trace.** Each Overseer action is audited, its output
kept under Deployments > Jobs, and each deploy recorded in History, with the
deploy component and a database.
