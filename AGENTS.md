# Kairos API — contract for AI agents

You are writing a client against the Kairos prediction-market API. Read this file before
writing code.

**Provenance.** This is a compression of the OpenAPI 3.1 specs Kairos publishes at
`https://app.kairos.trade/openapi/kairos.json` (four services, no authentication needed to
fetch). Those specs are generated from the service repository and guarded by CI coverage
tests, so they cannot drift from the running API. Every claim below is re-derived from
them daily by `scripts/verify_contract.py` in this repo. **Where this file and the
published spec disagree, the spec wins** — fetch it when you need the full surface, an
endpoint not covered here, or certainty.

## Services

| Service | Base URL | Auth |
|---|---|---|
| Order Execution | `https://execution.kairos.trade` | API key required, no anonymous tier |
| Market Data | `https://md.kairos.trade` | anonymous tier available |
| Data API | `https://data.kairos.trade` | anonymous tier available |
| Execution WebSocket | `wss://execution.kairos.trade/ws` | API key or session |

## Authentication

Three headers, always all three:

```
X-Client-Id:  <client id>
X-Api-Key:    <key>
X-Api-Secret: <secret>
```

A partial header set is `401` — it does **not** fall back to anonymous. Credentials come
from the environment (`KAIROS_CLIENT_ID`, `KAIROS_API_KEY`, `KAIROS_API_SECRET`). Never
hardcode them, never log them, never write them into a commit, and never echo them back
into a chat transcript.

Scopes are per-operation: `trade:execute` (submit, cancel, amend), `trade:read` (read
orders), `position:read` (exposure). A key missing the scope gets `403`.

## Placing an order — `POST /orders`

```json
{
  "exchange_id": "polymarket",
  "market_id": "1005343",
  "token_id": "51003468...",
  "outcome": "Yes",
  "side": "buy",
  "kind": "limit",
  "quantity": "25",
  "price": "0.42",
  "time_in_force": "GTC",
  "client_order_id": "your-uuid-here",
  "source": "api"
}
```

Required: `exchange_id`, `market_id`, `side`, `kind`, `quantity`. In practice also send
`price` (see below), `token_id` (to select an outcome) and `client_order_id`.

Numeric fields are **decimal strings**, not floats — `"25"`, `"0.42"`. Prices on the
execution API are on the 0–1 scale.

Response is `OrderSubmitResponse`:

```json
{ "order_id": "<uuid>", "status": "queued" }
```

### Non-negotiable rules

1. **`price` is required on EVERY order, including `kind: "market"`.** There is no
   market-price sentinel. On a market order it is the worst price you will cross to.
   Omitting it is `400 VALIDATION_INVALID_PRICE`.

2. **`200` means queued, not live.** The order has been validated, persisted and enqueued.
   It is not on the venue yet. Never treat a `200` as a fill or as a resting order. Resolve
   the real state via `GET /orders/{order_id}` or the websocket.

3. **Always send `client_order_id`.** It is the idempotency key over
   `(user, exchange_id, market_id, client_order_id)`. A replay returns the existing order
   and does not consume a rate-limit slot. Omit it and the server generates a random one,
   so a retried request creates a **second order**. On any timeout or connection error,
   retry with the same `client_order_id` rather than assuming failure.

4. **Match `kind` to `time_in_force`.**
   - `kind: "limit"` → `GTC`, or `GTD` with `expiration_minutes` in `[1, 43200]`
   - `kind: "market"` → `FOK` (all or nothing) or `FAK`/`IOC` (partials allowed, remainder
     cancelled)
   - An unrecognized TIF is rejected, never silently downgraded to `GTC`.
   - A TIF the venue does not advertise is `400 EXCHANGE_UNSUPPORTED` — check
     `GET /exchanges/{exchange_id}/capabilities`.

5. **`post_only: true` is a guarantee, not a hint.** The venue rejects the order rather
   than let any part of it take liquidity. Requires `kind: "limit"` and `GTC`/`GTD`.

### Size and price bounds

- `quantity` > 0 and ≤ 1,000,000.
- BUY orders: minimum quantity 1 (default `MIN_ORDER_QUANTITY`). SELLs are exempt so a
  position can always be fully closed after partial fills.
- **API-key BUY orders additionally require `quantity × price >= 5` (USD notional).**
  Session callers are exempt; API callers are not. This is the single most common
  first-order rejection.
- `price` > 0 and ≤ the venue max (typically 1.0).

## Reading an order — `GET /orders/{order_id}`

Requires `trade:read`. `status` is one of:

