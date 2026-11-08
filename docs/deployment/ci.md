# From CI

Two commands wire GitHub Actions deploys: `aegis deploy-cd-setup` gives CI its
own key and a workflow, and `aegis deploy-cd-env` ships the production env.

## Set it up

```bash
aegis deploy-cd-setup                # workflow_dispatch trigger
aegis deploy-cd-setup --on-tag       # also deploy on v* tag pushes
aegis deploy-cd-setup --on-merge     # also deploy each merge to main, once CI passes
aegis deploy-cd-setup --dry-run      # see the plan without touching anything
aegis deploy-cd-setup --force        # rotate the deploy key
```

It needs `aegis deploy-init` to have run (it reads `.aegis/deploy.yml`), the
[GitHub CLI](https://cli.github.com/) authenticated (`gh auth login`), and your
own SSH access to the server, which it uses to install the new key. Then it:

1. Detects the GitHub repo from `git remote get-url origin` (or honors `--repo`)
2. Generates a fresh ed25519 keypair in a temp directory, no passphrase, comment `github-actions-deploy@OWNER/REPO`
3. Appends the public key to the deploy user's `authorized_keys` on the server (idempotent)
4. Pushes four secrets to the repo: `DEPLOY_SSH_KEY` (the private key), `DEPLOY_HOST`, `DEPLOY_USER`, and `DEPLOY_CONFIG` (the whole `.aegis/deploy.yml`, which is gitignored, so a checkout has none)
5. Writes `.github/workflows/deploy.yml`
6. Records the key's fingerprint in `.aegis/deploy.yml` under `ci.github`, so a re-run sees it is configured
7. Securely deletes the temp private key (overwrites, then unlinks)

## What the workflow runs

It writes `.aegis/deploy.yml` back from `DEPLOY_CONFIG` (and `.env.deploy` from
`DEPLOY_ENV`, once `aegis deploy-cd-env` has pushed one), then runs
`aegis deploy` from the aegis-stack the project is on: the `_commit` in
`.copier-answers.yml` (so `aegis update` keeps CI in step), else the release
that wrote the workflow. A runner has no `aegis` of its own.

The deploy is rolling (`aegis deploy --rolling`, no downtime), as you would run
it by hand: Run workflow has a **rolling** box, ticked by default, to untick for
a standard deploy; a `v*` tag push (`--on-tag`) and a merge (`--on-merge`)
always deploy rolling. A merge deploys when the `CI` workflow passes on its push
to main, at the commit CI tested: a red main or a pull request's run deploys
nothing. Two deploys never run at once.

A change to `.aegis/deploy.yml` reaches CI when you re-run
`aegis deploy-cd-setup --force`.

## Ship the production env

Until `aegis deploy-cd-env` has run, the runner has no `.env.deploy` or `.env`,
so a CI deploy keeps the server's `.env` as the last deploy from your machine
left it.

```bash
aegis deploy-cd-env                       # pushes .env.deploy
aegis deploy-cd-env --env-file prod.env
```

It sends the file whole, as written, as the `DEPLOY_ENV` secret of the repo
`aegis deploy-cd-setup` wired; the workflow writes it back to `.env.deploy`
before `aegis deploy`, which copies it to the server as it does from your
machine. Run it again after changing the file: the secret is replaced, never
merged. What it refuses: [Security](security.md#what-can-reach-production).

A workflow written before this command existed has no step that reads
`DEPLOY_ENV`; `aegis deploy-cd-setup --force` writes the current one (and
rotates the key).

## The deploy key

!!! tip "Why a dedicated deploy key"
    Don't reuse your personal SSH key for CI. A dedicated key has a smaller blast radius (it only deploys this one project), can be rotated without touching your other servers, and shows up as a distinct identity in `auth.log`.

!!! warning "Backing up the deploy key"
    GitHub Actions secrets are **write-only**: once the private key is uploaded, you can't read it back from the API or UI. By default the only copy lives in GitHub.

    For a local copy (a password manager, disaster recovery, another CI provider), pass `--keep-key PATH` at setup:
    ```bash
    aegis deploy-cd-setup --keep-key ~/.ssh/aegis_deploy_ci
    ```

    Already set up without it? There's no way to extract the existing key, so rotate it and keep the new one:
    ```bash
    aegis deploy-cd-setup --force --keep-key ~/.ssh/aegis_deploy_ci
    ```
    This generates a fresh key, replaces the public key on the server, overwrites the GitHub secret, and saves a local copy.
