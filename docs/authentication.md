# Authentication

## Creating a token

1. Create an account at [kairos.trade](https://kairos.trade) — email or wallet.
2. Profile picture (top right) → **Settings**.
3. Left sidebar → **API Tokens**.
4. **Create API token** — name, access level, optional IP allowlist. Creating or revoking
   requires re-authentication and a security check.

You get three values, shown **once**: Client ID, API key, Client secret. The dialog's
"Copy all as .env" button emits them as `KAIROS_CLIENT_ID`, `KAIROS_API_KEY` and
`KAIROS_CLIENT_SECRET`.

There is a cap on how many tokens can be active at once; the section header shows your
count. Revoke what you no longer use.

## The header triple

Every authenticated request carries all three:

```http
X-Client-Id: <client id>
X-Api-Key: <key>
X-Api-Secret: <secret>
```

There is no bearer-token form for API consumers. `Authorization: Bearer <jwt>` exists but
belongs to first-party Kairos web sessions.

**Partial header sets are rejected with `401`.** They do not degrade to the anonymous
tier. If you send `X-Api-Key` alone against market data expecting free-tier behaviour, you
get a 401, not a free request.

Resolution order is fixed: an `Authorization` header takes the bearer path, any of the
three API-key headers takes the API-key path, and only a request carrying neither is
eligible for anonymous.

## Access levels and scopes

The UI offers two **access levels**; the server derives the underlying scopes from them.
You never type a scope string.

| Access level | Underlying scopes | Can it place orders? |
|---|---|---|
| **Read-only** | `trade:read`, `position:read` | no |
| **Trading** | adds `trade:execute` | yes |

What the scopes gate, per endpoint:

| Scope | Covers |
|---|---|
| `trade:execute` | `POST /orders`, all cancel endpoints, amend |
| `trade:read` | `GET /orders`, `GET /orders/{id}` |
| `position:read` | `GET /positions/exposure` |

A token missing the required scope gets `403` with a message naming it. Scope checks
apply to API-key credentials only.

Choose the narrower level. A market scanner that never trades should be Read-only — a
token that cannot place orders cannot lose money.

## The mutation gate

The custodial mutation endpoints (`POST /orders` and the cancel family) sit behind an
additional check satisfied by any of: the full API-key triple, an internal service token,
or a CSRF token. **API-key consumers satisfy it automatically** — nothing extra to send.
The one thing that does *not* satisfy it is a bare session JWT, which is why some web-app
recipes don't translate directly to API keys.

## Anonymous access

Market Data (`md.kairos.trade`) and the Data API (`data.kairos.trade`) work with no
credentials at all: 120 light units/min and 20 heavy units/min, keyed per source IP.
Enough to explore, prototype and backtest. With a key, the default budget is 1,200 light
and 150 heavy units/min, raisable per credential.

Execution has **no anonymous tier**.

## IP allowlisting

The create-token dialog has an optional **IP allowlist** field — comma-separated
addresses, e.g. `203.0.113.7, 198.51.100.22`. When set, requests from any other source
are rejected with `403 ip_not_whitelisted`; on market data, that is the only 403 the
service emits. The UI validates loosely and the server re-validates properly.

Strongly worth turning on for any trading token running from a fixed egress IP. It turns
a leaked credential from a disaster into an inconvenience.

## Rate limits on auth failures

Repeated authentication failures from one client IP are throttled at 10 per 60 seconds,
fail-closed, returning `{"error": "Too many authentication attempts"}`. A bot looping on a
bad credential locks itself out — fail fast on `401` instead of retrying.

## Key hygiene

- Keys live in `.env` (gitignored here) or a secret manager. Not in source, not in a
  Dockerfile, not in CI logs.
- Never paste a secret into a chat window or an LLM prompt. Prompts are logged.
- Never commit one. A force-push does not remove it from forks, caches, or anyone who
  already cloned. If it has been committed, rotate — don't rewrite history and hope.
- Redact credentials from your own logs. The examples in this repo read from the
  environment and never print them.
- Rotate on any suspicion, and on staff turnover.
- Separate keys per bot, so you can kill one without killing everything.

If a key is compromised: generate a new one, cut over, delete the old one, and check
`GET /orders` for anything you didn't place.
