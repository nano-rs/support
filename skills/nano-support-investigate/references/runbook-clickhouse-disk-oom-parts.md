# Runbook: ClickHouse disk full, out of memory, too many parts

ClickHouse stores nano's events. Three problems cover most of its trouble:
the disk fills, a query or merge runs out of memory, or one partition gets
more small parts than merges can keep up with.

## Symptoms

| Symptom | Points to |
|---|---|
| `nano-clickhouse` restarted, `oom_killed=true`, exit 137, `signal 9` | the kernel killed ClickHouse (host or container memory) |
| `Code: 241 ... MEMORY_LIMIT_EXCEEDED`; users see "Query exceeded memory limit" | a query or merge needed more than ClickHouse may use |
| `Code: 243 ... NOT_ENOUGH_SPACE`, `No space left on device`, `Cannot reserve`; nano says `ClickHouse disk full` | disk full |
| `Code: 252 ... TOO_MANY_PARTS`, `Merges are processing significantly slower than inserts` | too many parts in one partition |
| `Code: 202 ... TOO_MANY_SIMULTANEOUS_QUERIES` | more queries at once than allowed, often on a small host |
| `Code: 117 ... INCORRECT_DATA` | an insert carried a value ClickHouse can't parse |
| Searches slow, ingest backpressure | any of the above |

## Evidence

```bash
support query --recipe restarts-oom
support query --recipe ch-errors
support query --recipe ch-codes-in-logs
support query --recipe ch-query-failures
support query --recipe disk
support query --recipe too-many-parts
support query --recipe slow-queries
```

Memory: what ClickHouse may use and what the host has.

```sql
SELECT name, toString(value.metric) AS metric, toString(value.value) AS v FROM probes
WHERE name IN ('ch-memory', 'clickhouse:asynchronous-metrics') ORDER BY metric;
SELECT toString(value.name) AS setting, toString(value.value) AS v FROM probes WHERE name = 'ch-settings';
SELECT toString(value.container) AS c, formatReadableSize(toFloat64OrZero(toString(value.mem_limit_bytes))) AS mem_limit
FROM probes WHERE name = 'containers' AND toString(value.container) ILIKE '%clickhouse%';
SELECT key, value FROM facts WHERE key IN ('env.CLICKHOUSE_MEM_LIMIT', 'env.NANO_PLANNED_GB_PER_DAY', 'env.NANO_RETENTION_DAYS');
```

Which queries ran out of memory (by shape, never by text):

```sql
SELECT toString(value.normalized_query_hash) AS shape, toString(value.user) AS user,
       toString(value.exception_codes) AS codes, toString(value.p95_ms) AS p95_ms,
       formatReadableSize(toFloat64OrZero(toString(value.max_memory))) AS max_memory
FROM probes WHERE name LIKE 'ch-query-log-slowest-shapes%' AND toString(value.exception_codes) LIKE '%241%';
```

The `user` tells you who: `nanosiem_search` is analysts' searches,
`nanosiem_ingest` or Vector's user is inserts, `nanosiem_jobs` (or similar) is
detections, hunts and enrichment, `agentlane_*` is an AI agent on Agent Lane.

Parts: one partition with thousands of active parts is the signature of 252.

```sql
SELECT name, toString(value.table) AS tbl, toString(value.partition) AS p,
       toInt64OrZero(toString(value.active_parts)) AS parts
FROM probes WHERE name IN ('clickhouse:parts-hot-partitions', 'ch-parts-by-partition') ORDER BY parts DESC LIMIT 10;
SELECT toString(value.name) AS setting, toString(value.value) AS v FROM probes WHERE name = 'ch-merge-tree-settings';
```

## Likely causes

- **OOM kill (137):** the host is short of memory, or other containers took
  it. Check `host:memory` and `memory` probes, and `CLICKHOUSE_MEM_LIMIT`.
  The enrichment dictionaries alone need about 6 GB; hosts with less than
  16 GB should run with the enrichment feeds off.
- **241 on searches:** a wide search (long time range, free text across all
  events, a large `stats` by a high-cardinality field). On merges: too little
  memory for the volume.
- **243 / disk full:** retention longer than the disk holds, or tiering off.
  nano's disk pressure service drops the oldest daily partitions from 80%
  disk use (the OCSF events table included, always keeping today's), unless
  storage tiering is on. It stops when the rest of the disk, not ClickHouse,
  is what fills it: then the data that fills the disk is outside nano.
- **252:** many small inserts into one partition: a sender that posts one
  event per request, events with timestamps spread over many days (each day
  is a partition), or merges starved of CPU or disk.
- **202:** a small host, or many dashboards refreshing at once.
- **117:** a sender or parser emits a field in the wrong type.

## Safe fixes (ask first)

Memory:

- Right-size the host, or set `CLICKHOUSE_MEM_LIMIT` in `.env` and re-run the
  installer (Compose); on Helm, raise the ClickHouse resources in the values.
  On a lab host under 16 GB, the operator can turn off the enrichment feeds
  (`PLATFORM_FEEDS_AUTO_UPDATE=false`). See
  [Install with Docker Compose](https://nano.rs/docs/getting-started/install-compose/).
- For 241 on searches: narrow the search (shorter range, more filters, a
  field filter before free text). This needs no change on the install.

Disk:

- Check first whether the disk pressure service is already dropping old
  partitions (`partition_dropped` audit events; Settings, Storage &
  Retention). Don't drop partitions by hand while it works.
- Read [Disk pressure](https://nano.rs/docs/settings/disk-pressure/) and
  [Storage and retention](https://nano.rs/docs/settings/storage/) with the
  operator. Options, least to most drastic: add disk; shorten retention;
  turn on storage tiering; lower the disk pressure watermarks.
- Dropping a partition deletes those events for good. It needs its own
  explicit "yes", the partition names, and the operator's confirmation that
  the data is not needed (legal hold, investigations).

Too many parts:

- Find and fix the sender pattern (batch events; fix timestamps far in the
  past or future). Inserts recover once merges catch up.
- Do not raise `parts_to_throw_insert` as a fix: it hides the problem and
  makes merges heavier.

## Escalate

Escalate when ClickHouse keeps getting OOM-killed on a host sized for the
planned volume, when 252 continues after senders batch properly, when merges
or mutations show failures (`ch-mutations` `latest_fail_reason`), or on any
read-only replica. Send:

- the bundle (with probes);
- the planned GB/day and retention, host size (CPU, RAM, disk);
- the error codes with first and last times (UTC) from `ch-errors`;
- for 241: the shapes and users from `slow-queries` (no query text is in the
  bundle; the operator may add the search in their own words).
