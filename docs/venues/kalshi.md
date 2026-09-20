# First trade on Kalshi

`exchange_id: "kalshi"` · CFTC-regulated exchange · settles in USD

Kalshi is the odd one out in two ways: you trade **your own Kalshi account** rather than a
Kairos-custodied identity, and it is the only venue supporting native amend.

## Identifiers

```bash
curl -s "https://md.kairos.trade/v1/markets?provider=kalshi&limit=5"
```

Ticker-based, not token-based:

- `market_id` — the ticker, e.g. `KXBTC-26JUL`.
- `event_id` — the parent event, e.g. `KXBTC-26JUL-EVT`.
- `outcomes[].token_id` — `<TICKER>-YES` / `<TICKER>-NO`.

A `503 cache_cold` here means the Kalshi listing is still warming. Retry; it is not a
problem with your request.

## One-time onboarding

```http
POST https://execution.kairos.trade/exchanges/kalshi/enable-trading
```

**Kairos does not custody or provision a Kalshi identity.** You supply your own Kalshi API
key and RSA private key. The server validates the PEM, proves the credentials work by
calling Kalshi's balance endpoint, then encrypts them (AES-256-GCM) and stores them.

You are handing over a live private key. It is stored encrypted and used only to sign
Kalshi requests on your behalf. To rotate: rotate at Kalshi, then re-run this endpoint to
replace it.

Both PKCS#1 and PKCS#8 PEM encodings are accepted, and a key pasted as one line with
literal `\n` escapes is normalized before parsing.

Balance: `GET /exchanges/kalshi/balance`.

> This endpoint returns the minimal `{"error": "...", "code": "..."}` body, **not** the
> structured `error_details` envelope. Don't reuse your Polymarket error parser here.

## Constraints

| | |
|---|---|
| `supported_tif` | GTC, GTD, IOC, FAK, FOK |
| `post_only` | supported |
| `min_tick_size` | 0.01 |
| `max_price` | 1 |
| settlement | USD |
| native amend | **yes — the only venue** |

## A first order

```json
{
  "exchange_id": "kalshi",
  "market_id": "KXBTC-26JUL",
  "token_id": "KXBTC-26JUL-YES",
  "outcome": "Yes",
  "side": "buy",
  "kind": "limit",
  "quantity": "600",
  "price": "0.01",
  "time_in_force": "GTC",
  "client_order_id": "<uuid>"
}
```

## Amend — reprice without losing your order

```http
POST https://execution.kairos.trade/orders/{order_id}/amend
{ "price": 0.45 }
```

Kalshi is the only venue advertising `supports_native_amend`. The order keeps **both** its
Kairos `order_id` and its venue `exchange_order_id` — no supersession to reconcile, and no
second order whose fill could be booked twice. That's the whole reason to use it over
cancel-and-replace, which empties the book of your order for the entire cancel round trip.

- Price only. `quantity` is accepted **solely to be refused** with
  `409 EXCHANGE_AMEND_QUANTITY_UNSUPPORTED` — refused rather than ignored, so you never
  believe you resized when you didn't.
- Limit orders only, and `price` strictly between 0 and 1 in the order's own outcome terms.
- On any other venue: `409 EXCHANGE_AMEND_UNSUPPORTED`, answered before the order is even
  read. There is deliberately no internal cancel-and-replace fallback — that substitution
  changes queue position and order identity, so it is your call to make explicitly.

## Worth knowing

- Kalshi often completes terminal fill verification **synchronously** on cancel, so a
  cancel there is more likely to return `success: true` immediately than elsewhere. Don't
  write logic that assumes the async path is universal.
- `venue_reconciled` is currently authoritative for Kalshi specifically.
- `kalshi_offchain` is a deprecated alias; it canonicalizes to `kalshi`, but the response's
  top-level `id` echoes what you asked for. Read `capabilities.exchange_id`.
