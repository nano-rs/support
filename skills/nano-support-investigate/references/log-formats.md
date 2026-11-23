# Tables, services and log formats

## The tables

`support load` writes four tables in database `support`. Every row has a
`bundle` column (the file name), so several bundles can sit side by side.

| Table | Columns | One row per |
|---|---|---|
| `logs` | `bundle, host, service, container, ts, level, target, message, fields JSON, file, line, previous` | log line |
| `k8s_events` | `bundle, ts, type, reason, object, message, raw` | Kubernetes event (Helm bundles) |
| `facts` | `bundle, host, key, value` | fact: `manifest.*`, `host.*`, `release.*`, `env.*` (key names; secret values show `[REDACTED]`), `install.*`, `probes.collected_utc` |
| `probes` | `bundle, host, source, name, ok, row, value JSON, text` | table row of a bundle section or a live probe |

- `logs.ts` is UTC, from the `docker logs --timestamps` or `kubectl logs
  --timestamps` prefix, or from the line itself. Continuation lines (stack
  traces, multi-line VRL warnings) take the time of the line before.
- `logs.level` is `ERROR`, `FATAL`, `WARN`, `INFO`, `DEBUG`, or empty when the
  line states none (program banners, continuation lines).
- `logs.previous = 1` marks a Kubernetes `--previous` log: the container run
  before the last restart. It usually holds the crash reason.
- `probes.source` is `bundle` (a section of nano's bundle) or `live` (a probe
  from `support collect`). `probes.ok = 0` marks a section nano marked
  `(FAILED)`, or a probe that failed.
- Bundle section names are `<file>:<section title>`, for example
  `clickhouse:errors-recent`, `postgres:migrations`, `compose:compose ps`,
  `disk:data directories (is each its own mount?)`. On Helm bundles the
  ClickHouse file is per pod: `clickhouse/<pod>:errors-recent`.
- List them: `SELECT DISTINCT source, name FROM probes ORDER BY name`.

## Services and container names

Compose single node (open edition and Self-run), container names:

| Container | Service | What it does |
|---|---|---|
| `nano-api` | `nano-api` (`service = 'api'` in `logs`) | REST API, settings, rules, license, Vector config delivery |
| `nano-search` | `nano-search` (`search`) | query execution |
| `nano-jobs` | `nano-jobs` (`jobs`) | scheduled detections, hunts, enrichment, health checks |
| `nano-vector` | `vector` | ingest: HEC :8088, HTTP :8080, OTLP :4317/:4318, Vector native :6000 |
| `nano-vector-netns` | `vector-netns` | holds Vector's network namespace and published ports; stays up while Vector restarts |
| `nano-vector-tap` | `vector-tap` | live event sampling for the UI (never collected: it prints events) |
| `nano-clickhouse` | `clickhouse` | event store |
| `nano-clickhouse-migrate` | `clickhouse-migrate` | one-shot: applies PostgreSQL then ClickHouse migrations, then exits 0 |
| `nano-clickhouse-preflight` | `clickhouse-preflight` | one-shot check before ClickHouse starts |
| `nano-postgres` | `postgres` | metadata store |
| `nano-valkey` | `dragonfly` (`valkey`) | cache and queues (Valkey) |
| `nano-web`, `nano-nginx` | `nano-web`, `nginx` (`web`) | the UI and the front proxy |

Role split (enterprise) uses Compose's default names (`<project>-<service>-1`)
and adds `keeper`, `postgres-ha`, `etcd`, `valkey-ha`, `valkey-sentinel`,
`clickhouse-proxy`, `app-api-proxy`, `ingest-proxy`, `ingest-edge` and
`vector-config-consumer`. Helm pods carry the same service names.

## Log line formats

**nano's Rust services** (api, search, jobs, the migrator) use `tracing`.

- Compose: one line per event, plain text, with ANSI colors (the loader
  strips them):

  ```
  2026-11-23T13:16:51.504965Z  INFO service{service.name="nanosiem-api" deployment_id= version="2.0.34"}: nanosiem_api: Starting NanoSIEM API server
  ```

  `level` = `INFO`, `target` = `nanosiem_api`, `message` = the rest. Fields
  such as `error=...` stay in `message`.

- Helm (`LOG_FORMAT=json`): one JSON object per line. The loader puts
  `fields.message` in `message`, the other fields (and `span`, `spans`) in
  `fields`:

  ```
  {"timestamp":"...","level":"ERROR","fields":{"message":"Refusing to start: PostgreSQL schema is behind","error":"..."},"target":"nanosiem_search","span":{...}}
  ```

  Query a field: `toString(fields.error)`.

- `target` is the Rust module: `nanosiem_core::license::checker`,
  `nanosiem_core::db::dual_pool`, `nanosiem_core::hunts::service`,
  `nanosiem_core::parsers::vector_config::deploy`, and so on. Filtering on
  `target ILIKE '%license%'` is a quick way into one subsystem.

**Vector** (`nano-vector`): `<ts> LEVEL <target>: <message> key=value`, for
example

