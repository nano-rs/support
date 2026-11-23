# Runbook: AI provider errors

nano's AI features (pivt, the AI wizards, hunts' investigator) call the AI
provider the operator configured in Settings, AI & pivt. On Self-run the
operator brings their own provider and key. Most AI errors are answers from
that provider. The public guide is
[pivt AI settings](https://nano.rs/docs/settings/pivt-ai/).

## Symptoms

- pivt or a wizard shows `Authentication failed: ...`, `Model not available:
  ...`, `Rate limit exceeded`, `Request timeout`, or `AI Gateway error (<status>):
  ...`.
- `This model does not support tool calling. Choose a tool-capable model ...`
- Hunts' server runner shows "No AI provider is configured" or "the Hunt
  investigator agent's model (...) does not support tool calling".

## Evidence

```bash
support query --recipe ai-provider
support query --recipe error-clusters
```

| Message | Meaning |
|---|---|
| `Authentication failed: ...`, `<host> answered HTTP 401: the API key was rejected` | the provider refused the key (wrong, expired, revoked, or for another account) |
| `Model not available: ...` (HTTP 404), `check the endpoint path, deployment and model` | the model or deployment name doesn't exist at that endpoint |
| `Rate limit exceeded` (429), `the endpoint is rate limiting requests` | the provider's quota or rate limit |
| `Request timeout` (408/504), `the endpoint timed out` | the provider is slow, or a proxy timed out |
| `the endpoint returned a server error` (5xx) | the provider is failing |
| `Connection error: ...` | nano can't reach the endpoint: egress, proxy, DNS, or a private address that is not allowed |
| `Token limit exceeded: ...` | the request was larger than the model allows |
| `meloD AI service not configured (disabled or no credentials)` (api, at start) | no provider is set up |
| `Provider health check failed` (with `provider=` and `error=`) | nano's periodic provider check failed: the `error` says why |
| `Airgap mode: skipping AI provider health check (no on-prem base_url)` | air-gapped install with no on-premises model endpoint |

## Likely causes

1. A wrong or rotated API key.
2. A model or deployment name that doesn't exist for that key.
3. Provider rate limits or quota.
4. Egress blocked, a proxy in the way, or a private-address endpoint (a local
   model) without `NANO_ALLOW_PRIVATE_AI_ENDPOINTS=true`.

## Safe fixes (ask first)

- Key: the operator enters a new key in Settings, AI & pivt. Never paste a
  key into chat or a file in the bundle.
- Model: pick a model the provider offers, and a tool-capable one for agents.
- Rate limits: reduce concurrent use, or raise the provider quota.
- Network: fix egress or proxy settings. Allowing private AI endpoints is a
  security decision for the operator; explain it before they change it.

## Escalate

nano support doesn't cover the operator's AI provider. Escalate only when the
provider answers correctly to a direct test from the same host and nano still
fails. Send:

- the bundle;
- the provider type and model name (no key), the time (UTC), and the exact
  error text nano showed.
