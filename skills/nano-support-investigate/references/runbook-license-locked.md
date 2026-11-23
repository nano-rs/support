# Runbook: license in grace or locked

nano Self-run checks its license with nano's license service (online), or
uses an imported license file (offline and air-gapped). The license has three
states: `active`, `grace_period` (licensed features keep working for a while,
for example 7 days after a cancellation) and `locked` (the hard stop).

At the hard stop, licensed features answer HTTP 403 with code
`LICENSE_REQUIRED`: "This licensed feature is unavailable at the license hard
stop. Open/core features and stored data remain available." Events keep
being stored and searched. Nothing is deleted.

## Symptoms

- A license banner in the UI; licensed pages or actions fail with 403
  `LICENSE_REQUIRED`.
- The deployment on app.nano.rs shows no recent check-in.
- Hunts report "the license hard stop suspends the hunts lane".

## Evidence

```bash
support query --recipe license
support query --recipe overview
```

| Evidence | Meaning |
|---|---|
| `pg-licensing-state` `state = grace_period`, `grace_ends_at` set | in grace until that time |
| `state = locked`, `locked_reason` | the hard stop, and why |
| `License check failed (will retry next interval)` with a network error | nano can't reach the license service: egress, proxy or DNS |
| `License token rejected (will retry next interval)` | the license service refused the token: regenerated, wrong deployment, or billing |
| `Incomplete online license configuration; failing closed` | `LICENSE_URL`, `LICENSE_TOKEN` or `NANO_DEPLOYMENT_ID` is missing |
| `Failed to load cached license status; failing closed` | the cached state in PostgreSQL can't be read |
| `Initial online license check failed; using only a previously successful bounded cache` | a start without reaching the service: works from the cache for a bounded time |
| `last_checked_at` hours or days old | check-ins have been failing that long |

Facts to read: `env.NANO_LICENSE_MODE` (online, offline), `env.AIRGAP_MODE`,
`env.LICENSE_URL` and `env.NANO_DEPLOYMENT_ID` (their names and non-secret
values; the token itself is always `[REDACTED]`). On a role split, the
deployment ID in `.nano-role.env` overrides `.env`: check `env.*` on every
host.

## Likely causes

1. Outbound access to the license service is blocked (firewall, proxy, DNS).
2. The token was regenerated on app.nano.rs and the install still has the
   old one.
3. The subscription changed (canceled, unpaid, trial over): the operator
   sees the reason on app.nano.rs.
4. The deployment ID does not match the deployment the token belongs to.

## Safe fixes (ask first)

- Network: from the nano host, the operator checks that the license service
  answers (with their proxy settings). Fix the egress rule or proxy.
- Token: the operator copies the current values from the deployment's page on
  app.nano.rs into a file (never into chat), and re-runs the installer with
  them, as in [Self-run](https://nano.rs/docs/getting-started/self-run/).
- Billing: only the account owner can fix it on app.nano.rs.
- Never edit the license tables or cached state, or set variables to bypass
  the check.

## Escalate

Escalate when the license service is reachable, the token is current, the
subscription is active, and the state stays `grace_period` or `locked`. Send:

- the bundle;
- the deployment ID (it is in the bundle) and the install ID (`overview`);
- the `license` recipe output and the time of the first failed check (UTC).
