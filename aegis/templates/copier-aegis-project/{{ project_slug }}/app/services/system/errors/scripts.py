"""Atomic Redis operations for retained errors (standalone Redis, not Cluster).

A mutation removes at most 128 old records, the oldest first, while the store
holds more than its count, its age or its bytes (``bytes``: what the records
and their search projections take, kept as they are written and removed;
a store from before it is counted once). One high-water timestamp keeps
count-pruned history from returning on replay: late records at or before it
are dropped, timestamp ties included. Issue summaries are rebuilt from the
small ``search`` projection, never the full record.
"""

MAINTENANCE = r"""
local p = ARGV[1]
local cutoff = tonumber(ARGV[2])
local maximum = tonumber(ARGV[3])
local most = tonumber(ARGV[4])
local function size(id)
    return redis.call('HSTRLEN', p .. 'records', id) + redis.call('HSTRLEN', p .. 'search', id)
end
local function held()
    local total = redis.call('GET', p .. 'bytes')
    if total then return tonumber(total) end
    local sum = 0
    for _, id in ipairs(redis.call('ZRANGE', p .. 'all', 0, -1)) do sum = sum + size(id) end
    return sum
end
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
        app_service=b.app_service, app_component=b.app_component,
        container_name=b.container_name,
        message=b.message, exception_type=b.exception_type,
        count=redis.call('ZCARD', group), first_seen=a.timestamp,
        last_seen=b.timestamp, latest_id=b.id}
    redis.call('HSET', p .. 'summaries', fp, cjson.encode(row))
    redis.call('ZADD', p .. 'issues', last[2], fp)
end
local function prune(bytes)
    local changed = {}
    local done = 0
    for n=1,128 do
        local oldest = redis.call('ZRANGE', p .. 'all', 0, 0, 'WITHSCORES')
        if #oldest == 0 or (tonumber(oldest[2]) >= cutoff
            and redis.call('ZCARD', p .. 'all') <= maximum and bytes <= most) then
            done = 1
            break
        end
        local raw = redis.call('HGET', p .. 'search', oldest[1])
        if raw then
            local fp = cjson.decode(raw).fingerprint
            redis.call('ZREM', p .. 'occurrences:' .. fp, oldest[1])
            changed[fp] = true
        end
        bytes = bytes - size(oldest[1])
        redis.call('HDEL', p .. 'records', oldest[1])
        redis.call('HDEL', p .. 'search', oldest[1])
        redis.call('ZREM', p .. 'all', oldest[1])
        local water = tonumber(redis.call('GET', p .. 'watermark') or '-1')
        if tonumber(oldest[2]) > water then redis.call('SET', p .. 'watermark', oldest[2]) end
    end
    redis.call('SET', p .. 'bytes', bytes)
    for fp,_ in pairs(changed) do summary(fp) end
    return done
end
"""

# ARGV[5] the writer's lease token ('' for an unfenced write), ARGV[6] the
# record, ARGV[7] its score, ARGV[8] the notifications stream, ARGV[9] the
# search projection.
INSERT = (
    MAINTENANCE
    + r"""
local token = ARGV[5]
if token ~= '' and redis.call('GET', p .. 'lease') ~= token then return 'fenced' end
local event = cjson.decode(ARGV[6])
local score = tonumber(ARGV[7])
if redis.call('HEXISTS', p .. 'records', event.id) == 1 then return 'replay' end
if score < cutoff or score <= tonumber(redis.call('GET', p .. 'watermark') or '-1') then return 'expired' end
local bytes = held() + #ARGV[6] + #ARGV[9]
redis.call('HSET', p .. 'records', event.id, ARGV[6])
redis.call('HSET', p .. 'search', event.id, ARGV[9])
redis.call('ZADD', p .. 'all', score, event.id)
redis.call('ZADD', p .. 'occurrences:' .. event.fingerprint, score, event.id)
prune(bytes)
summary(event.fingerprint)
redis.call('XADD', ARGV[8], 'MAXLEN', '~', 10000, '*', 'fingerprint', event.fingerprint)
return 'inserted'
"""
)

PRUNE = (
    MAINTENANCE
    + r"""
local done = prune(held())
return {redis.call('ZCARD', p .. 'all'), done}
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
