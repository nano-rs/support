-- nano support playbook: named queries for a loaded bundle.
--
-- Run one:   support query --recipe <name>
-- List them: support recipes
--
-- Tables: logs, k8s_events, facts, probes (see log-formats.md). JSON paths in `probes.value`
-- and `logs.fields` are Dynamic: wrap them in toString() / toInt64OrNull(toString(...)) to
-- compare or do math. Every query is read-only.

-- name: overview
-- what: Version, edition, install type, collection window, hosts reached, notes.
SELECT bundle, key, value FROM facts
WHERE key IN ('manifest.version', 'manifest.edition', 'manifest.mode', 'manifest.created_utc',
              'manifest.since_seconds', 'manifest.install_id', 'manifest.redactions', 'probes.collected_utc',
              'host.reached', 'host.error', 'manifest.note', 'host.note', 'manifest.namespace', 'manifest.release')
ORDER BY bundle, key;

-- name: services
-- what: Every container or pod: state, restarts, OOM kills, last exit code (live probe first, then the bundle).
SELECT bundle, host, source, toString(value.container) AS container, toString(value.service) AS service,
       toString(value.state) AS state, toString(value.status) AS status,
       toInt64OrNull(toString(value.restarts)) AS restarts, toString(value.oom_killed) AS oom_killed,
       toInt64OrNull(toString(value.exit_code)) AS exit_code, toString(value.health) AS health
FROM probes WHERE name = 'containers'
ORDER BY restarts DESC NULLS LAST, source DESC;

-- name: compose-status
-- what: The `docker compose ps` table from the bundle: Restarting (N) or Exited (N) is the exit code.
-- (Aliases never reuse a column name: in ClickHouse an alias shadows the column in WHERE.)
SELECT bundle, host, toString(value.NAME) AS container, toString(value.SERVICE) AS service,
       toString(value.STATUS) AS status
FROM probes WHERE name = 'compose:compose ps'
ORDER BY (status ILIKE 'Restarting%' OR (status ILIKE 'Exited (%' AND status NOT ILIKE 'Exited (0)%')) DESC, container;

-- name: health
-- what: Health endpoints asked from inside the containers (live probes).
SELECT bundle, host, toString(value.service) AS service, toString(value.url) AS url,
       toString(value.ok) AS healthy, substring(toString(value.detail), 1, 160) AS detail
FROM probes WHERE name = 'health' ORDER BY healthy, service;

-- name: error-clusters
-- what: Warnings and errors grouped by shape (numbers and ids folded), biggest first.
SELECT service, level, count() AS n, min(ts) AS first_seen, max(ts) AS last_seen,
       any(target) AS target, substring(any(message), 1, 300) AS example
FROM logs
WHERE level IN ('ERROR', 'FATAL', 'WARN')
GROUP BY service, level, replaceRegexpAll(message, '[0-9a-fA-F]{8,}|[0-9]+', '#') AS shape
ORDER BY n DESC LIMIT 40;

-- name: first-errors
-- what: The first ERROR or FATAL line of each service: the earliest one is usually the cause.
SELECT service, min(ts) AS first_error, argMin(substring(message, 1, 300), ts) AS msg,
       argMin(target, ts) AS target, count() AS errors
FROM logs WHERE level IN ('ERROR', 'FATAL') AND ts IS NOT NULL
GROUP BY service ORDER BY first_error;

-- name: timeline
-- what: Errors and warnings per service in 5-minute buckets.
SELECT toStartOfFiveMinutes(ts) AS t, service, countIf(level IN ('ERROR', 'FATAL')) AS errors,
       countIf(level = 'WARN') AS warnings, count() AS lines
FROM logs WHERE ts IS NOT NULL
GROUP BY t, service HAVING errors + warnings > 0 ORDER BY t, service;

-- name: around
-- what: Every log line within 2 minutes of the first FATAL/ERROR that is not known start-up noise.
WITH (SELECT min(ts) FROM logs WHERE level IN ('ERROR', 'FATAL')
        AND message NOT ILIKE '%_sqlx_migrations" does not exist%'
        AND message NOT ILIKE '%UNKNOWN_TABLE%' AND message NOT ILIKE '%UNKNOWN_DATABASE%'
        AND message NOT ILIKE '%CACHE_DICTIONARY_UPDATE_FAIL%') AS t0
SELECT ts, service, level, target, substring(message, 1, 240) AS msg
FROM logs WHERE ts BETWEEN t0 - INTERVAL 2 MINUTE AND t0 + INTERVAL 2 MINUTE
ORDER BY ts LIMIT 300;

