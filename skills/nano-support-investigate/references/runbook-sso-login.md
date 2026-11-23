# Runbook: users can't sign in (SSO and passwords)

nano signs users in with a local password or with single sign-on over OpenID
Connect (OIDC). Group rules decide who may sign in through SSO. The public
guides are [Single sign-on](https://nano.rs/docs/settings/sso/) (with pages
for [Okta](https://nano.rs/docs/settings/sso/okta/),
[Microsoft Entra ID](https://nano.rs/docs/settings/sso/entra/),
[Google Workspace](https://nano.rs/docs/settings/sso/google-workspace/)) and
[Groups](https://nano.rs/docs/settings/sso/groups/).

## Symptoms

- `Too many login attempts. Please try again later.` (HTTP 429).
- An SSO sign-in ends on an error page, or loops back to the sign-in page.
- `SSO account is not in a group allowed to sign in`.

## Evidence

```bash
support query --recipe auth-sso
```

| Message | Meaning | Usual fix |
|---|---|---|
| `Login rate limit exceeded` (with `ip=`), users see `Too many login attempts` | more than 100 sign-in requests from one address in 5 minutes (or 10 per account in 10 minutes) | wait for `Retry-After`; find the client that retries (a monitor, a script, a shared NAT) |
| `Failed to fetch OIDC discovery document: ...`, `Failed to fetch JWKS: ...` | nano can't reach the identity provider | egress, proxy, DNS, or a wrong issuer URL |
| `Issuer URL blocked by security policy: ...` | the issuer URL points at an address nano refuses (for example a private one) | use the provider's public issuer URL |
| `Invalid ID token: Token validation failed: ...` | the token's issuer, audience or expiry doesn't match | check the issuer URL and client ID exactly; check the host clock (`host:time sync`) |
| `Invalid state parameter`, `OIDC authorization transaction not found, already consumed, or expired` | the sign-in took too long, was opened twice, or the browser lost its cookie | sign in again in one tab; check that the base URL is the one users open |
| `Redirect URI mismatch between /authorize and /callback` | the redirect URI registered at the provider differs from nano's | register nano's exact callback URL (scheme, host, port, path) |
| `Missing required claim: email or preferred_username` | the provider doesn't send an email claim | add the email scope or claim at the provider |
| `SSO email address is not verified by the identity provider` / `Rejected OIDC sign-in: email not verified by the identity provider` | the provider says the email is unverified | verify the email at the provider |
| `SSO account is not in a group allowed to sign in` (audit reason `group_not_allowed`) | the user is in none of the allowed groups | add the user to an allowed group, or map the group in nano |
| `SSO group membership could not be verified` (`membership_unknown`) | nano couldn't read the groups claim | send the groups claim, or check the group sync |
| `SSO identity cannot be linked to the local account` | a local account with that email exists and can't be linked | an admin links or removes the local account |
| `OIDC provider is disabled: ...` | the SSO provider is turned off in nano | turn it on in Settings |

Look at the host clock too: a clock that is off by minutes breaks token
validation.

```sql
SELECT key, value FROM facts WHERE key LIKE 'host.%time%' OR key LIKE 'host.collected%';
SELECT text FROM probes WHERE name = 'host:time sync';
```

## Likely causes

1. The redirect URI or base URL doesn't match what users open.
2. Issuer or client ID typed slightly wrong.
3. Group rules exclude the user.
4. A client retrying sign-ins hits the rate limit for everyone behind one
   address.
5. Clock drift on the host.

## Safe fixes (ask first)

- Configuration changes are made in nano's SSO settings and at the identity
  provider by the operator. Show them the exact field to change.
- Never raise or turn off the sign-in rate limit to fix a lockout. Find the
  client that retries instead.
- Time sync: the operator fixes NTP on the host.

## Escalate

nano support doesn't cover the identity provider itself. Escalate when the
provider's settings match nano's documented values and sign-in still fails.
Send:

- the bundle;
- the provider (Okta, Entra ID, Google Workspace, other), the time of a
  failed attempt (UTC), and the exact error text;
- the audit reason if shown (`sso_sign_in_denied` and its reason).