| Status | Meaning |
|---|---|
| `pending` | accepted, not yet acknowledged by the venue (covers the internal `queued`/`locked`/`executing` states) |
| `live` | resting on the venue's book |
| `partial` | partially filled — the wire spelling is `partial`, **not** `partially_filled` |
| `filled` | fully filled — terminal |
| `cancelled` | cancelled — terminal |
| `expired` | GTD expiry — terminal |
| `failed` | rejected or errored — terminal |

`queued` appears only in the `POST /orders` response body. An order in flight can report
any of the internal working states — `pending` and `executing` are both normal while the
worker submits to the venue. Write your check as "is this one of my terminal states?"
rather than switch-casing on an exhaustive list.

`GET /orders` lists the caller's orders (newest first, `raw` and `metadata` stripped); the
single-order `GET` includes them.

Typical progression: `POST` → `queued` → `executing` → `live`, within a second or two.

## Cancelling — `POST /orders/{order_id}/cancel`

Requires `trade:execute` and ownership.

**This endpoint returns `200` even when the cancel did not happen.** Read the body:

```json
{ "success": false, "order_id": "...", "venue_reconciled": false,
  "message": "Order is being submitted to exchange. Please try again in a moment." }
```

- `success: true` — cancelled *and* terminal fill verification complete.
- `success: false` — either the order was already terminal, or verification is still in
  progress. `Venue accepted cancellation; terminal fill verification pending` is the
  in-progress case and the common one: the venue has taken the cancel, and Kairos is
  confirming the exact fill state before calling the order dead. Do not re-issue the
  cancel — poll the order until its status is terminal. Budget for that step; an order
  reads `live` for a short window while it runs. This barrier is what prevents a fill
  landing mid-cancel from being lost.
- The status and the receipt answer different questions and do not arrive together. Use
  the order status to know it is dead; use `final_filled_quantity` to know how much
  filled.
- Until `terminal_fill_verification.state == "complete"`, keep any protective logic
  active — a fill may have landed during the cancel.
- `filled_quantity` omitted does **not** mean zero. Do not infer it.
- `final_filled_quantity` on the completed receipt is the authoritative venue cumulative,
  not the latest fill delta.

Batch variants: `POST /orders/cancel-batch`, `POST /orders/cancel-all`.
Reprice in place: `POST /orders/{order_id}/amend` — Kalshi only today, price only;
passing `quantity` is refused by design rather than ignored.

## Per-venue differences

`exchange_id` ∈ `polymarket | kalshi | predictfun | hyperliquid`
(`kalshi_offchain` is a deprecated alias of `kalshi`).

| Venue | `supported_tif` | post-only | tick | max price | settles |
|---|---|---|---|---|---|
| `polymarket` | GTC, GTD, FOK, FAK, IOC | yes | 0.01 | 1 | USDC |
| `kalshi` | GTC, GTD, IOC, FAK, FOK | yes | 0.01 | 1 | USD |
| `predictfun` | GTC, GTD, FOK, FAK, IOC | yes | 0.001 | 1 | USDT |
| `hyperliquid` | GTC, GTD, IOC, FAK, FOK | yes (`Alo`) | 0.0001 | none | USDC |

Read `GET /exchanges/{exchange_id}/capabilities` at runtime instead of hardcoding this.
It also reports `supports_cancel_all` (false on Hyperliquid — your kill switch needs a
fallback there) and `supports_native_amend` (Kalshi only).

Venue-specific details:

- **Hyperliquid**: `market_id` is the numeric HIP-4 outcome id; `token_id` is the side
  coin `#<10 × market_id + side_index>`, required to select side 1 — read it from the
  orderbook snapshot's `token_ids`, don't compute it. Whole shares only. `FOK`/`FAK`/`IOC`
  all map to venue IOC, so FOK is **not** strict all-or-nothing here. No cancel-all, no
  fee quotes.
- **Kalshi**: you supply your own Kalshi API key and RSA private key via
  `POST /exchanges/kalshi/enable-trading`. Tickers, not token ids. Often completes cancel
  verification synchronously.
- **Predict.fun**: 0.001 tick, USDT on BSC. Onboarding is on-chain approvals only and is
  idempotent.
- **Polymarket**: onboarding derives CLOB credentials server-side; they are never
  returned to you.

Each venue needs a one-time `POST /exchanges/{venue}/enable-trading` before its first
order. Full detail per venue in `docs/venues/`.

## Finding markets — `GET https://md.kairos.trade/v1/markets`

No credentials needed.