-- name: restarts-oom
-- what: Restarts, OOM kills (exit 137, signal 9, OOM killer) from probes and from log text.
SELECT 'container' AS evidence, host, toString(value.container) AS what,
       concat('restarts=', toString(value.restarts), ' oom_killed=', toString(value.oom_killed),
              ' exit=', toString(value.exit_code)) AS detail
FROM probes WHERE name = 'containers'
  AND (toInt64OrZero(toString(value.restarts)) > 0 OR toString(value.oom_killed) = 'true'
       OR toInt64OrZero(toString(value.exit_code)) IN (137, 139))
UNION ALL
SELECT 'log', host, service, concat(toString(ts), '  ', substring(message, 1, 240))
FROM logs WHERE message ILIKE '%OOM%' OR message ILIKE '%signal 9%' OR message ILIKE '%Killed process%'
             OR message ILIKE '%out of memory%' OR message ILIKE '%MEMORY_LIMIT_EXCEEDED%'
UNION ALL
SELECT 'kernel', host, name, substring(text, 1, 400)
FROM probes WHERE name = 'kernel-oom' AND text ILIKE '%kill%';

-- name: vector-config-files
-- what: Vector's config files (names, sizes, times; never contents) and the ones not part of the release.
SELECT * FROM (
  SELECT 'local change' AS kind, toString(value.status) AS status, toString(value.path) AS path,
         '' AS modified_utc, '' AS bytes
  FROM probes WHERE name = 'vector-config-local-changes'
  UNION ALL
  SELECT 'file', '', toString(value.path), toString(value.modified_utc), toString(value.bytes)
  FROM probes WHERE name = 'vector-config-files'
) ORDER BY kind DESC, modified_utc DESC;

-- name: vector-components
-- what: Component IDs Vector knew when it last started (live topology, or the ids in its own log lines).
SELECT 'topology' AS seen_in, toString(value.component_id) AS component_id, toString(value.kind) AS kind
FROM probes WHERE name LIKE 'vector-topology%' AND toString(value.component_id) != ''
UNION ALL
SELECT DISTINCT 'log', extract(message, 'component_id="([^"]+)"'), ''
FROM logs WHERE service = 'vector' AND message LIKE '%component_id="%';

-- name: vector-crash-loop
-- what: Is Vector restarting, and why? Exit 78 is a configuration error; the log line names the file's component.
SELECT 'state' AS evidence, toString(value.container) AS what,
       concat(toString(value.status), ' restarts=', toString(value.restarts), ' exit=', toString(value.exit_code)) AS detail
FROM probes WHERE name = 'containers' AND toString(value.container) ILIKE '%vector%'
UNION ALL
SELECT 'compose ps', toString(value.NAME), toString(value.STATUS)
FROM probes WHERE name = 'compose:compose ps' AND toString(value.SERVICE) ILIKE 'vector%'
UNION ALL
SELECT 'log', target, concat(toString(min(ts)), ' .. ', toString(max(ts)), '  x', toString(count()), '  ',
       substring(any(message), 1, 300))
FROM logs
WHERE service IN ('vector', 'vector-config-consumer')
  AND (message ILIKE '%Configuration error%' OR message ILIKE '%failed to load%' OR message ILIKE '%not starting Vector%'
       OR message ILIKE '%quarantined%' OR message ILIKE '%REJECTED generation%' OR message ILIKE '%rolling back%'
       OR message ILIKE '%error[E%' OR level IN ('ERROR', 'FATAL'))
GROUP BY target, replaceRegexpAll(message, '[0-9]+', '#')
UNION ALL
SELECT 'api', toString(value.service), concat(toString(value.ok), ' ', toString(value.detail))
FROM probes WHERE name = 'health' AND toString(value.url) LIKE '%8686%';

-- name: ingest-drops
-- what: Signs that events are refused, dropped or not delivered: Vector state, errors and discard counters.
SELECT 'vector metric' AS evidence, toString(value.metric) AS what,
       concat(toString(value.labels.component_id), ' ', toString(value.labels.error_type), ' = ',
              toString(value.value)) AS detail
FROM probes
WHERE (name LIKE 'vector%metrics%' OR name = 'vector-metrics' OR name LIKE 'vector/%')
  AND toString(value.metric) REGEXP '(discarded|errors_total|buffer_discarded)' AND toFloat64OrZero(toString(value.value)) > 0
UNION ALL
SELECT 'log', service, concat(toString(min(ts)), ' x', toString(count()), '  ', substring(any(message), 1, 260))
FROM logs
WHERE message ILIKE '%Events dropped%' OR message ILIKE '%discarded%' OR message ILIKE '%not starting Vector%'
   OR message ILIKE '%ingest token%' OR message ILIKE '%Connection refused%' OR message ILIKE '%backpressure%'
   OR message ILIKE '%buffer%full%' OR message ILIKE '%Healthcheck failed%' OR message ILIKE '%refused events%'
   OR message ILIKE '%ingest gate%'
