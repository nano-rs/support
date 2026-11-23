# What is and isn't collected

A `support collect` file holds two parts:

- `bundle/nano-support-*.tar.gz`: nano's own support bundle, exactly as
  `scripts/nano support-bundle` wrote it. Its redaction and its rules are
  nano's, for the release that is installed.
- `probes/probes.json`: the optional live probes from this tool, passed
  through the same redaction (nano's `Redactor`, loaded from the install).
  On Compose the install's `.env` secret values are added, on Kubernetes the
  release namespace's Secret values (in memory only; skipped, and recorded as
  `redaction-seed` failed, when kubectl may not read Secrets). Every Secret
  value is seeded except under known non-secret keys (user names, hosts,
  ports, database, bucket and region names); a URL gives its password (or the
  whole URL when it has none, such as a webhook), a JSON value such as
  `.dockerconfigjson` gives each string (and `auth` its decoded password), and
  a multi-line value (a private key, `users.xml`, `config.yaml`) gives each
  line or each line's value. Quoted
  literals in ClickHouse and PostgreSQL error text are removed.

`SUPPORT-MANIFEST.json` lists both.

## nano's bundle

Collected (see `README.md` inside the bundle for the release's own list):

- versions, the edition, image locks and the install ID;
- host facts: OS, CPU, memory, time sync, clock skew between hosts, disk use,
  and whether each data directory is its own mount;
- service state, health, restarts and out-of-memory kills;
- cluster health and HA roles (Patroni, etcd, Sentinel, Valkey, HAProxy) on a
  role split;
- ClickHouse diagnostics: recent `system.errors`, replication, read-only
  replicas, parts, disks, mutations, dictionaries;
- Vector component errors and buffer metrics;
- the nano services' own logs for the window, size-capped. Logs of the ingest
  data plane (Vector, ClickHouse, Tenzir, connector runner) keep warning and
  error lines only, with event fragments removed. In nano's own service logs,
  quoted SQL literals and search text in request URIs are removed;
- recent configuration changes: time, action and object only;
- on Kubernetes: pods, events, `describe` output, logs and the Helm values
  with secrets removed;
- the names of configuration settings. Secret values are replaced.

Never collected: event data, raw logs that sources sent to nano, search or
query results, lookup or IOC contents, secret values, private keys, license
files. The `vector-tap` service is skipped because it prints sampled events.

## Live probes

All read-only. Each runs with a timeout. A probe that fails is recorded as
failed, and the rest still run.

| Probe | What it reads | Never |
|---|---|---|
| `containers` | `docker inspect` (or `kubectl get pods`): state, restarts, OOM kill, exit code, health, memory limit, restart policy | environment variables, mounts' contents |
| `health` | nano-api `/health` and `/ready`, nano-search `/health` and `/ready`, nano-jobs `/health`, Vector API `/health` (from inside the containers) | authenticated endpoints |
| `vector-topology` | Vector's local GraphQL API: component IDs and types | events, `vector tap` output |
| `vector-metrics` | Vector's Prometheus metrics, filtered by nano's own filter (errors, discards, buffers, throughput) | event samples |
| `ch-parts-by-partition`, `ch-merges`, `ch-mutations`, `ch-errors`, `ch-disks`, `ch-memory`, `ch-settings`, `ch-merge-tree-settings` | ClickHouse `system` tables | table data |
| `ch-query-log-by-hour`, `ch-query-log-slowest-shapes`, `ch-query-log-exceptions` | `system.query_log` totals by hour, user, query kind, error code and `normalized_query_hash` | **query text** (no `query` or `formatted_query` column is read) |
| `ch-migrations-recent` | the last 15 rows of nano's ClickHouse `_migrations` ledger | |
| `pg-migrations-recent`, `pg-migrations-failed` | `_sqlx_migrations` version, description, success, time | |
| `pg-stat-database`, `pg-connections`, `pg-locks-waiting`, `pg-tables-dead-tuples`, `pg-database-size`, `pg-max-connections` | `pg_stat_*` summaries | **query text** (`pg_stat_activity.query` is never read) |
| `pg-licensing-state` | the cached license state row: state, valid, tier, locked reason, grace end, expiry, last check | the license token, the raw license response |
| `disk-free`, `inodes-free`, `memory` | `df`, `/proc/meminfo` | |
| `kernel-oom` | kernel log lines about the OOM killer (names of killed processes) | other kernel messages |

## Redaction you can check

- `support check FILE --bundle-tool PATH` re-runs nano's redactor over every
  line and lists any line it would still change.
- Redaction is pattern-based. Logs can still name hosts, IP addresses and user
  names. The preview counts them so the operator can decide.
