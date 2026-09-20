# First trade on Polymarket

`exchange_id: "polymarket"` · CTF outcome tokens on Polygon · settles in USDC

## Identifiers

```bash
curl -s "https://md.kairos.trade/v1/markets?provider=polymarket&limit=5"
```

- `market_id` — Kairos' numeric market id. This is what `POST /orders` wants.
- `condition_id` — the on-chain condition hash (`0x…`). Useful for cross-referencing
  on-chain data; not what you submit.
- `outcomes[].token_id` — the long numeric ERC-1155 outcome-token id. **Required** — it is
  what says which side of the market you are taking.
- `neg_risk` — whether the market is part of a negative-risk (mutually exclusive) event
  group.

## One-time onboarding

```http
POST https://execution.kairos.trade/exchanges/polymarket/enable-trading
```

In one call the server derives CLOB API credentials for your wallet (signing the ClobAuth
EIP-712 message with your delegated key), encrypts and stores them, and sets the token
approvals the venue needs. **Until this succeeds, `POST /orders` on `polymarket` fails.**

The derived credentials are **never returned** — they are stored server-side only,
deliberately kept out of HTTP responses so they cannot leak through logs, proxies or
devtools. You don't need them; Kairos signs with them on your behalf.

Verify with `GET /exchanges/polymarket/allowances`. Polymarket grants unlimited pUSD
approvals, so a *finite* pUSD allowance is reported as incomplete — POST to the same path
repairs it.

## Constraints

| | |
|---|---|
| `supported_tif` | GTC, GTD, FOK, FAK, IOC |
| `post_only` | supported |
| `min_tick_size` | 0.01 |
| `max_price` | 1 |
| settlement | USDC |

## A first order

A resting limit bid — unmarketable, so it sits on the book:

```json
{
  "exchange_id": "polymarket",
  "market_id": "1005343",
  "token_id": "51003468127441151629175486348234306205171264132494050168622344644756302639",
  "outcome": "Yes",
  "side": "buy",
  "kind": "limit",
  "quantity": "600",
  "price": "0.01",
  "time_in_force": "GTC",
  "client_order_id": "<uuid>"
}
```

To take liquidity instead, use `"kind": "market"` with `"time_in_force": "FOK"` (all or
nothing) or `"FAK"` (partials allowed) — and remember `price` is still required, as the
worst price you'll cross to.

## Worth knowing

- **`ALLOWANCE_CTF_NOT_SET` / `ALLOWANCE_USDC_NOT_SET`** on a `400` means onboarding
  didn't complete. Re-run enable-trading; don't retry the order.
- **`EXCHANGE_POLYMARKET_MARKET_CLOSED`** — the market is resolved or halted. Stop working
  it.
- **`EXCHANGE_POLYMARKET_RATE_LIMITED`** is the *venue's* limit, distinct from Kairos' own
  `429`. Back off harder.
- Tick is 0.01 by default, but individual markets can quote finer. Read `tick_size` from
  the market's metadata in `/v1/markets`, and `min_tick_size` from
  `GET /exchanges/polymarket/capabilities`, rather than hardcoding a grid.
- Cancellation is an L2 HMAC operation venue-side, so no wallet signature is needed — it
  works identically for custodial and self-custody orders.

## Self-custody

Polymarket is one of the two venues where allow-listed institutional accounts can sign
their own orders: `POST /v2/orders/intent` → sign the EIP-712 digest → `POST
/v2/orders/submit`. Submission is synchronous and returns the venue's verbatim result.
`POST /v2/onchain/intent` / `submit` do the same for approvals, redeem, split/merge and
unwrap on Polygon, where you also pay the gas.
