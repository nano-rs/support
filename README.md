# nano support

Tools and agent skills to troubleshoot a [nano](https://github.com/nano-rs/nano)
install: collect a safe diagnostics bundle, load it into a local database you
can query, and follow step-by-step guides to find the cause.

Everything here runs on your own machines. Nothing is uploaded. You decide if a
bundle goes to nano support.

## What is in this repository

| Part | What it does |
|---|---|
| `bin/support` | A small command-line tool (one Python file, no installs needed). |
| `skills/nano-support-collect` | An agent skill: collect a bundle safely, with a preview and your OK. |
| `skills/nano-support-investigate` | An agent skill: load a bundle, run a query playbook, follow runbooks. |
| `tests/` | Tests, and a made-up sample bundle you can practice on. |

The skills use the open [Agent Skills](https://agentskills.io) format, the
same as nano's own skills. They work with coding agents such as Claude Code,
Codex and Cursor.

## The `support` tool

```text
support collect      collect a redacted bundle (shows a preview, asks before writing)
support load FILE    start a throwaway local ClickHouse and load the bundle into it
support recipes      list the named playbook queries
support query ...    run a read-only query (SQL, @file.sql, or --recipe NAME)
support shell        open clickhouse-client on the loaded bundle
support status       show the throwaway ClickHouse
support down         remove it and its data
support check FILE   look for secret-looking text left in a bundle
```

You need Python 3.9 or later. `load`, `query` and `shell` also need Docker.

### Collect

Run it on the nano host, as the user that installed nano:

```bash
curl -fsSLo support https://raw.githubusercontent.com/nano-rs/support/main/bin/support
python3 support collect --install-dir ~/nano --since 24h
```

From your workstation over ssh, or for Kubernetes:

```bash
python3 support collect --ssh nano@nano.example.com --since 24h
python3 support collect --kubernetes --namespace nano --release nano --bundle-tool nano/scripts/nano-support-bundle
```

With `--ssh`, the tool copies itself to the host for one session and does all
the work there; nothing from the host runs on your machine. On Kubernetes, a
downloaded copy of nano's tool must match a SHA-256 pinned for your release.

`collect` runs nano's own `scripts/nano support-bundle` from your install, so
it matches your release and uses nano's redaction. It can add read-only "live
probes" (health checks, migration state, Vector restarts, ClickHouse and
PostgreSQL summaries, disk and memory), which go through the same redaction.
It shows you every file, counts the IP addresses, emails and URLs in them, runs
a second redaction pass, and only then asks if it may write the file. See
[PRIVACY.md](PRIVACY.md) for exactly what is collected.

### Load and look

```bash
python3 support load support-nano-1-20261123T140000Z.tar.gz
python3 support query --recipe services
python3 support query --recipe first-errors
python3 support query "SELECT service, count() FROM logs WHERE level = 'ERROR' GROUP BY service"
python3 support down
```

`load` starts ClickHouse in Docker on `127.0.0.1` only, on a random port, with
a random password saved in a file only you can read. It fills four tables:
`logs`, `k8s_events`, `facts` and `probes`. `query` is read-only.

Try it on the sample bundle (all made-up data):

```bash
python3 bin/support load tests/fixtures/sample-bundle
python3 bin/support query --recipe vector-crash-loop
```

## Install the skills

Any agent with Agent Skills support:

```bash
npx skills add nano-rs/support --skill nano-support-collect
npx skills add nano-rs/support --skill nano-support-investigate
```

Claude Code, by hand (personal skills folder):

```bash
mkdir -p ~/.claude/skills && curl -fsSL https://github.com/nano-rs/support/archive/refs/heads/main.tar.gz \
  | tar -xz -C ~/.claude/skills --strip-components=2 support-main/skills/nano-support-collect
```

Use the same command with `nano-support-investigate` for the second skill.
Each skill folder has its own copy of the tool in `scripts/support`.

For an agent without skill support, copy the folder anywhere and tell the
agent: *"Read `nano-support-investigate/SKILL.md` and follow it."*

## Runbooks

The investigate skill has a runbook for each of these. Each one lists the
signs, the exact queries to run, the likely causes, safe fixes (your agent
asks before changing anything), and what to send nano support if you need to.

- Events are not arriving
- Vector crash loop
- ClickHouse disk full, out of memory, too many parts
- Migrations stuck or failed
- License in grace or locked
- An upgrade failed
- Hunts held, or telemetry not ready
- AI provider errors
- Users can't sign in (SSO and passwords)

## Safety

- **Read-only by default.** Collecting and querying change nothing on your
  install. The skills ask before every change, and ask again before anything
  that deletes data.
- **No event data.** Bundles never hold your log events, search results or
  query text.
- **Secrets are removed** by nano's own redaction, and checked again before
  the file is written.
- **Local only.** The tool never uploads anything.

## Getting help

- nano docs: [Getting help](https://nano.rs/docs/support/), including how to
  attach a bundle to a support case.
- nano's own agent skills (deploy, Agent Lane): [Agent skills](https://nano.rs/docs/agents/skills/).

## License

[AGPL-3.0-or-later](LICENSE), the same as nano and its agent skills.
