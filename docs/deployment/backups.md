# Backups and restore

Three layers: a backup on the server before every deploy, an encrypted copy off
the server every night, and a drill that proves the copy comes back.

## On every deploy

Every `aegis deploy` backs up first, checks the app's health after, and
restores the backup on its own if the check fails:

```
aegis deploy
  → back up the current state
  → sync the new code
  → docker compose up
  → health check (GET /health/)
    → pass: done
    → fail: restore the backup
```

A backup is a timestamped directory on the server, `backups/<timestamp>/`:

1. **The database.** A SQLite database is snapshotted into `data/` through
   SQLite's online backup API, run in the webserver container: a consistent
   copy while the app keeps writing (if the snapshot fails, the live file is
   copied with the rest instead). A PostgreSQL database is dumped to
   `db_backup.sql`.
2. **The files**, into `files/` via server-side `rsync`: the code and the
   server's `.env`.
3. **The object store** (the `storage-data` volume), archived to
   `storage.tar.gz`.

Old backups beyond `backup.keep_count` (default 5) are pruned, and deploys
never sync over or delete `backups/`.

```bash
aegis deploy-backup                                # back up now
aegis deploy-backups                               # list them
aegis deploy-rollback                              # restore the newest
aegis deploy-rollback --backup 2026-03-11_183045   # or a given one
```

A rollback stops the services, restores the files (skipped for a backup
without `files/`, such as one restored from off the server), the SQLite
snapshot, the object store and the PostgreSQL dump, whichever the backup has,
then rebuilds and starts the services. Overseer > Deployments offers the same:
**Back up**, the list under Backups, and **Roll back**.

## Off the server

Backups on the server die with it. A project with the deploy component, a
database and the scheduler sends its nightly backup elsewhere: at 02:00 the app
backs up its database (and its stored files, on the filesystem store), and at
02:30 its off-site job sends that backup with [restic](https://restic.net) to
S3-compatible storage (DigitalOcean Spaces, Backblaze B2, AWS S3). restic
encrypts it before it leaves, and keeps 7 daily, 4 weekly and 6 monthly copies.

It does nothing until these four are set, in `.env.deploy` or in
Overseer > Secrets:

```bash
OFFSITE_BACKUP_REPOSITORY=s3:https://nyc3.digitaloceanspaces.com/<bucket>/<project>
OFFSITE_BACKUP_PASSWORD=<long random password>
OFFSITE_BACKUP_ACCESS_KEY=<Spaces key id>
OFFSITE_BACKUP_SECRET_KEY=<Spaces key secret>
```

Keep the password and the app's `ENCRYPTION_KEY` somewhere else too (a
password manager): without them the copies cannot be read, nor the app's
encrypted fields. Overseer > Deployments > Backups shows the last copy (or that
none is set up, or when the first leaves), and History lists each one.

## Rehearse a restore

A backup nobody has restored is a guess. The restore drill restores the newest
off-site copy on your machine and runs the app's own checks on it:

- the database is whole
- the app starts on it
- every stored secret decrypts with the `ENCRYPTION_KEY` kept off the server
- every stored file is there

```bash
aegis deploy-restore-drill
```

Or **Rehearse a restore** on the server's card in Overseer > Deployments; the
last drill shows under Backups.

<!-- Screenshot: Overseer > Deployments > Backups, a passed drill. -->

restic's own image restores the copy into a scratch directory, and a
throwaway container from the project's webserver image lays it out and checks
it. Nothing on the server changes but the drill's record, and the scratch
directory is emptied however the drill ends. The drill needs a SQLite project
(the copy is one file).

## Restoring by hand

Anywhere with restic and the same four values, as restic names them:

```bash
export RESTIC_REPOSITORY=...       # OFFSITE_BACKUP_REPOSITORY
export RESTIC_PASSWORD=...         # OFFSITE_BACKUP_PASSWORD
export AWS_ACCESS_KEY_ID=...       # OFFSITE_BACKUP_ACCESS_KEY
export AWS_SECRET_ACCESS_KEY=...   # OFFSITE_BACKUP_SECRET_KEY

restic snapshots
restic restore latest --target <dir>
```

## Settings

In `.aegis/deploy.yml`, all optional:

```yaml
backup:
  keep_count: 5           # backups kept on the server
  include_database: true  # the database (SQLite snapshot or PostgreSQL dump)

health_check:
  retries: 3              # health check attempts
  auto_rollback: true     # restore the backup on a failed check
```

To skip both for a quick redeploy you're sure of:
`aegis deploy --no-backup --no-health-check`.