**Confirm a market is quotable before you trade it.** The listing covers every market
Kairos tracks, which is a superset of what has a live orderbook at any moment. Check
`GET /v1/marks` for the pair first — never-traded pairs are omitted from that response
entirely, which is a cheap liquidity filter. On any order failure, branch on
`failure.classification` (`retryable` / `non_retryable`); the `actions` array is a UI
affordance, not retry policy.

```
GET /v1/markets?provider=polymarket&limit=100&cursor=<next_cursor>
```

`provider` ∈ `kalshi | polymarket | predictfun | hyperliquid`.
Response: `{ exchange_id, markets[], count, next_cursor, has_more }`, each market carrying
`market_id`, `condition_id`, `event_id`, `title`, and `outcomes[]` with
`{ outcome, normalized_outcome, token_id, outcome_index, side }`.

`market_id` + the chosen outcome's `token_id` are what `POST /orders` wants.

A `503 cache_cold` means that provider's listing hasn't been populated yet — retry, it is
not an error in your request. Responses are ETagged; send `If-None-Match` and handle `304`.

Prices from market data (`/v1/marks`, `/v1/candles`, `/v1/trades`) are on a **0–100**
scale. The execution API uses **0–1**. Divide by 100 when you carry a market-data price
into an order.

## Rate limits

- Order submission: default **5 per second per user**, sliding window, Redis-backed and
  **fail-closed** (if it can't check, it denies with `429`).
- **No `Retry-After`, no `X-RateLimit-*` headers.** Back off on your own schedule.
- The `429` body carries `error_details.code = VALIDATION_INVALID_ORDER` with the message
  `Order rate limit exceeded` — there is no dedicated rate-limit code on that path.
- Idempotent replays are resolved before the limiter and never consume a slot.
- Repeated auth failures from one IP: 10 per 60s, then throttled.
- Market data: 120 light + 20 heavy units/min anonymous, per IP.

## Errors

The main envelope on execution:

```json
{ "error": "human message", "code": "...",
  "error_details": { "code": "VALIDATION_INVALID_PRICE", "message": "...",
                     "details": {}, "metadata": {}, "actions": [] } }
```

Branch on `error_details.code`, not on the HTTP status alone. **Several error body shapes
exist on this service and they are not interchangeable** — some endpoints return an empty
body with only a status code. Always guard your parsing. See `docs/errors.md`.

Codes worth handling explicitly:

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_INVALID_ORDER` | 400 / 429 | bad side/kind/TIF combination, under $5 notional, or rate limited |
| `VALIDATION_INVALID_SIZE` | 400 | quantity ≤ 0, under the minimum, or over 1,000,000 |
| `VALIDATION_INVALID_PRICE` | 400 | price missing, ≤ 0, or above the venue max |
| `VALIDATION_MARKET_NOT_FOUND` | 404 | market/contract not resolvable on the venue |
| `EXCHANGE_UNSUPPORTED` | 400 | unknown `exchange_id`, or the venue doesn't support that TIF/flag |
| `FUNDS_INSUFFICIENT_USDC` / `FUNDS_INSUFFICIENT_BALANCE` | 400 | not enough balance — note this is a 400, not a 502 |
| `MARKET_FOK_NOT_FILLED` | 400 | FOK couldn't fill, or slippage exceeded `max_slippage_cents` |
| `ORDERBOOK_UNAVAILABLE` | 422 | market order couldn't be priced; retryable with a fresh book |
| `MARKET_PAUSED` | 503 | kill switch or venue restriction |
| `AUTH_CREDENTIALS_INVALID` | 403 | trading not enabled, or disabled account |
| `ALLOWANCE_CTF_NOT_SET` / `ALLOWANCE_USDC_NOT_SET` | 400 | missing on-chain approval |

## Writing a client — checklist

- [ ] Credentials from env, never from source.
- [ ] `client_order_id` on every submit; reuse it on retry.
- [ ] Never treat the submit response as a terminal state.
- [ ] Poll `GET /orders/{id}` (or use the websocket) until terminal, with a timeout.
- [ ] Check `success` on the cancel response; on `false`, poll the order to terminal
      rather than re-issuing the cancel.
- [ ] Respect 5 orders/sec; back off on `429` without expecting a `Retry-After`.
- [ ] Parse errors defensively — assume the body may be empty.
- [ ] Decimal strings, not floats, for `quantity` and `price`.
- [ ] Convert market-data prices from 0–100 to 0–1 before submitting.
- [ ] Test with an unmarketable resting limit order before anything marketable.
