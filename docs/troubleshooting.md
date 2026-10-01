# Troubleshooting

## Stale or truncated files in dev containers (macOS)

### What it looks like

On macOS with Docker Desktop, the dev stack shares the project into its
containers through a bind mount (`.:/code`). Docker Desktop's default file
sharing (VirtioFS) caches file attributes inside its Linux VM. After a file
is rewritten in place (truncated, then written again), a container can keep
seeing the old size or modification time, so it reads a truncated file.

It tends to follow bulk writes: `aegis add`, `ruff format` / `make fix`, or an
editor that saves in place. The symptoms look like broken code:

- a syntax error in a file that is fine on disk, and a webserver that stays
  down after a reload;
- a reload that never happens after you save;
- a CSS build failing with `Unclosed block`, and new Tailwind classes that
  never appear.

### How to confirm it

Compare the file's size on the host and in the container:

```bash
wc -c app/components/frontend/dashboard/cards/__init__.py
docker exec <project>-webserver-1 wc -c /code/app/components/frontend/dashboard/cards/__init__.py
```

Different sizes (and an older modification time inside the container) mean
the container is reading a stale copy.

### Immediate fix

Replace the file instead of rewriting it, so the container sees a new file:

```bash
cp path/to/file path/to/file.tmp && mv path/to/file.tmp path/to/file
```

`touch` is not enough: it keeps the same file, and the cached attributes stay.
Then restart whatever stopped on the bad read, for example
`docker restart <project>-webserver-1`.

The dev Tailwind watcher recovers on its own: it restarts when it exits, or
when a template, script or stylesheet changed and no build followed.

### Durable options

- **OrbStack**, a drop-in replacement for Docker Desktop on macOS. Its file
  sharing does not show this.
- **Docker Desktop with gRPC FUSE** file sharing (Settings, General, "Choose
  file sharing implementation"). Slower than VirtioFS, without the stale
  attributes.

Linux hosts share files natively and are not affected.
