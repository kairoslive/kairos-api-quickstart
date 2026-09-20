# First trade on Hyperliquid (HIP-4)

`exchange_id: "hyperliquid"` · HIP-4 prediction markets · settles in USDC

Hyperliquid's identifier scheme is unlike the other venues'. Read this section before
writing any code against it.

## Identifiers

- **`market_id`** — the numeric HIP-4 **outcome id**, e.g. `"101"`.
- **`token_id`** — the **side coin**, `#<10 × market_id + side_index>`. For market `101`
  that is `#1010` (side 0) and `#1011` (side 1). Take it from the market-data
  `OrderbookSnapshot.token_ids` rather than computing it by hand.
- **`outcome`** — the selected display label.

`token_id` is **required to select side 1.** Omit it and you are not trading the side you
think you are.

- Quantities are **whole shares**.
- `min_tick_size` is `0.0001` — the finest of any venue here.
- There is **no `max_price`**.

## Constraints

| | |
|---|---|
| `supported_tif` | GTC, GTD, IOC, FAK, FOK |
| `post_only` | supported — expressed venue-side as the `Alo` time-in-force rather than a flag, but the request field is the same `post_only: true` |
| `min_tick_size` | 0.0001 |
| `max_price` | none |
| settlement | USDC |

**TIF mapping.** Hyperliquid maps `GTC`/`GTD` to venue GTC, and `IOC`/`FAK`/`FOK` to venue
IOC. So a `FOK` here behaves as the venue's IOC — it does **not** give you strict
all-or-nothing semantics the way it does on Polymarket. If you depend on fill-or-kill,
this is the venue where that assumption breaks.

**Not available on Hyperliquid:**

- `POST /orders/cancel-all` — your kill switch needs a per-order or batch fallback here.
- Fee quotes (`POST /orders/fee-quote`).

Single-order and selected-order batch cancellation both work.

## A first order

```json
{
  "exchange_id": "hyperliquid",
  "market_id": "101",
  "token_id": "#1011",
  "outcome": "No",
  "side": "buy",
  "kind": "limit",
  "quantity": "25",
  "price": "0.42",
  "time_in_force": "GTC",
  "client_order_id": "<uuid>"
}
```

(This is the example carried in the published OpenAPI spec for `POST /orders`.)

Transfers and withdrawals have their own prepare/execute pairs:
`POST /exchanges/hyperliquid/withdraw/prepare` → `/withdraw`, and
`/transfer/prepare` → `/transfer`.

## Worth knowing

- Read `token_ids` from the orderbook snapshot rather than computing the side coin
  yourself — it is the one identifier worth taking straight from the source.
- No `max_price` means your own sanity bounds are the only ones. Set them.
- Fractional quantities are not a thing — whole shares only.
