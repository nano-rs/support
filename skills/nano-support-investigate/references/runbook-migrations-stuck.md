# Runbook: migrations stuck or failed

nano keeps its schema in two places: PostgreSQL (`_sqlx_migrations`) and
ClickHouse (`nanosiem._migrations`). On Compose, the one-shot
`nano-clickhouse-migrate` container applies the PostgreSQL migrations first,
then ClickHouse's, then exits 0. The api, search and jobs services refuse to
start while either schema is behind their binary.

## Symptoms

- api, search or jobs restart in a loop, or never become healthy, after an
  install or upgrade.
- Their logs say `Refusing to start: ...`, for example `Refusing to start:
  PostgreSQL schema is behind`, or `ClickHouse schema is behind: ...`.
- `nano-clickhouse-migrate` exited non-zero, or runs for a long time.

## Evidence

```bash
support query --recipe migrations
support query --recipe services
support query --recipe first-errors
```

The migrator's own story, in order:

```sql
SELECT ts, level, substring(message, 1, 300) AS msg FROM logs
WHERE container ILIKE '%migrate%' AND (level IN ('ERROR', 'FATAL', 'WARN')
   OR message ILIKE '%migration%' OR message ILIKE '%Applying%' OR message ILIKE '%lock%')
ORDER BY ts;
```

| Line | Meaning |
|---|---|
| `Starting ClickHouse schema migration` ... `ClickHouse schema migration complete` | a normal run |
| `Another migrator holds the cluster migration lock; waiting` (repeats with `waited_secs`) | another migrator run holds the lock: waiting, not failed |
| `PostgreSQL not accepting connections yet; retrying the migration lock connect` | PostgreSQL is down or still starting |
| `ClickHouse schema migration failed: ...` | a migration failed: the text after the colon is the reason |
| `Applying ClickHouse migration: <name>` as the last line, nothing after | it is still running (a large table change) or it was killed: check restarts and OOM |
| `PostgreSQL schema is behind this binary: ... migration <N> (...) is not applied; run clickhouse_migrator` (from api/search/jobs) | the services are newer than the schema: the migrator did not finish |
| `Code: 202 ... TOO_MANY_SIMULTANEOUS_QUERIES` during migration | the migrator retries this by itself |

Probes: `pg-migrations-failed` lists any PostgreSQL migration with
`success = false`; `postgres:migrations` gives `applied`, `head` and
`failed`; `ch-migrations-recent` the last ClickHouse migrations applied.

## Likely causes

1. ClickHouse or PostgreSQL was down or out of memory during the migration
   (check `restarts-oom`, `disk`).
2. Two migrators at once (role split: several app hosts upgraded at the same
   time): one waits for the other's lock.
3. A migration failed on data it did not expect (the error names it).
4. Disk full during a large table change.

## Safe fixes (ask first)

- Fix the cause first (memory, disk, a database that is down).
- Then re-run the migrator the way nano's install does it: on Compose,
  re-run `install.sh` (or `scripts/nano upgrade --resume` if an upgrade
  stopped), which starts `clickhouse-migrate` again. Migrations are
  idempotent: applied ones are skipped (`already applied, skipping`).
- While a migrator waits for the lock, let it wait. Do not kill it.
- Never mark a migration as applied by hand, edit `_sqlx_migrations` or
  `_migrations`, or drop tables to get past a failure. That breaks later
  upgrades.

## Escalate

Escalate when a migration fails with a schema or data error, when the lock
wait does not end after the other run has finished, or when a migration that
ran before fails after an upgrade. Send:

- the bundle;
- the version before and after (from `overview` and the upgrade output);
- the migrator's last 40 lines (from the query above) and the time (UTC);
- the `pg-migrations-failed` and `ch-migrations-recent` rows.
