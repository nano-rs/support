# Runbook: hunts held, or telemetry not ready

A hunt checks that the data it needs is arriving before it runs a sweep (its
"telemetry readiness"). When it can't confirm that, nano holds the sweep: it
records the run as finished with outcome `held`, runs no queries and spends
no AI budget. The public guide is
[Troubleshoot hunts](https://nano.rs/docs/hunts/troubleshooting/).

## Symptoms

- A hunt's sweeps show `Held: nano couldn't confirm this hunt's data sources,
  so the sweep didn't run.`
- Or `Held: nano couldn't check this hunt's data sources just now, so the
  sweep didn't run. It will try again on the next run.`
- A hunt shows "Can't run yet: ...", or a run ends with `no_coverage`.

## Evidence

```bash
support query --recipe hunts-held
support query --recipe ingest-drops      # is the data arriving at all?
support query --recipe ch-errors         # could the readiness probe query ClickHouse?
```

| Message | Meaning | What to do |
|---|---|---|
| `Can't run yet: you don't have a source for <label>. This hunt needs <needs>.` | No log source sends the data this hunt reads. | Add a log source for it. |
| `Can't run yet: <label> stopped arriving.` + `The last event from <sources> was N hours ago.` or `Nothing arrived from <sources> in the last N days.` | The source exists but has gone quiet. | Treat it as an ingest problem: [runbook-ingest-not-arriving.md](runbook-ingest-not-arriving.md). |
| `Can't run yet: confirm that <subject> sends <label>. nano matched it by its name only ...` | nano guessed the source from its name and won't rely on it until a person confirms. | Confirm it in Coverage. |
| `Waiting for recon to map your sources: ...` | Recon hasn't checked which sources send this data yet. | Run recon. |
| `hunt sweep held: telemetry readiness probe failed` (jobs log, WARN) | The readiness check itself failed (often ClickHouse busy or down). The next run retries. | Check ClickHouse health. |
| `no_coverage`: "No pivot could run: the sources this hunt needs are not present in the window" | None of the hunt's sources had data in the window. | Check those sources' ingestion. |

The `jobs` service runs hunts. Read its warnings and errors around the held
run:

```sql
SELECT ts, level, substring(message, 1, 400) FROM logs
WHERE service = 'jobs' AND (target ILIKE '%hunt%' OR message ILIKE '%hunt%') ORDER BY ts DESC LIMIT 50;
```

## Likely causes

1. A source stopped sending (the most common case).
2. A source was never added or never confirmed.
3. ClickHouse was briefly unavailable when the readiness probe ran.

## Safe fixes (ask first)

- Fix ingest for the quiet source, add the missing source, confirm the
  source in Coverage, or run recon. All are done in nano's UI by the
  operator.
- Do not turn off the readiness check or edit hunt rows in the database.

## Escalate

Escalate when the source is arriving (events are searchable within the hunt's
window) and sweeps are still held, or when `telemetry readiness probe failed`
repeats while ClickHouse is healthy. Send:

- the bundle;
- the hunt ID, the run ID and the time with time zone;
- the source name and a search showing its recent events (count only).