```
2026-11-23T09:02:11.401220Z ERROR vector::cli: Configuration error. error=Input "syslog_tcp" for transform "tag_firewall" doesn't match any components.
```

Some Vector lines are JSON objects with `"source_type":"internal_logs"`
(Vector's own log events). nano's bundle scrubs their `metadata`, which holds
the level, so they load with `target = 'vector::internal_logs'` and an empty
level. Read their `message`.

nano's Vector entrypoint prints its own lines with a `nano-vector:` prefix
(`nano-vector: not starting Vector yet ...`), and VRL diagnostics print
`warning[E620]: ...` followed by indented continuation lines. In nano's bundle,
Vector's log keeps warning and error lines only.

**vector-config-consumer** (role split, Helm): `[2026-11-23T13:20:00Z] Installed
Vector config generation 12 (previous 11)`, with `ERROR: ` after the time on
errors.

**ClickHouse**: `2026.11.23 13:30:55.120300 [ 812 ] {query_id} <Error>
executeQuery: Code: 241. DB::Exception: ...`. The loader maps `<Error>`,
`<Warning>`, `<Fatal>`, `<Information>` to levels and copies `Code: N` into
`fields.code`. Only warning and error lines are kept in the bundle. Most of
what ClickHouse logs goes to files inside the container, so
`clickhouse:errors-recent` (from `system.errors`) is the better source.

**PostgreSQL**: `2026-11-23 13:05:00.100 UTC [57] ERROR:  relation ...`.

**nginx**: access lines become `target = 'access'` with `fields.status`;
5xx is `ERROR`, 4xx is `WARN`.

## ClickHouse error codes you will meet

| Code | Name | Usually means |
|---|---|---|
| 60 | UNKNOWN_TABLE | right after the first start: normal. Later: a migration did not run |
| 117 | INCORRECT_DATA | a value ClickHouse can't parse in an insert (a sender's malformed field, a parser bug) |
| 159 | TIMEOUT_EXCEEDED | a search ran past its time limit |
| 202 | TOO_MANY_SIMULTANEOUS_QUERIES | too many queries at once, often a small host |
| 210 | NETWORK_ERROR | a client went away mid-answer (a closed browser tab): usually noise |
| 241 | MEMORY_LIMIT_EXCEEDED | a query or merge needed more memory than ClickHouse may use |
| 243 | NOT_ENOUGH_SPACE | disk full |
| 252 | TOO_MANY_PARTS | inserts are faster than merges in one partition |
| 394 | QUERY_WAS_CANCELLED | a user or the service canceled a query: usually noise |

nano itself classifies ClickHouse errors by code. A user sees, for 241:
`Query exceeded memory limit. Try adding more filters, reducing the time
range, or using sampling.`

## Normal noise

These appear on a healthy install and are not a cause by themselves:

- PostgreSQL at first start: `relation "public._sqlx_migrations" does not
  exist` (before the migrator has run once).
- ClickHouse at first start: `UNKNOWN_TABLE` (60), `UNKNOWN_DATABASE` (81) and
  `CACHE_DICTIONARY_UPDATE_FAIL` (510) in `system.errors` with times from the
  first minutes.
- ClickHouse `NETWORK_ERROR` (210), `ABORTED` (236), `QUERY_WAS_CANCELLED`
  (394): clients that closed a connection.
- Vector: `warning[E620]: can't abort infallible function`, `VRL compilation
  warning`, `Transform "..._unmatched" has no consumers`, and `Enabling
  acknowledgements on sources themselves is deprecated`.
- nano-search: `No admin credentials configured (CLICKHOUSE_ADMIN_USER/PASSWORD),
  using runtime user ...` on start.

## Known gaps in nano's bundle

Handle these; do not report them as the install's problem.

- nano 2.0.34 on recent Docker: for containers without a health check
  (Vector, web, the netns holder) `containers.txt` holds `template parsing
  error ... map has no entry for key "Health"` instead of restarts. Use the
  `services` recipe (the live `containers` probe) or `compose-status` (the
  `compose ps` STATUS column, such as `Restarting (78) 56 seconds ago`).
- On Compose, nano's bundle can't read Vector's metrics (`wget: not found`
  inside the Vector image). The live `vector-metrics` probe reads them through
  `nano-vector-netns`.
- Seen on 2.0.34 open edition: `postgres:audit-config-changes` fails with
  `relation "audit_logs" does not exist`. Single node:
  `clickhouse:distributed-ddl-queue` fails. Neither causes other symptoms.
- nano's redactor treats a log target whose name contains `token` followed by
  a colon as a secret key-value pair, so lines from
  `nanosiem_core::ingest_tokens` arrive as `nanosiem_core::ingest_tokens:[REDACTED]`
  with the message removed. You can still see their time and level. If
  ingest tokens matter to the problem, ask the operator to read those lines on
  the host (`docker logs nano-api 2>&1 | grep ingest_tokens`) and share them
  after checking for secrets.
- nano's bundle does not list Vector's config files. The live probe
  `vector-config-files` does (names only); bundles made without probes lack it.
