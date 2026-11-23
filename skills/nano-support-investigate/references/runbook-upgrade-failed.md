# Runbook: an upgrade failed

On Compose, nano upgrades with `scripts/nano upgrade --bundle <bundle>` (from
v2.0.10), or by re-running `install.sh` (older releases and the open
edition). On Kubernetes, with `helm upgrade`. Every upgrade runs the new
schema migrations first and starts the new app services only after they
succeed. Migrations are forward-only: roll forward, don't downgrade across a
schema change. The public guide is
[Upgrade a self-hosted deployment](https://nano.rs/docs/releases/upgrading/).

## Symptoms

- `scripts/nano upgrade` printed `Upgrade stopped safely. Journal: ...`, or
  `preflight failed; no installation state was changed`.
- `install.sh` stopped with a line starting with `✗`.
- After the upgrade some services run the new version and some the old, or a
  service won't start (`Refusing to start`).
- `helm upgrade` timed out, or a migration hook failed.

## Evidence

Ask the operator for the upgrade's own output first (the last 40 lines). It
prints each step as `==> <time> <step>: started` and `done in <N>s`, and on
failure `==> <time> <step>: FAILED after <N>s`. The preflight prints a table
`RESULT HOST CHECK DETAIL` with a summary `Preflight: N/M PASS; K FAIL`.
Every step is also in `~/nano/upgrade-journal/` (no secrets; the operator can
share it).

Then the bundle:

```bash
support query --recipe overview          # version now recorded in .env
support query --recipe services          # who restarted or exited
support query --recipe migrations        # did the migrator finish?
support query --recipe first-errors
```

Mixed versions (image per container):

```sql
SELECT toString(value.container) AS container, toString(value.image) AS image FROM probes
WHERE name = 'containers' ORDER BY container;
SELECT toString(value) FROM probes WHERE name LIKE 'release:container images%';
```

| Message | Meaning |
|---|---|
| `preflight failed; no installation state was changed` | a check failed before anything changed: fix that check, run again |
| preflight `FAIL` on `disk`, `ram`, `cpu`, `ntp` | the host is below the release's floor or its clock is off |
| preflight `FAIL` on `registry-login` / `registry-pull` | the registry credential expired or is missing (from v2.0.30 an online license logs in itself) |
| `C05 license state is missing or expired` / `C05 cached license is not active and unexpired` | the dry run refused because of license state: contact nano support, never bypass |
| `Upgrade stopped safely. Journal: ...` + `run: scripts/nano upgrade --bundle <same-bundle> --resume` | it stopped partway and the previous version keeps running: fix the cause, then `--resume` |
| `Image digest verification failed: pulled images do not match images.lock. Refusing to start` | the pulled images are not the signed release: never skip verification |
| `Rollback complete: X -> Y` | a rollback finished |
| `rollback preflight failed; no installation state was changed` | the rollback refused before changing anything |

## Likely causes

1. A preflight check (disk, memory, registry login, senders not paused).
2. A migration failure: follow [runbook-migrations-stuck.md](runbook-migrations-stuck.md).
3. A new requirement of the release (from v2.0.30, Vector native senders on
   port 6000 need client certificates; read the release notes between the
   two versions).
4. A service that fails after the upgrade: follow the matching runbook
   (Vector crash loop is common after an upgrade with local Vector files).

## Safe fixes (ask first)

- Fix the reported cause, then run the same command again, with `--resume` if
  the upgrade told you to. Re-running is safe: it keeps `.env`, secrets and
  data.
- Pass the same bundle. Do not mix bundles of different versions.
- Never use `--skip-backup-I-understand`, `--allow-siem-health-regression`,
  `NANO_SKIP_IMAGE_VERIFY=1` or `NANO_SKIP_HOST_MINIMUMS=1` to get past a
  failure, and never hand-edit compose files or downgrade images across a
  schema change.
- A rollback (`scripts/nano rollback`) is a change with its own "yes": read
  the upgrade guide's rollback section with the operator first.

## Escalate

Escalate on a C05 license refusal, on a migration failure, when `--resume`
fails twice for the same reason, or when a rollback refuses. Send:

- the bundle (collected after the failure, before any restart if possible);
- the version from and to, and the install type;
- the upgrade's last 40 lines and the journal folder;
- the time (UTC) and what was tried.
