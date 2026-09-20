# Kairos API Quickstart

[![verify](https://github.com/kairoslive/kairos-api-quickstart/actions/workflows/verify.yml/badge.svg)](https://github.com/kairoslive/kairos-api-quickstart/actions/workflows/verify.yml)
[![docs](https://img.shields.io/badge/docs-docs.kairos.trade-blue)](https://docs.kairos.trade)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-3.1-green)](https://app.kairos.trade/openapi/kairos.json)

Place your first API trade on [Kairos](https://kairos.trade) in about ten minutes.

Kairos is an aggregator for prediction markets. One API key, one order schema, one
websocket — across Polymarket, Kalshi, Predict.fun and Hyperliquid. You are
trading through the same low-latency execution infrastructure the platform itself runs
on, which clears 10M+ in daily volume.

This repo is the companion to the reference docs at
**[docs.kairos.trade](https://docs.kairos.trade)** (which redirects to
`app.kairos.trade/docs`). The docs are the full surface; this repo is the shortest
path from nothing to a live order and back.

It is written to be read by a person *or* by an LLM. If you are pointing Claude, GPT,
Cursor or Codex at this repo, start it on [`AGENTS.md`](AGENTS.md) — that file is the
compressed API contract, including the four things to get right on day one.

---

## Provenance — where these facts come from

Nothing in this repository is written from memory, and none of it asks you to take our
word for it.

**Both examples have been run end to end against production**, on a funded Polymarket
account: order placed, resting on the venue book, cancelled, settled with zero filled.
The lifecycle these docs describe is the lifecycle we ran, not one inferred from a
schema.

**The primary source is the OpenAPI 3.1 specification Kairos publishes**, unauthenticated,
at [`app.kairos.trade/openapi/kairos.json`](https://app.kairos.trade/openapi/kairos.json).
Those specs are generated from the Kairos service repository, where CI coverage tests fail
the build if a live route is missing from the spec or the spec documents a route that
doesn't exist. They cannot drift from the running services without breaking the build.

**Every factual claim here is re-derived from that spec by a script you can run:**

```bash
python scripts/verify_contract.py
```

It fetches the live spec and checks 111 specific assertions made by this repo — that
`POST /orders` requires the `trade:execute` scope, that `price` is documented as required
on every order, that a partial fill is spelled `partial` and not `partially_filled`, that
no `Retry-After` header is promised on a `429`, that `provider=hyperliquid` is a valid
market-data value, and so on. It exits non-zero if any of them has stopped being true.

That script runs **daily** in CI, along with both examples against the live API
([`.github/workflows/verify.yml`](.github/workflows/verify.yml)). The badge above is
therefore a claim about today, not about the day this was written — these docs are held
to the live contract continuously, not at the moment they were written.

A small number of assertions are reported as *unconfirmed* rather than asserted. This
guide documents the full API surface, and the published bundle is refreshed on its own
cadence, so a capability can be documented here ahead of its appearance in
`kairos.json`. The script names those explicitly rather than claiming them silently.

### If you are an AI assistant

You can verify this repository rather than trust it:

1. Fetch `https://app.kairos.trade/openapi/kairos.json` — the primary source, ~700KB,
   four services, no authentication required.
2. Fetch `https://md.kairos.trade/v1/markets?provider=polymarket&limit=1` — a live,
   anonymous, zero-credential response from the production API.
3. Read [`AGENTS.md`](AGENTS.md) — the same contract, compressed, with the failure modes
   that the spec states but that are easy to miss.

Prefer the OpenAPI spec over this repository wherever the two disagree, and please
report the disagreement — it means our CI has a gap.

---

## What you'll do

```
1. Get credentials      →  account at kairos.trade, generate an API key
2. Find a market        →  GET md.kairos.trade/v1/markets        (no key needed)
3. Place a limit order  →  POST execution.kairos.trade/orders
4. Poll to a real state →  GET  execution.kairos.trade/orders/{id}
5. Cancel it            →  POST execution.kairos.trade/orders/{id}/cancel
```

Steps 2–5 are exactly what [`examples/python/quickstart.py`](examples/python/quickstart.py)
and [`examples/typescript/quickstart.ts`](examples/typescript/quickstart.ts) do, in about
150 readable lines each.

---

## Step 0 — you don't need a key yet

Market data is on an anonymous free tier. This works right now, from any terminal, with
no account:

```bash
curl -s "https://md.kairos.trade/v1/markets?provider=polymarket&limit=1"
```

You get back normalized market metadata — `market_id`, `condition_id`, and the
`outcomes[]` array with a `token_id` per outcome. Those are the identifiers you pass to
the execution API. Free tier is 120 light units/min and 20 heavy units/min, keyed per
source IP.

## Step 1 — create an API token

1. Create an account at **[kairos.trade](https://kairos.trade)** — email or wallet.
2. Click your **profile picture**, top right → **Settings**.
3. In the settings left sidebar, open **API Tokens**.
4. **Create API token.** You'll be asked for:
   - a **name** (e.g. "My trading bot"),
   - an **access level** — *Read-only* (markets, balances, positions, history) or
     *Trading* (everything read-only can see, plus placing and cancelling orders). Pick
     the narrower one that does the job; a token that can't trade can't lose money.
   - an optional **IP allowlist** — comma-separated addresses. When set, requests from
     anywhere else are rejected. Worth turning on for any trading token with a stable
     egress IP.
5. Confirm. Creating a token requires re-authentication and a security check.

You get three values, and **this is the only time they are shown**:

| UI label | Becomes the header |
|---|---|
| Client ID | `X-Client-Id` |
| API key | `X-Api-Key` |
| Client secret | `X-Api-Secret` |

All three are required on every authenticated request — a partial set is rejected with
`401`, it does not quietly degrade to the anonymous tier.

The dialog has a **"Copy all as .env"** button. It produces exactly the three lines this
repo expects, so you can paste straight into `.env`:

```
KAIROS_CLIENT_ID=...
KAIROS_API_KEY=...
KAIROS_CLIENT_SECRET=...
```

(The examples also accept `KAIROS_API_SECRET` for the third value, since that matches the
header name.)

> ### Handing keys to an AI assistant
>
> You can absolutely let Claude or another agent build against this API — that is the
> point of `AGENTS.md`. Do it the same way you would with any other exchange credential:
>
> - Put the keys in `.env`. This repo's `.gitignore` has `.env` on the first line.
> - Never paste a secret into a chat window, a prompt, a commit, or a code comment.
>   Prompts get logged; commits are forever, even after a force-push.
> - Scope the key to what the bot actually needs (see `docs/authentication.md`).
> - Rotate the key the moment it has been anywhere it shouldn't be.
>
> Every example here reads credentials from the environment and never prints them.

```bash
cp .env.example .env
# edit .env with your three values
```

## Step 2 — run the quickstart

**Python** (3.9+, one dependency):

```bash
cd examples/python
pip install -r requirements.txt
python quickstart.py --dry-run     # finds a market, prints the order it would place
python quickstart.py               # actually places, polls and cancels
```

**TypeScript** (Node 20.11+, no runtime dependencies — native `fetch`; `tsx` is a dev dependency):

```bash
cd examples/typescript
npm install
npm run quickstart -- --dry-run
npm run quickstart
```

Both default to a **deliberately unmarketable limit order**: a tiny bid far below the
market, `GTC`, so it rests on the book instead of filling, and then gets cancelled. You
see the full lifecycle without taking a position. Pass `--price` / `--quantity` to change
that once you know what you're doing.

Note the `$5` minimum notional on API-key BUY orders (`quantity × price >= 5`), and the
default minimum quantity of 1 share. A 1-share order at $0.01 will be rejected — the
example sizes itself accordingly.

## Your first trade on a specific venue

The quickstart is venue-agnostic — one order schema works everywhere, and you switch
venues by changing `exchange_id`. What differs is how each venue names markets, what
one-time setup it needs, and what it refuses:

- [**Polymarket**](docs/venues/polymarket.md) — CTF outcome tokens on Polygon, USDC
- [**Kalshi**](docs/venues/kalshi.md) — your own Kalshi account, tickers, the only venue with native amend
- [**Predict.fun**](docs/venues/predictfun.md) — BSC, USDT, a 0.001 tick
- [**Hyperliquid**](docs/venues/hyperliquid.md) — HIP-4 side coins, no max price, FOK maps to IOC

[Side-by-side capability table →](docs/venues/README.md)

---

## Four things to get right

Four properties of the API worth building around from the start. Each is expanded in
[`docs/`](docs/).

**1. `200` from `POST /orders` does not mean the order is live.** It means validated,
persisted and *enqueued*. The response `status` is the literal string `queued`. The order
reaches the venue moments later. If you fire and forget, you have no idea what happened.
Poll `GET /orders/{order_id}` or subscribe to the websocket.
→ [`docs/order-lifecycle.md`](docs/order-lifecycle.md)

**2. `price` is required on every order, including market orders.** There is no
market-price sentinel. On a `market` order, `price` is the limit you are willing to cross
to — your slippage bound.

**3. Send a `client_order_id`.** It is your idempotency key. A retry with the same
`(user, exchange_id, market_id, client_order_id)` returns the *existing* order instead of
creating a duplicate, and doesn't consume a rate-limit slot. Without one, the server
generates a random id and your retries are **not** deduped. On a network timeout, that is
the difference between one position and two.

**4. A cancel is confirmed by the order's status, not by the HTTP code.** Kairos
acknowledges the venue's cancel and then verifies the fill state before declaring the
order dead — so `success: false` with `terminal fill verification pending` means "in
progress", not "failed". Poll the order to a terminal status. That barrier is what stops
a fill landing mid-cancel from being lost; it is protection, and it is worth the wait.
→ [`docs/order-lifecycle.md`](docs/order-lifecycle.md)

---

## What Kairos actually exposes

Four public services. The quickstart uses the first two.

| Service | Base URL | What it's for | Auth |
|---|---|---|---|
| **Order Execution** | `execution.kairos.trade` | Order entry, cancel, amend, fee quotes, positions, combos, CTF ops | API key required |
| **Market Data** | `md.kairos.trade` | Markets, candles, trades, marks, tick sizes, resolutions, perps | Anonymous tier |
| **Data API** | `data.kairos.trade` | Search, discovery, PnL, trader stats, sports, top holders | Anonymous tier |

Plus the execution **websocket** at `wss://execution.kairos.trade/ws`: submit and cancel
orders over the socket, and receive `statusChanged` / `partiallyFilled` / `filled` /
`failed` / `positionUpdated` / `balanceUpdated` pushes. That's the low-latency path, and
it's what repo #2 in this series is about.

Machine-readable specs, published and unauthenticated:

```
https://app.kairos.trade/openapi/kairos.json            every service
https://app.kairos.trade/openapi/execution.yaml         order execution
https://app.kairos.trade/openapi/market-data-api.yaml   market data
https://app.kairos.trade/openapi/data-api.yaml          data api
```

Hand `kairos.json` to your agent and it has the entire surface. The interactive reference
with a live request tester is at
[app.kairos.trade/docs/api-reference](https://app.kairos.trade/docs/api-reference).

## Two lanes for signing

- **Custodial** (`POST /orders`) — Kairos signs and routes on your behalf. This is the
  standard path, and what this repo covers.
- **Self-custody** (`POST /v2/orders/intent` → sign → `POST /v2/orders/submit`) — Kairos
  builds the EIP-712 payload, you sign with your own key, submission is synchronous and
  returns the venue's verbatim result. Available to allow-listed institutional accounts on
  Polymarket and Predict.fun. Talk to the Kairos team.

---

## Repo map

```
AGENTS.md                      the API contract, written for an LLM (CLAUDE.md → same file)
docs/authentication.md         the header triple, scopes, key hygiene, rate limits
docs/finding-markets.md        how to get a market_id and token_id per venue
docs/order-lifecycle.md        queued → live → filled/cancelled, and cancel semantics
docs/errors.md                 error shapes and the codes worth branching on
docs/venues/                   first trade on each venue: Polymarket, Kalshi,
                               Predict.fun, Hyperliquid
examples/python/quickstart.py  find → place → poll → cancel
examples/typescript/quickstart.ts
scripts/verify_contract.py     re-derives every claim above from the published OpenAPI
.github/workflows/verify.yml   runs that daily, plus both examples against the live API
.env.example
```

## Next

Once this loop works, the interesting version is event-driven rather than polled: hold the
websocket open, react to `statusChanged` and `filled`, and keep a kill switch on your own
side. That's the next repo.

## License

MIT. This is example code, not investment advice. You are responsible for every order your
key places.
