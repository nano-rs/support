# Runbook: events are not arriving

Events go from a sender to Vector (nano's ingest service), then to
ClickHouse. "Not arriving" means one of three things: the sender is refused,
Vector accepts but can't deliver, or events arrive but don't look like what
the operator searches for.

## Symptoms

- Search shows no new events for a source, or SIEM Health warns that a source
  is quiet.
- Senders log `connection refused`, `401`, `403`, `413`, `415`, `429` or `503`.
- Hunts report "Can't run yet: ... stopped arriving" (see the hunts runbook).

## Evidence

```bash
support query --recipe services          # is Vector running, restarting, OOM-killed?
support query --recipe health            # Vector API /health from vector-netns
support query --recipe ingest-drops      # discards, errors, refusals
support query --recipe vector-crash-loop
support query --recipe ch-errors         # ClickHouse refusing inserts (252, 243, 241)
```

Vector's error and discard counters (live probe):

```sql
SELECT toString(value.metric) AS metric, toString(value.labels.component_id) AS component,
       toString(value.labels.error_type) AS error_type, toFloat64OrZero(toString(value.value)) AS v
FROM probes WHERE name = 'vector-metrics' AND v > 0
  AND toString(value.metric) REGEXP 'errors_total|discarded|buffer_byte_size|buffer_events'
ORDER BY v DESC LIMIT 40;
```

What the answers mean:

| Sender sees / evidence | Meaning |
|---|---|
| `connection refused` on every port, Vector `Restarting` | Vector is down: [runbook-vector-crash-loop.md](runbook-vector-crash-loop.md). |
| `nano-vector: not starting Vector yet ...` | nano is holding Vector until a condition clears (its reason follows the colon). |
| `503` with `Retry-After` and `Ingest is closed for a few seconds while nano restarts its collector; retry` | `scripts/nano` closed ingest while it restarts Vector (an upgrade, restore or backup). It reopens by itself; senders retry. |
| `503` with `Retry-After` and `Ingestion is paused` | Ingest is paused on purpose (for example at the disk pressure emergency level, when that pause is on). Find why in Settings and SIEM Health. |
| `403` on `/ingest` with a valid token | The ingest admission check refused it: ingest is paused for this install, or an IP allowlist blocks the sender. |
| `401` / `403` | The ingest token is wrong, revoked or not yet published. A new token can take about 10 seconds to work. nano-api logs `ingest token publication failed` when publication itself fails. |
| `413` | The request is larger than the ingest edge allows. Senders must send smaller batches (see the HEC guide for the limit on your release). |
| `415` on `/otlp/v1/...` | OTLP over HTTP accepts binary protobuf only. Set the sender to `http/protobuf`. |
| `429` | A rate limit: per HEC credential, per client or per node. Senders must retry with backoff. |
| `404` on `/services/collector` | Splunk HEC is served on port 8088 only: use `/services/collector/event` (or `/raw`) there. On a single host, port 80/443 serves HTTP ingest (`/ingest`) and OTLP over HTTP (`/otlp/v1/logs`, `traces`, `metrics`) with an ingest token, but not HEC. |
| `component_discarded_events_total` or `buffer_discarded_events_total` above 0 | Vector dropped events after accepting them. SIEM Health calls it `Vector discarded events after accepting them`. |
| `component_errors_total` on a ClickHouse sink, plus Code 252 / 243 / 241 in `ch-errors` | ClickHouse refuses inserts: [runbook-clickhouse-disk-oom-parts.md](runbook-clickhouse-disk-oom-parts.md). Vector's disk buffer holds the events (it blocks when full, so senders see backpressure). |
| No errors anywhere, health fine | The events arrive but are not where the operator looks: wrong source type, a parser that sends them to the unparsed path, or timestamps in the future or past. Ask for the source slug and one redacted sample event. |

## Likely causes

1. Vector is down or restarting.
2. The sender uses a wrong port, path, protocol or token.
3. ClickHouse refuses inserts (disk, parts, memory).
4. A firewall between the sender and nano (outside nano: the bundle can't see
   it; `connection timed out`, not `refused`, points there).

## Safe fixes (ask first)

- Vector down: follow the Vector runbook.
- Token: create a new ingest token in nano's UI and update the sender. Do not
  copy tokens into chat.
- Size or protocol: change the sender's batch size or exporter protocol.
- ClickHouse refusing: follow the ClickHouse runbook. Do not delete Vector's
  data volume: its disk buffer holds events that are not delivered yet.

Public guides: [HEC troubleshooting](https://nano.rs/docs/integrations/hec/),
[Set up your first feed](https://nano.rs/docs/getting-started/first-feed/),
[Windows, Linux and firewall collection](https://nano.rs/docs/integrations/on-premise-collection/).

## Escalate

When Vector is healthy, ClickHouse accepts inserts, the sender gets 200s and
the events still can't be found. Send:

- the bundle;
- the source slug, the sender and its version, the protocol and port;
- one representative raw event with private data removed;
- whether the request was accepted (status code) and the time (UTC).
