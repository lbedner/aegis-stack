"""Backfill Overseer's live charts for a demo: a fresh stack has seconds of
history, a recording wants a week.

Every series the samplers have started is filled backwards from its oldest
real point, on the keys, tiers and point format the app itself keeps
(``app.core.series``, ``app.core.series_store``): the raw hour, each minute
for a day, each five minutes for a week. Gauges wander around their real value; running totals
(network, disk, jobs done) climb to it.

Run inside the stack:
    docker compose exec -T webserver python - < seed_metrics.py
"""

import math
import random
import time
import zlib
from itertools import accumulate

import redis
from app.core import series
from app.core.config import settings
from app.core.series_store import _member, _point

# The raw hour at a point every 15 s: dense enough to read as live, light
# enough to write.
TIERS = (("hour", 15, series.KEEP_SECONDS),) + tuple(
    (str(step), step, keep) for step, keep in series.TIERS
)
TOTALS = ("net_in", "net_out", "disk_read", "disk_write", "done")
FLAT = ("restart", "pids")


def wave(t: float, rng: random.Random, phase: float) -> float:
    """A daily swell, an hourly ripple and noise, around 1."""
    day = 0.3 * math.sin(2 * math.pi * t / 86400 + phase)
    hour = 0.15 * math.sin(2 * math.pi * t / 3600 + phase * 3)
    spike = 0.6 if rng.random() < 0.01 else 0.0
    return max(0.05, 1 + day + hour + rng.gauss(0, 0.06) + spike)


def backfill(
    name: str,
    sampled: list[tuple[float, float]],
    join: tuple[float, float],
    step: int,
    keep: int,
    now: float,
) -> list[tuple[float, float]]:
    """Points every ``step`` from ``keep`` ago up to ``join`` (the oldest
    point the tier keeps, or the newest sampled where it keeps none yet), at
    the level and pace the raw hour ``sampled`` reads."""
    rng = random.Random(zlib.crc32(f"{name}:{step}".encode()))
    phase = rng.uniform(0, 2 * math.pi)
    join_at, joined = join
    times = list(range(int(now - keep), int(join_at), step))
    kind = name.rsplit(":", 1)[-1]
    if kind in FLAT:
        return [(t, joined) for t in times]
    if kind in TOTALS:
        (first_at, first), (last_at, last) = sampled[0], sampled[-1]
        rate = (last - first) / (last_at - first_at) if last_at > first_at else 0
        rate = rate or rng.uniform(200, 4000)
        climbs = [rate * step * wave(t, rng, phase) for t in times]
        # Up to the join where it fits; where it would start below zero it
        # starts at zero and resets at the join instead, as a restart does
        # (the chart skips a total that went down).
        start = max(0.0, joined - sum(climbs))
        return list(zip(times, accumulate(climbs, initial=start), strict=False))
    if kind == "queued":
        return [(t, float(max(0, round(rng.gauss(3, 4))))) for t in times]
    base = sum(v for _, v in sampled) / len(sampled)
    return [(t, base * wave(t, rng, phase)) for t in times]


def main() -> None:
    r = redis.Redis.from_url(
        settings.redis_url_effective, db=settings.CACHE_REDIS_DB, decode_responses=True
    )
    now = time.time()
    raw, raw_index = series.tier("hour")
    seeded = 0
    # Every tier from the raw hour's series: a tier is folded a bucket after
    # boot (five minutes for the week's), so soon after one it keeps none.
    for index in r.scan_iter(f"{raw_index}*"):
        sampler = str(index).removeprefix(raw_index)
        for key in map(str, r.smembers(index)):
            sampled = [_point(m) for m in r.lrange(key, 0, -1)]
            if not sampled:
                continue
            name = key.removeprefix(raw)
            for tier, step, keep in TIERS:
                prefix, tier_index = series.tier(tier)
                kept = [_point(m) for m in r.lrange(prefix + name, 0, -1)]
                join = kept[0] if kept else sampled[-1]
                points = backfill(name, sampled, join, step, keep, now) + kept
                pipe = r.pipeline()
                pipe.delete(prefix + name)
                pipe.rpush(prefix + name, *(_member(at, value) for at, value in points))
                pipe.expire(prefix + name, keep)
                pipe.sadd(tier_index + sampler, prefix + name)
                pipe.expire(tier_index + sampler, keep)
                pipe.execute()
                seeded += 1
    print(f"seeded {seeded} series")


if __name__ == "__main__":
    main()