GROUP BY service, replaceRegexpAll(message, '[0-9]+', '#')
UNION ALL
SELECT 'http status', service, concat(toString(fields.status), ' x', toString(count()))
FROM logs WHERE target = 'access' AND toInt64OrZero(toString(fields.status)) >= 400
GROUP BY service, toString(fields.status);

-- name: ch-errors
-- what: ClickHouse errors by code from system.errors (bundle and live), newest first.
SELECT host, name AS source, toString(value.name) AS error, toInt64OrNull(toString(value.code)) AS code,
       toString(value.value) AS times, toString(value.last_error_time) AS last_time,
       substring(toString(value.last_error_message), 1, 200) AS msg
FROM probes WHERE name LIKE 'clickhouse%errors-recent' OR name LIKE 'ch-errors%'
ORDER BY last_time DESC LIMIT 60;

-- name: ch-codes-in-logs
-- what: ClickHouse codes quoted anywhere in the logs (117 bad data, 202 too many queries, 241 memory, 243 disk, 252 parts).
SELECT extract(message, 'Code: ([0-9]+)') AS code, service, count() AS n, min(ts) AS first_seen, max(ts) AS last_seen,
       substring(any(message), 1, 260) AS example
FROM logs WHERE message LIKE '%Code: %'
GROUP BY code, service ORDER BY toInt32OrZero(code) IN (117, 202, 241, 243, 252) DESC, n DESC;

-- name: ch-query-failures
-- what: query_log totals by error code and user (no query text is ever collected).
SELECT toInt64OrNull(toString(value.exception_code)) AS code, toString(value.error_name) AS error,
       toString(value.query_kind) AS kind, toString(value.user) AS user, toString(value.queries) AS queries,
       toString(value.first_seen) AS first_seen, toString(value.last_seen) AS last_seen
FROM probes WHERE name LIKE 'ch-query-log-exceptions%' ORDER BY toInt64OrZero(toString(value.queries)) DESC;

-- name: slow-queries
-- what: Slowest query shapes by p95 (hash only, no text) and the hourly picture.
SELECT toString(value.normalized_query_hash) AS shape, toString(value.query_kind) AS kind, toString(value.user) AS user,
       toInt64OrNull(toString(value.queries)) AS queries, toInt64OrNull(toString(value.p95_ms)) AS p95_ms,
       toInt64OrNull(toString(value.max_ms)) AS max_ms, toString(value.max_read_rows) AS max_read_rows,
       formatReadableSize(toFloat64OrZero(toString(value.max_memory))) AS max_memory, toString(value.failed) AS failed
FROM probes WHERE name LIKE 'ch-query-log-slowest-shapes%' ORDER BY p95_ms DESC LIMIT 20;

-- name: too-many-parts
-- what: Active parts per table and per partition, merges running, and the insert limits.
(SELECT name AS source, toString(value.database) AS db, toString(value.table) AS tbl,
       toString(value.partition) AS part_key, toInt64OrNull(toString(value.active_parts)) AS active_parts
 FROM probes WHERE name LIKE 'clickhouse%parts%' OR name LIKE 'ch-parts%'
 ORDER BY active_parts DESC NULLS LAST LIMIT 20)
UNION ALL
SELECT name, toString(value.name), toString(value.value), '', NULL
FROM probes WHERE name LIKE 'ch-merge-tree-settings%'
UNION ALL
SELECT name, toString(value.database), toString(value.table), concat('merge ', toString(value.elapsed_s), 's'), NULL
FROM probes WHERE (name LIKE 'clickhouse%merges' OR name LIKE 'ch-merges%') AND text = '';

-- name: disk
-- what: Free space everywhere it was measured: host filesystems, ClickHouse disks, data directories.
SELECT name AS source, toString(value.mounted_on) AS path, toString(value.use_pct) AS used_pct,
       formatReadableSize(toFloat64OrZero(toString(value.available))) AS free
FROM probes WHERE name = 'disk-free' AND toString(value.mounted_on) NOT LIKE '/proc%'
UNION ALL
SELECT name, toString(value.path), toString(value.used_pct), toString(value.free)
FROM probes WHERE name LIKE 'clickhouse%:disks'
UNION ALL
SELECT name, toString(value.path), '', toString(value.free)
FROM probes WHERE name LIKE 'disk:data directories%'
UNION ALL
SELECT 'text', host, '', substring(text, 1, 500) FROM probes WHERE name = 'disk:df -hT';

