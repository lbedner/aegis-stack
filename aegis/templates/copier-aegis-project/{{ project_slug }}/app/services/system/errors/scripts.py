"""Atomic Redis operations for retained errors (standalone Redis, not Cluster).

A mutation removes at most 128 old records. One high-water timestamp keeps
count-pruned history from returning on replay: late records at or before it
are dropped, timestamp ties included. Issue summaries are rebuilt from the
small ``search`` projection, never the full record.
"""

MAINTENANCE = r"""
local p = ARGV[1]
local cutoff = tonumber(ARGV[2])
local maximum = tonumber(ARGV[3])
local function summary(fp)
    local group = p .. 'occurrences:' .. fp
    local first = redis.call('ZRANGE', group, 0, 0)
    local last = redis.call('ZREVRANGE', group, 0, 0, 'WITHSCORES')
    if #first == 0 then
        redis.call('HDEL', p .. 'summaries', fp)
        redis.call('ZREM', p .. 'issues', fp)
        return
    end
    local a = cjson.decode(redis.call('HGET', p .. 'search', first[1]))
    local b = cjson.decode(redis.call('HGET', p .. 'search', last[1]))
    local row = {fingerprint=fp, page=b.page, service=b.service,
        app_service=b.app_service, container_name=b.container_name,
        message=b.message, exception_type=b.exception_type,
        count=redis.call('ZCARD', group), first_seen=a.timestamp,
        last_seen=b.timestamp, latest_id=b.id}
    redis.call('HSET', p .. 'summaries', fp, cjson.encode(row))
    redis.call('ZADD', p .. 'issues', last[2], fp)
end
local function prune()
    local changed = {}
    for n=1,128 do
        local oldest = redis.call('ZRANGE', p .. 'all', 0, 0, 'WITHSCORES')
        if #oldest == 0 then break end
        if tonumber(oldest[2]) >= cutoff and redis.call('ZCARD', p .. 'all') <= maximum then break end
        local raw = redis.call('HGET', p .. 'search', oldest[1])
        if raw then
            local fp = cjson.decode(raw).fingerprint
            redis.call('ZREM', p .. 'occurrences:' .. fp, oldest[1])
            changed[fp] = true
        end
        redis.call('HDEL', p .. 'records', oldest[1])
        redis.call('HDEL', p .. 'search', oldest[1])
        redis.call('ZREM', p .. 'all', oldest[1])
        local water = tonumber(redis.call('GET', p .. 'watermark') or '-1')
        if tonumber(oldest[2]) > water then redis.call('SET', p .. 'watermark', oldest[2]) end
    end
    for fp,_ in pairs(changed) do summary(fp) end
end
"""

# ARGV[4] the writer's lease token ('' for an unfenced write), ARGV[5] the
# record, ARGV[6] its score, ARGV[7] the notifications stream, ARGV[8] the
# search projection.
INSERT = (
    MAINTENANCE
    + r"""
local token = ARGV[4]
if token ~= '' and redis.call('GET', p .. 'lease') ~= token then return 'fenced' end
local event = cjson.decode(ARGV[5])
local score = tonumber(ARGV[6])
if redis.call('HEXISTS', p .. 'records', event.id) == 1 then return 'replay' end
if score < cutoff or score <= tonumber(redis.call('GET', p .. 'watermark') or '-1') then return 'expired' end
redis.call('HSET', p .. 'records', event.id, ARGV[5])
redis.call('HSET', p .. 'search', event.id, ARGV[8])
redis.call('ZADD', p .. 'all', score, event.id)
redis.call('ZADD', p .. 'occurrences:' .. event.fingerprint, score, event.id)
prune()
summary(event.fingerprint)
redis.call('XADD', ARGV[7], 'MAXLEN', '~', 10000, '*', 'fingerprint', event.fingerprint)
return 'inserted'
"""
)

PRUNE = (
    MAINTENANCE
    + r"""
prune()
local first = redis.call('ZRANGE', p .. 'all', 0, 0, 'WITHSCORES')
return {redis.call('ZCARD', p .. 'all'), first[2] or '-1'}
"""
)

# The collector's other writes, each only while it holds the lease (KEYS[1]
# the lease, ARGV[1] its token): 0 when another process took it over.
FENCE = "if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end\n"
LEASE = (
    FENCE
    + "if ARGV[2] == '0' then return redis.call('DEL', KEYS[1]) end\n"
    + "return redis.call('EXPIRE', KEYS[1], ARGV[2])"
)
STATUS = FENCE + "redis.call('SET', KEYS[2], ARGV[2], 'EX', 60)\nreturn 1"
CURSOR = FENCE + "redis.call('HSET', KEYS[2], ARGV[2], ARGV[3])\nreturn 1"
