# Collect by install type

All commands assume the `support` CLI from this skill's `scripts/support`.
Every command prints a plan, asks before collecting, and asks again before it
writes the final file.

## Docker Compose, single node

On the host, as the user that owns the install (the one that ran
`install.sh`, usually not root):

```bash
python3 ~/support collect --install-dir ~/nano --since 24h --out-dir ~/support-out
```

- Docker must work for that user without `sudo` (`docker ps` works).
- The install directory holds `.env` and `scripts/nano-support-bundle`.

From a workstation, with key-based ssh to the host:

```bash
python3 scripts/support collect --ssh nano@nano.example.com --install-dir '~/nano' --since 24h
```

The workstation needs only ssh and Python; the host needs `python3` 3.9 or
later. In one ssh session, this script is streamed to the host and runs
there: nano's bundle tool, the probes, redaction and the second redaction
check all happen on the host, inside a private temporary folder that is
removed when the session ends. Only the finished file and a short summary
come back. Nothing from the host is run on the workstation.

`--install-dir` may be `~/nano`, `~alice/nano` or a path with spaces: the host
expands it. `--ssh` takes `user@host` (neither part may start with `-`).
Use your ssh config or agent for keys and jump hosts; `--ssh-identity` and a
short list of safe `--ssh-option` names (`UserKnownHostsFile`,
`StrictHostKeyChecking`, `Port`, ...) are accepted, never options that run
commands (`ProxyCommand`, `LocalCommand`, ...).

## Docker Compose, role split (several hosts)

Run on the first app host. nano's bundle tool reads the host inventory
(`/etc/nano/inventory.yaml`, or `--inventory FILE` when you run nano's tool
yourself) and collects every other host over BatchMode SSH, so that host must
reach the others without a prompt:

```bash
ssh -o BatchMode=yes <other host address> true
```

If it can't, run `collect --local-only` on each host and keep every file. The
live probes cover the host they run on only.

## Kubernetes (Helm)

From any machine with `kubectl` and `helm` access to the release's namespace:

```bash
helm pull <chart reference> --version <chart version> --untar   # gives nano/scripts/nano-support-bundle
python3 scripts/support collect --kubernetes --namespace nano --release nano \
  --bundle-tool nano/scripts/nano-support-bundle --since 24h
```

- Add `--context CTX` to pick a kubectl context.
- Without `--bundle-tool`, the tool reads the release's app version with
  `helm list` and offers to download the matching
  `scripts/nano-support-bundle` from the public repository
  (`raw.githubusercontent.com/nano-rs/nano/v<version>/...`). It asks first,
  and checks the file against the SHA-256 pinned for that release before it
  saves or runs it. Releases without a pinned SHA-256 are refused: pass
  `--bundle-tool`.
- Probes read the namespace's Secret values into memory to redact them (when
  kubectl may), and reach Vector through its pod's curl sidecar and the API
  server's pod proxy, never by running anything in the Vector container.
- Probes run through `kubectl exec` (no port-forwards). An external,
  managed PostgreSQL is skipped and noted.

## Windows and options

| Option | Meaning |
|---|---|
| `--since 90m`, `24h`, `3d` | Log and error window (1 minute to 30 days). Default 24h. |
| `--no-probes` | Only nano's own bundle. |
| `--out-dir DIR` | Where the final file goes. Default: the current folder. |
| `--yes` | Answers yes to both questions. Only after the operator saw a preview and agreed. |
| `--local-only` | Role split: this host only. |

## Many files

When you have several files (role split hosts collected one by one, or a
before-and-after pair), load them all: `support load A.tar.gz B.tar.gz`. Each
row keeps its file name in the `bundle` column.