-- name: migrations
-- what: Migration state (PostgreSQL _sqlx_migrations, ClickHouse _migrations) and migrator or boot errors.
SELECT name AS source, '' AS service, toString(value) AS detail
FROM probes WHERE name IN ('postgres:migrations', 'pg-migrations-failed', 'pg-migrations-recent', 'ch-migrations-recent')
UNION ALL
SELECT 'log', service, concat(toString(ts), '  ', substring(message, 1, 300))
FROM logs
WHERE message ILIKE '%Refusing to start%' OR message ILIKE '%schema is behind%' OR message ILIKE '%migration lock%'
   OR message ILIKE '%migration failed%' OR message ILIKE '%schema migration failed%'
   OR ((service = 'migrate' OR container ILIKE '%migrate%') AND level IN ('ERROR', 'FATAL', 'WARN'));

-- name: license
-- what: Cached license state, grace period and the license checker's own log lines.
SELECT 'state' AS evidence, toString(value.state) AS state, toString(value.valid) AS valid,
       toString(value.grace_ends_at) AS grace_ends_at, toString(value.locked_reason) AS locked_reason,
       toString(value.last_checked_at) AS last_checked
FROM probes WHERE name = 'pg-licensing-state'
UNION ALL
SELECT 'log', level, toString(ts), '', substring(message, 1, 300), target
FROM logs WHERE target ILIKE '%license%' OR message ILIKE '%license%' OR message ILIKE '%LICENSE_REQUIRED%'
UNION ALL
SELECT 'config', key, value, '', '', '' FROM facts WHERE key IN ('env.NANO_LICENSE_MODE', 'release.NANO_LICENSE_MODE',
       'env.LICENSE_URL', 'env.AIRGAP_MODE', 'env.NANO_DEPLOYMENT_ID');

-- name: auth-sso
-- what: Sign-in failures: OIDC/SSO errors, group admission, rate limits, 401/403 answers.
SELECT service, level, count() AS n, min(ts) AS first_seen, max(ts) AS last_seen,
       substring(any(message), 1, 300) AS example
FROM logs
WHERE message ILIKE '%OIDC%' OR message ILIKE '%SSO%' OR message ILIKE '%sign-in%' OR message ILIKE '%login%'
   OR message ILIKE '%JWKS%' OR message ILIKE '%issuer%' OR message ILIKE '%redirect uri%' OR message ILIKE '%nonce%'
   OR message ILIKE '%state parameter%' OR (target = 'access' AND toInt64OrZero(toString(fields.status)) IN (401, 403, 429))
GROUP BY service, level, replaceRegexpAll(message, '[0-9]+', '#') ORDER BY n DESC LIMIT 30;

-- name: hunts-held
-- what: Hunt sweeps that were held, and the telemetry readiness reason.
SELECT ts, service, substring(message, 1, 400) AS msg
FROM logs WHERE message ILIKE '%hunt sweep held%' OR message ILIKE '%Can''t run yet%' OR message ILIKE '%Held:%'
   OR message ILIKE '%Waiting for recon%' OR message ILIKE '%telemetry readiness%'
ORDER BY ts;

-- name: ai-provider
-- what: AI provider errors: rejected keys, missing models, rate limits, timeouts, unreachable endpoints.
SELECT service, level, count() AS n, min(ts) AS first_seen, max(ts) AS last_seen,
       substring(any(message), 1, 300) AS example
FROM logs
WHERE target ILIKE '%melod%' OR target ILIKE '%ai_%' OR message ILIKE '%AI provider%' OR message ILIKE '%AI Gateway%'
   OR message ILIKE '%AI endpoint%' OR message ILIKE '%Model not available%' OR message ILIKE '%Rate limit exceeded%'
   OR message ILIKE '%tool calling%' OR message ILIKE '%meloD%' OR message ILIKE '%Provider health check failed%'
GROUP BY service, level, replaceRegexpAll(message, '[0-9]+', '#') ORDER BY n DESC LIMIT 30;

-- name: k8s-warnings
-- what: Kubernetes Warning events (BackOff, OOMKilled, FailedScheduling, probes failing), newest first.
SELECT ts, reason, object, substring(message, 1, 260) AS msg
FROM k8s_events WHERE type = 'Warning' ORDER BY ts DESC NULLS LAST LIMIT 100;

-- name: postgres
-- what: PostgreSQL health: connections by state, waiting locks, deadlocks, dead tuples.
SELECT name AS source, toString(value) AS detail FROM probes
WHERE name IN ('pg-stat-database', 'pg-connections', 'pg-max-connections', 'pg-locks-waiting', 'pg-database-size',
               'postgres:activity', 'postgres:long-running', 'postgres:replication')
ORDER BY source;

-- name: config-keys
-- what: Configuration key names and non-secret values from .env (secret values are already [REDACTED]).
SELECT host, key, value FROM facts WHERE key LIKE 'env.%' ORDER BY key;
