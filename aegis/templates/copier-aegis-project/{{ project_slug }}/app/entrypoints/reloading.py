"""Dev auto-reload for a process with none of its own (the scheduler, an
arq or taskiq worker): a restart on a change under the watched folder,
and a new process when the one it ran was killed.

watchfiles' CLI, which this replaces, restarts only on a change: one
killed (out of memory) left it running as the container's main process
with nothing under it, so the container was never restarted and nothing
ran. One that exited itself (code that fails to import) waits for the
change that fixes it: a new one would only fail again, in a loop.

    python -m app.entrypoints.reloading /code/app python -m app.entrypoints.scheduler
"""

from collections.abc import Iterable
from signal import SIGINT, SIGKILL, SIGTERM, default_int_handler, signal
import subprocess
import sys

from app.core.log import logger


def killed(exitcode: int | None) -> str | None:
    """Why a process that ended was killed (a negative exit code is the
    signal that did it); None for one running, or that exited itself."""
    if (number := -(exitcode or 0)) <= 0:
        return None
    return "likely out of memory" if number == SIGKILL else f"signal {number}"


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Ask it to stop as watchfiles did (SIGINT), killed if it will not."""
    if process.poll() is not None:
        return
    process.send_signal(SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def supervise(command: list[str], changes: Iterable[set[object]]) -> None:
    """Run ``command``, anew on each batch of ``changes`` and whenever it
    was killed: an empty batch is a tick with no change."""
    process = subprocess.Popen(command)
    try:
        for batch in changes:
            if (cause := killed(process.poll())) is not None:
                logger.error(
                    f"{' '.join(command)} was killed ({cause}); starting anew."
                )
            elif not batch:
                continue
            else:
                _stop(process)
            process = subprocess.Popen(command)
    finally:
        _stop(process)


def main() -> None:
    # Dev only, and not in every stack (it ships with uvicorn[standard]):
    # the entrypoint checks it imports before running this.
    from watchfiles import PythonFilter, watch

    path, *command = sys.argv[1:]
    # ``docker stop`` as Ctrl-C: watchfiles ends the loop on either with
    # KeyboardInterrupt, and ``supervise`` stops the process on the way out.
    signal(SIGTERM, default_int_handler)
    changes = watch(
        path, watch_filter=PythonFilter(), yield_on_timeout=True, rust_timeout=1000
    )
    try:
        supervise(command, changes)
    except KeyboardInterrupt:
        logger.info(f"Stopped: {' '.join(command)}")


if __name__ == "__main__":
    main()
