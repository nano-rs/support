# Privacy: what is and isn't collected

This page explains what `support collect` puts in a bundle, what it never
collects, and where the data goes.

## Where the data goes

Nowhere, unless you send it. The tool writes one file on your machine
(mode 0600: only you can read it). It has no upload feature and makes no
network calls, except:

- with `--ssh`, to the host you name. The tool streams itself to the host and
  runs there with the host's `python3`; redaction and the second check happen
  on the host, and only the finished file comes back. Nothing from the host
  is ever run on your machine;
- on Kubernetes, to your cluster through `kubectl` and `helm`;
- on Kubernetes without `--bundle-tool`, one download of nano's public
  `nano-support-bundle` script from `raw.githubusercontent.com/nano-rs/nano`.
  It asks first, and the file must match the SHA-256 this tool has pinned for
  your release before it is saved or run. A release without a pinned SHA-256
  is never downloaded.

`support load` runs a database in Docker on your own machine, listening on
`127.0.0.1` only. `support down` deletes it and everything loaded into it.

## Two parts

A bundle has two parts. Both are redacted the same way.

1. **nano's own support bundle**, made by `scripts/nano support-bundle` from
   your install. Its rules are nano's, for your release. The bundle's own
   `README.md` lists them.
2. **Live probes** (optional, `--no-probes` turns them off), made by this
   tool. They pass through nano's redaction too, with your install's secret
   values added so they are replaced wherever they appear: on Compose, the
   values in `.env`; on Kubernetes, the values of the release namespace's
   Secrets, read into memory only (never written) when your kubectl user may
   read them. Every Secret value counts as secret except user names, hosts,
   ports and database names; passwords inside URLs, registry logins and
   config files are found and replaced too. Without that permission, Kubernetes probes use pattern
   redaction only, and the bundle records that. Quoted values in database
   error messages are removed too.

## Collected

- Versions, the edition, image names, the install ID and deployment ID.
- Host facts: operating system, CPU count, memory, time sync, disk use,
  mounts.
- Service state: running or not, restarts, out-of-memory kills, exit codes,
  health checks, memory limits.
- The nano services' own logs for the time window you choose (24 hours by
  default), size-capped. For the ingest services (Vector, ClickHouse and
  similar), only warning and error lines are kept, with event fragments
  removed. In nano's own service logs, quoted SQL values and search text in
  web addresses are removed.
- ClickHouse system information: errors by code, parts, merges, mutations,
  disks, memory settings, and query totals by hour, user, kind and error code.
- PostgreSQL summaries: migration state, connection counts, waiting locks,
  dead rows per table, database size, the cached license state.
- Vector metrics: errors, discards, buffer sizes, throughput, and the names
  of its components.
- Configuration setting **names**, and the values of settings that are not
  secret (for example `NANO_VERSION=2.0.34`). Secret values show as
  `[REDACTED]`.
- Recent configuration changes: time, action and object only.
- On Kubernetes: pods, events, `describe` output and the Helm values with
  secrets removed.

## Never collected

- Your log events, or the raw logs your sources sent to nano.
- Search or query results, and **query text**: ClickHouse's query log is
  summed up by hour, user and error code, and identified only by a hash of
  the query's shape. PostgreSQL's running statements are never read.
- Lookup tables, IOC lists, case contents.
- Secret configuration values, passwords, tokens, private keys,
  certificates, the license token or license files.
- The output of `vector-tap` (it shows sampled events).

## What redaction removes

Secret `.env` values (replaced everywhere they appear), tokens, JSON web
tokens, private keys and certificates, passwords in URLs, the license token,
`Authorization` and `Cookie` headers, `key=value` pairs whose key names a
secret, and ingest tokens.

## What can still be in it

Redaction works by patterns. Logs can still name your host names, IP
addresses, user names and the names of your rules, sources and dashboards.
Before writing, the tool counts the IP addresses, email addresses and URLs it
finds and shows examples, so you can decide. Review the file before you send
it:

```bash
tar -tzf support-*.tar.gz
tar -xzOf support-*.tar.gz | less
python3 support check support-*.tar.gz --bundle-tool ~/nano/scripts/nano-support-bundle
```

If you send a bundle to nano support, see
[Getting help](https://nano.rs/docs/support/) for how bundles are stored and
when they are deleted.
