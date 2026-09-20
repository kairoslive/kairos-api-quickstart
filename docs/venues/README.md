# First trade, per venue

The [quickstart](../../README.md) is venue-agnostic on purpose: one order schema works
everywhere. These pages cover what is *specific* to each venue — how it names markets,
what one-time setup it needs, and the constraints it enforces.

## What every venue shares

Same endpoint, same body, same auth, same lifecycle:

```http
POST https://execution.kairos.trade/orders
X-Client-Id / X-Api-Key / X-Api-Secret

{ "exchange_id": "<venue>", "market_id": "...", "token_id": "...",
  "side": "buy", "kind": "limit", "quantity": "100", "price": "0.42",
  "time_in_force": "GTC", "client_order_id": "<uuid>" }
```

Only `exchange_id` and the identifiers change. That is the point of the aggregation: you
write one client, not five.

## What differs

Authoritative values, from `OrderExchangeCapabilities` in the published spec. Read them at
runtime from `GET /exchanges/{exchange_id}/capabilities` rather than hardcoding — this
table is a snapshot, that endpoint is the truth.

| Venue | `supported_tif` | post-only | `min_tick_size` | `max_price` | settlement |
|---|---|---|---|---|---|
| [`polymarket`](polymarket.md) | GTC, GTD, FOK, FAK, IOC | yes | 0.01 | 1 | USDC |
| [`kalshi`](kalshi.md) | GTC, GTD, IOC, FAK, FOK | yes | 0.01 | 1 | USD |
| [`predictfun`](predictfun.md) | GTC, GTD, FOK, FAK, IOC | yes | 0.001 | 1 | USDT |
| [`hyperliquid`](hyperliquid.md) | GTC, GTD, IOC, FAK, FOK | yes (venue-side `Alo`) | 0.0001 | none | USDC |

`kalshi_offchain` is a deprecated alias that canonicalizes to `kalshi`.

A `time_in_force` outside a venue's `supported_tif`, or `post_only` where it isn't
supported, is a `400` rather than a silent downgrade — you always know exactly what the
venue accepted.

## Capabilities at runtime

```http
GET https://execution.kairos.trade/exchanges/{exchange_id}/capabilities
```

Authentication, but no scope. Returns `supported_tif`, `supports_post_only`,
`min_tick_size`, `min_order_size`, `max_order_size`, `fee_model`, `maker_fee_bps` /
`taker_fee_bps`, `chain_id`, `settlement_currency`, `requires_allowances`,
`supports_redemption`, `supports_cancel_all`, `supports_batch_orders`,
`supports_user_websocket` and `is_active`.

Two worth branching on:

- **`supports_cancel_all: false`** — `POST /orders/cancel-all` is unavailable there, so
  your kill switch needs a per-order fallback on that venue.
- **`supports_native_amend`** — only `kalshi` today. Everywhere else, repricing means
  cancel-and-replace, which you must implement yourself and which changes your queue
  position.

The canonical id may differ from the one you asked for; read `capabilities.exchange_id`,
not the id you sent.

## One-time onboarding

Every venue needs a one-time setup call before its first order, and `POST /orders` fails
until it succeeds. What that call does differs a lot — see each page.

| Venue | Endpoint | What it does |
|---|---|---|
| Polymarket | `POST /exchanges/polymarket/enable-trading` | derives CLOB credentials, sets approvals |
| Predict.fun | `POST /exchanges/predictfun/enable-trading` | on-chain approvals on BSC, gas-sponsored |
| Kalshi | `POST /exchanges/kalshi/enable-trading` | **you supply your own Kalshi API key + RSA key** |

Check the result with `GET /exchanges/{exchange_id}/allowances`, which reports every
token/spender pair the venue needs and whether the current on-chain allowance is
sufficient. `enabled: true` only when all of them are.
