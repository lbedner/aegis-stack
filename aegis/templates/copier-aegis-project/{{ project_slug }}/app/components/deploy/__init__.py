"""Deploy component: where the app runs (Docker Compose on a host today).

The seam is ``app.core.runtime``; this package is the backend that reads
the running containers through the ``socket-proxy`` service, the only
container that mounts the Docker socket, read-only, over a Unix socket in
the ``docker-proxy`` volume.
"""
