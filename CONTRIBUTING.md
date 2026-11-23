# Contributing

Thanks for helping. Fixes to runbooks, new playbook queries, and parsing of
log formats we miss are all welcome.

## Ground rules

- **Never commit a real bundle**, real logs, host names, IP addresses,
  customer names or secrets. Use the sample bundle in `tests/fixtures/` and
  extend `tests/fixtures/make_sample_bundle.py`. Fixture addresses come from
  the documentation ranges (`192.0.2.0/24`, `198.51.100.0/24`,
  `203.0.113.0/24`) and names from `example.com`.
- **Don't fork nano's redaction.** `support` loads `nano-support-bundle` from
  the user's install. Redaction bugs belong in
  [nano](https://github.com/nano-rs/nano).
- **Probes stay read-only.** No query text, no table data, no event samples.
  Add a test in `tests/test_redaction.py` for any new probe.
- **Runbooks only state what the evidence can prove.** Quote real messages
  from nano's code or a real bundle. Every fix is a proposal that the agent
  asks about first; mark anything that deletes data.
- **Plain English**, US spelling, short sentences, no em dashes.

## Develop

```bash
make test          # unit tests, no Docker (downloads nano's bundle tool once, checked by SHA-256)
make test-docker   # also loads the sample bundle into a throwaway ClickHouse and runs every query
make lint          # ruff
make sync          # copy bin/support into each skill's scripts/ (a test checks they match)
make fixtures      # rebuild tests/fixtures/sample-bundle
```

`tests/test_hygiene.py` fails on private addresses, internal names, token
shapes, em dashes and UK spelling anywhere in the repository.

## Changing pinned versions

- The throwaway ClickHouse image is pinned by tag and digest in `bin/support`
  (`CH_IMAGE`). Check the new tag exists on Docker Hub
  (`clickhouse/clickhouse-server`) and use its digest.
- The nano bundle tool used by the tests is pinned in
  `tests/fetch_nano_tool.py` by release and SHA-256.

## Security issues

Please don't open a public issue for a redaction gap that exposes data.
Email support@nano.rs instead.
