# Runbook: Vector crash loop

Vector is nano's ingest service. When it can't build its configuration it
exits, Docker or Kubernetes starts it again, and it exits again. While it
loops, every ingest port refuses connections, so senders buffer or drop.

## Symptoms

- `compose ps` shows `nano-vector  Restarting (78) N seconds ago`. Exit code 78
  is Vector's "configuration error".
- Kubernetes: the Vector pod is `CrashLoopBackOff`, with `BackOff` events.
- Senders get `connection refused` on 8088 (HEC), 8080 (HTTP), 4317/4318
  (OTLP) or 6000. Search shows no new events.
- The rest of nano is healthy: api, search and jobs answer `/health`.

## Evidence

```bash
support query --recipe vector-crash-loop
support query --recipe services
support query --recipe first-errors
```

Then read every distinct Vector error, oldest first:

```sql
SELECT min(ts) AS first, max(ts) AS last, count() AS n, target, substring(any(message), 1, 400) AS msg
FROM logs WHERE service = 'vector' AND level IN ('ERROR', 'FATAL')
GROUP BY target, replaceRegexpAll(message, '[0-9]+', '#') ORDER BY first;
```

Kubernetes: the reason is in the `--previous` log and the events:

```sql
SELECT ts, substring(message, 1, 400) FROM logs
WHERE service = 'vector' AND previous = 1 AND level IN ('ERROR', 'FATAL') ORDER BY ts;
SELECT ts, reason, object, message FROM k8s_events WHERE object ILIKE '%vector%' ORDER BY ts;
```

What the evidence means:

| Line | Cause |
|---|---|
| `Configuration error. error=Input "X" for transform "Y" doesn't match any components.` | A config file defines `Y` reading from `X`, and nothing named `X` exists (a typo, or a component that was renamed or removed). Compare `X` with the real IDs: `support query --recipe vector-components`. A near match (one letter off) proves a typo. |
| `Configuration error. error=... duplicate ...` or `...unknown variant...`, `missing field` | A file has an invalid or duplicated component. |
| `failed to parse` / `TOML parse error` | A config file is not valid TOML or YAML. |
| `Permission denied` on a config path | Vector can't read a file (often a file created with mode 0600 by another user). |
| `nano-vector: not starting Vector yet ...` | nano's entrypoint is waiting for something (the api's rendered config, the ingest gate). Read the reason after the colon. |
| `nano-vector: ERROR: nano-api has not rendered the Vector config ...` | The api never published Vector's config: see the api's own errors. |
| `nano: quarantined the source in <file> at startup` | nano set aside a log-source file it could not build. Vector keeps running without it; fix the log source in the UI. |
| `ERROR: Vector REJECTED generation N; rolling back` (vector-config-consumer) | A new config from the api failed and was rolled back. Vector keeps the previous one. |

The component names in the error (`Y` and `X`) lead to the file. On Compose,
Vector reads every file in `config/vector/` of the install (mounted read-only
at `/etc/vector`) plus the generated `dynamic/` files. A file that is not part
of nano's release is the first suspect. Bundles from `support collect` list
the files (names, sizes and times, never contents) and, on a git install, the
ones that are not part of the release:

```bash
support query --recipe vector-config-files
```

A file marked `??` (untracked) or `M` (modified), or one changed shortly
before the first `Configuration error`, is the likely culprit.

## Likely causes

1. A hand-edited or hand-added file in `config/vector/`.
2. An upgrade that left an old local file next to new built-in components
   (a renamed source).
3. A file Vector can't read (ownership or mode).
4. Out of memory at start (then the exit code is 137, not 78: see the
   ClickHouse/OOM runbook for how to read OOM kills).

## Safe fixes (ask first)

Show the operator the file and the line, then propose:

1. Find the file that defines the component (read-only, on the host):

   ```bash
   cd ~/nano && grep -rln '<component named in the error>' config/vector/
   git -C ~/nano status --short config/vector/      # git installs: files that are not part of the release
   ```

2. Move the file out of Vector's directory, keeping a copy (a change: ask):

   ```bash
   mkdir -p ~/nano-local-backup && mv ~/nano/config/vector/<file> ~/nano-local-backup/
   ```

   Or fix the typo, if the operator wants to keep the transform.

3. Vector restarts by itself within a minute (restart policy `unless-stopped`).
   Watch it, read-only:

   ```bash
   docker logs --since 3m nano-vector 2>&1 | grep -E 'Configuration error|Vector has started' | tail -3
   docker ps --filter name=nano-vector --format '{{.Names}} {{.Status}}'    # Up, not Restarting
   ```

   A new `Configuration error` names the next problem: repeat step 1. Do not
   run `vector validate` by hand on Compose: nano's files need the
   container's environment, so a bare validate fails on nano's own files and
   misleads.

4. Prove ingest works again: send one test event through the operator's
   usual sender, or run nano's smoke test, then collect a new bundle and
   confirm the `vector-crash-loop` recipe shows no new errors.

Never "fix" a crash loop by deleting `config/vector/dynamic`, the Vector data
volume (it holds the disk buffer: undelivered events), or nano's own files.

## Escalate

Escalate to nano support when the failing component is one of nano's own (it
comes from the release, not a local file), when the loop started right after
an upgrade with no local changes, or when a `vector-config-consumer` keeps
rolling back. Send:

- the bundle;
- the exact `Configuration error` line and its first time (UTC);
- `overview` output (version, edition, install type);
- whether any file in `config/vector/` was changed locally, and what.
