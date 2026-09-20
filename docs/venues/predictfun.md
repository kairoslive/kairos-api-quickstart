# First trade on Predict.fun

`exchange_id: "predictfun"` · conditional tokens on BSC · settles in USDT

## Identifiers

```bash
curl -s "https://md.kairos.trade/v1/markets?provider=predictfun&limit=5"
```

Same shape as Polymarket: numeric `market_id`, `condition_id` hash, and a long numeric
`token_id` per outcome. You need `market_id` + the chosen outcome's `token_id`.

## One-time onboarding

```http
POST https://execution.kairos.trade/exchanges/predictfun/enable-trading
```

Predict.fun has **no server-side credentials to provision** — orders are signed at
submission time. This endpoint does the one-time on-chain setup instead: it approves USDT
and ConditionalTokens across all four `(yieldBearing × negRisk)` market variants,
gas-sponsored on BSC.

A wallet must run this once before its first Predict.fun order. The executor does **not**
approve per trade.

**Idempotent.** Variants already approved are no-ops, and a partially-approved wallet
re-submits only the missing variants on the next call — so retrying is always safe.

> Error shape: this endpoint returns the minimal `{"error": "...", "code": "..."}` body
> (`OrderSimpleErrorResponse`) rather than the structured `error_details` envelope used on
> the order path. Codes include `INSUFFICIENT_SCOPE`, `PLATFORM_API_ACCESS_DISABLED`,
> `RATE_LIMITED`, `INVALID_USER_ID`.

Account state: `GET /exchanges/predictfun/account`.

## Constraints

| | |
|---|---|
| `supported_tif` | GTC, GTD, FOK, FAK, IOC |
| `post_only` | supported |
| `min_tick_size` | **0.001** |
| `max_price` | 1 |
| settlement | **USDT** |

The **0.001 tick** is the thing to notice. It is ten times finer than Polymarket's and
Kalshi's, so a price grid computed for those venues is valid here but leaves you quoting
coarser than the book allows.

## A first order

```json
{
  "exchange_id": "predictfun",
  "market_id": "1027194",
  "token_id": "95529413987055678045721671221891051419305712495092201322982484927770599527786",
  "outcome": "Yes",
  "side": "buy",
  "kind": "limit",
  "quantity": "600",
  "price": "0.01",
  "time_in_force": "GTC",
  "client_order_id": "<uuid>"
}
```

## Worth knowing

- Settlement is **USDT on BSC**, not USDC on Polygon. Sizing logic that assumes one
  collateral asset across venues is wrong here.
- `503 predictfun execution is not available on this node` is a deployment-topology
  response, not a rejection of your order. Retry.
- Predict.fun is the second venue (with Polymarket) where allow-listed institutional
  accounts can use the self-custody lane: `POST /v2/orders/intent` → sign → `POST
  /v2/orders/submit`.
