# Errors

## Guard your parsing

**The execution service uses several different error body shapes, and they are not
interchangeable.** A client that assumes one shape will read `undefined` for the reason on
the others. Some endpoints return an **empty body** with only a status code — notably
`GET /orders/{id}` on 403/404/500, and the cancel endpoint on 400/403/404/500.

Write your error handling to survive:

1. a structured JSON envelope
2. a plain `{"error": "..."}` body
3. a plain-text body (a bad UUID in the path is rejected by the framework, before JSON)
4. no body at all

Always fall back to the HTTP status.

## The structured envelope

Returned by order submission, cancel-all, the CTF endpoints, the onboarding endpoints and
most of the deposit-wallet family:

```json
{
  "error": "human-readable message",
  "code": "...",
  "error_details": {
    "code": "VALIDATION_INVALID_PRICE",
    "message": "price is required",
    "details": {},
    "metadata": {},
    "actions": []
  }
}
```

Branch on **`error_details.code`**, not on the HTTP status alone — one status covers
several distinct causes. (Note the two `code` fields differ in case; use the inner one.)

## Codes worth handling

### 400 — validation and admission

| `error_details.code` | Cause | What to do |
|---|---|---|
| `VALIDATION_INVALID_ORDER` | unparseable `side`/`kind`; unrecognized `time_in_force`; `expiration_minutes` outside [1, 43200] on a GTD; `max_slippage_cents` outside [1, 99]; `max_retries` > 20; a TIF or `post_only` the venue doesn't advertise; an API-key BUY under $5 notional | fix the request; never blind-retry |
| `VALIDATION_INVALID_SIZE` | quantity ≤ 0, below `MIN_ORDER_QUANTITY` (BUY only), or above 1,000,000 | resize |
| `VALIDATION_INVALID_PRICE` | `price` missing (required on **every** order), ≤ 0, or above the venue max | send a price on the 0–1 scale |
| `EXCHANGE_UNSUPPORTED` | unregistered `exchange_id`, or a capability the venue lacks | check `GET /exchanges/{id}/capabilities` |
| `FUNDS_INSUFFICIENT_USDC` / `FUNDS_INSUFFICIENT_BALANCE` | pre-trade balance check, or a venue balance rejection | **note: 400, not 502** — fund the account |
| `MARKET_FOK_NOT_FILLED` | FOK couldn't fill, or realized slippage exceeded `max_slippage_cents` | expected outcome for FOK; re-quote |
| `EXCHANGE_POLYMARKET_MARKET_CLOSED` | market closed / trading halted | stop working that market |
| `ALLOWANCE_CTF_NOT_SET` / `ALLOWANCE_USDC_NOT_SET` | missing on-chain approval | run the venue's enable-trading flow once |

### 401 — authentication

Missing or wrong credentials. Remember: a **partial** header triple is a 401, not a
downgrade to anonymous. Do not retry a 401 in a loop — repeated auth failures from one IP
are throttled at 10 per 60s and the throttle fails closed.

### 403 — authorization

Missing scope (`API key missing trade:execute scope`), API-key access to that provider
disabled, an order belonging to another user, or `AUTH_CREDENTIALS_INVALID` (trading not
enabled / no signing identity). Often an empty body.

### 404

`VALIDATION_MARKET_NOT_FOUND` on submit — the market couldn't be resolved on the venue.
On `GET`/cancel by id: no such order (empty body).

### 422 — `ORDERBOOK_UNAVAILABLE`

A market order couldn't be priced because the live orderbook was missing or went stale
between pricing and submission. **Retryable** — a fresh book may arrive. It is never
auto-retried server-side within the same attempt.

### 429 — rate limited

Order submission is capped per user (default 5/sec, sliding window). Keys with an `orders`
override are checked against *both* their own per-credential window and the aggregate
per-user window — either denying is a 429. The limiter is Redis-backed and **fails
closed**: unreachable Redis denies.

- Body carries `error_details.code = VALIDATION_INVALID_ORDER`, message
  `Order rate limit exceeded`. There is no dedicated rate-limit code on this path.
- **No `Retry-After`. No `X-RateLimit-*`.** Back off on your own schedule —
  exponential with jitter.
- A *venue-side* rate limit surfaces differently, e.g. `EXCHANGE_POLYMARKET_RATE_LIMITED`.
- Idempotent replays never consume a slot.

### 500

`INTERNAL_ERROR`, `DATABASE_ERROR`, or `SIGNATURE_ERROR` (custodial signing failed). Retry
with the **same** `client_order_id` — the order may or may not exist, and idempotency is
what tells you which.

### 502

The venue call failed: `NETWORK_ERROR` or an unclassified `EXCHANGE_ERROR`. Balance,
allowance and market-closed rejections are classified *out* of this bucket into 400, so a
502 is genuinely "the venue didn't answer properly."

### 503

`MARKET_PAUSED` — a global or per-exchange execution kill switch, or a venue restriction.
Stop submitting and alert; this is deliberate, not transient noise. On market data,
`cache_cold` means the listing is still warming (retry), and a `503` on a
credentialed read can mean the access check itself failed closed.

## Retry policy

| Class | Retry? |
|---|---|
| Network timeout on submit | **Yes**, same `client_order_id` |
| 429 | Yes, after backoff |
| 422 `ORDERBOOK_UNAVAILABLE` | Yes, bounded |
| 500 / 502 | Yes, bounded, same `client_order_id` |
| 503 `MARKET_PAUSED` | No — alert instead |
| 400 validation | No — fix the request |
| 401 / 403 | No — fix the credential |

Always bound your retries, always jitter, and always reconcile afterwards with
`GET /orders` rather than trusting your own count of what you sent.
