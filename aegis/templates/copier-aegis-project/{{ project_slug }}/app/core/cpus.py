"""How many CPUs this process may use: its container's quota (cgroup v2
``cpu.max``) where it has one, else the machine's cores. A library that
sizes its threads by the machine (PyTorch does) runs far more threads than
a capped container can serve, and throttles itself and everything beside
it; size them by this instead."""

import math
import os
from pathlib import Path

QUOTA = Path("/sys/fs/cgroup/cpu.max")


def allowed(quota: Path = QUOTA) -> int:
    """Whole CPUs this process may use: its quota rounded up, else every
    core; at least one."""
    try:
        limit, period = quota.read_text().split()[:2]
    except (OSError, ValueError):
        limit = "max"
        period = "1"
    if limit == "max":
        return os.cpu_count() or 1
    return max(1, math.ceil(int(limit) / int(period)))


def spare_one(quota: Path = QUOTA) -> int:
    """Threads for heavy work that leave one CPU for the rest of the
    process (a server's requests), never fewer than one."""
    return max(1, allowed(quota) - 1)
