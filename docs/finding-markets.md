# Finding markets

Before you can place an order you need two identifiers: **`market_id`** (the market on the
venue) and **`token_id`** (the specific outcome you're taking). Both come from the free
Market Data API — no credentials required.

## List active markets

```bash
curl -s "https://md.kairos.trade/v1/markets?provider=polymarket&limit=100"
```

`provider` ∈ `kalshi` | `polymarket` | `predictfun` | `hyperliquid`
(case-insensitive). `limit` ∈ [1, 250], default 100.

```json
{
  "exchange_id": "kalshi",
  "markets": [
    {
      "exchange_id": "kalshi",
      "market_id": "KXBTC-26JUL",
      "condition_id": "",
      "event_id": "KXBTC-26JUL-EVT",
      "title": "Bitcoin price above $120k on July 31?",
      "neg_risk": false,
      "outcomes": [
        { "outcome": "Yes", "normalized_outcome": "yes",
          "token_id": "KXBTC-26JUL-YES", "outcome_index": 0, "side": "yes" },
        { "outcome": "No",  "normalized_outcome": "no",
          "token_id": "KXBTC-26JUL-NO",  "outcome_index": 1, "side": "no" }
      ],
      "raw": {}
    }
  ],
  "count": 1,
  "next_cursor": "eyJvZmZzZXQiOjEwMH0=",
  "has_more": true
}
```

Pass `market_id` and the chosen outcome's `token_id` straight into `POST /orders`, with
`outcome` as the human-readable label.

## Pagination

Cursor-based. While `has_more` is true, pass `next_cursor` back as `cursor`. Don't
construct cursors yourself — they're opaque.

## Caching

Responses carry a strong `ETag` and a `Cache-Control`. Send `If-None-Match` with the
previous ETag and a `304` costs you nothing but still counts as a request. Use it for a
market list you refresh on a loop.

## `503 cache_cold`

```json
{"error":{"code":"cache_cold","message":"metadata cache warming up, retry shortly"}}
```

The provider's active-market listing hasn't been populated yet. Nothing is wrong with your
request — retry after a few seconds (a `Retry-After: 5` is included). Handle this
explicitly; it's the first thing a new integration hits.

## Check a market is quotable before you trade it

`/v1/markets` enumerates every market Kairos tracks on a venue — which is deliberately a
superset of what has a live orderbook at any given moment. Newly listed, paused and
thinly-quoted markets all appear there, which is exactly what you want for discovery and
research, and not what you want to fire an order at blind.

One cheap filter, before you size anything:

```
GET https://md.kairos.trade/v1/marks?provider=polymarket&pairs=<condition_id>:<token_id>
```

**Pairs that have never traded are omitted from the response entirely** — no zero, no
null placeholder. An empty result is your answer. For live depth rather than last trade,
use the market-data websocket.

If an order does fail at the venue, the order row carries a `failure` object. Branch on
**`failure.classification`** (`retryable` / `non_retryable`) — that field is the retry
policy. The `actions` array beside it drives UI affordances and is not a retry
instruction.

## Identifiers per venue

Venues name things differently. The listing normalizes them, but it helps to know what
you're looking at:

- **Polymarket / Predict.fun** — `market_id` is a numeric id, `condition_id` is
  the on-chain condition hash, and `token_id` is the long numeric ERC-1155 outcome-token
  id. You need `token_id` to say which side you're taking.
- **Kalshi** — ticker-based. `market_id` is the ticker (`KXBTC-26JUL`), and outcomes are
  the Yes/No pair.
- **Hyperliquid (HIP-4)** — `market_id` is the numeric outcome id, and `token_id` is the
  side coin, `#<10 * market_id + side_index>` — e.g. `#1010` / `#1011`. It's required to
  select side 1. Quantities are whole shares.

If you have an identifier from elsewhere and want the canonical one:

```
GET https://md.kairos.trade/v1/market-identifiers/resolve
```

## Prices

```
GET https://md.kairos.trade/v1/marks?...          last trade price per outcome
GET https://md.kairos.trade/v1/candles?...        OHLCV, 1s/1m/5m/15m/1h/4h/1d
GET https://md.kairos.trade/v1/trades?...         the trade tape
GET https://md.kairos.trade/v1/markets           metadata, including per-market tick_size
```

> **Scale mismatch — read this twice.** Market-data prices are on a **0–100** scale
> (`63.5` = 63.5% probability). The execution API takes prices on a **0–1** scale
> (`"0.635"`). Divide by 100 when carrying a market-data price into an order. Getting this
> wrong turns a 63-cent bid into a rejected order — or worse, silently changes your size.

Also mind the **tick size**: a price off the venue's grid is rejected. Each market's
metadata in `/v1/markets` carries its own `tick_size`, and the venue-wide floor is
`min_tick_size` from `GET /exchanges/{exchange_id}/capabilities`. Read them rather than
hardcoding a grid — a market can quote finer than its venue's default.

## Search and discovery

For "find me markets about X" rather than "enumerate everything", the Data API at
`data.kairos.trade` has `/search/markets`, `/search/screener`, `/api/markets/discover/v2`,
`/api/markets/trending`, plus sports-specific endpoints. Also anonymous-friendly.
