# Order lifecycle

The single most important thing about the Kairos execution API: **submission is
asynchronous.**

## What `200` means

```
POST /orders  →  200  { "order_id": "...", "status": "queued" }
```

That means: validated, persisted, enqueued. It does **not** mean:

- the order is on the venue
- the order is resting on the book
- anything filled

A worker picks the order up moments later and submits it to the venue. Everything that can
go wrong at the venue — market closed, insufficient balance surfacing late, a venue
rate limit, an allowance problem — happens *after* your `200`.

A client that fires and forgets is flying blind.

## Resolving the real state

**Polling** (what this repo's examples do — simplest, good enough to start):

```
GET /orders/{order_id}   →  Order, with `status` and `filled_quantity`
```

Poll on a sane interval (the examples use ~500ms with a timeout), until `status` is
terminal.

**WebSocket** (lowest latency — the production path):

```
wss://execution.kairos.trade/ws
```

Pushes `statusChanged`, `partiallyFilled`, `filled`, `failed`, `positionUpdated`,
`balanceUpdated`. You can also submit and cancel over the socket. This is where repo #2
goes.

## Statuses

| Status | Terminal | Meaning |
|---|---|---|
| `pending` | no | accepted, not yet live on the venue |
| `live` | no | resting on the venue's book |
| `partial` | no | partially filled, remainder still working |
| `filled` | **yes** | fully filled |
| `cancelled` | **yes** | cancelled |
| `expired` | **yes** | GTD expiry |
| `failed` | **yes** | rejected or errored |

Two details worth knowing:

- The wire spelling of a partial fill is **`partial`**, not `partially_filled`.
- An order in flight can report any of the internal working states — `pending` and
  `executing` are both normal while the worker submits to the venue. Write your status
  check as "is this one of my terminal states?" rather than switch-casing on an
  exhaustive list, and new states can never break your client.

## The lifecycle, end to end

A full run against Polymarket, using the example in this repo:

```
POST /orders                     → 200  status=queued
GET  /orders/{id}                → executing        submitting to the venue
GET  /orders/{id}                → live             resting on the venue book
POST /orders/{id}/cancel         → 200  success=false
                                   "Venue accepted cancellation;
                                    terminal fill verification pending"
GET  /orders/{id}                → live             verification in progress
GET  /orders/{id}                → cancelled        terminal
```

Two lessons, and they are the same lesson: **the order's status is the source of truth,
at both ends.** A `200` on submit means queued, not live. A cancel acknowledgement means
the venue took it, not that the order is dead. Poll the status — or hold the websocket
open, which gives you the same transitions without the polling.

Budget for the verification step rather than racing it. An order stays `live` for a
short window after the venue accepts the cancel, while Kairos confirms exactly what
filled. A bot that assumes "cancel returned" means "order gone" will under-count its own
exposure during that window.

## Idempotency

Send a `client_order_id` on every submit. The dedup key is
`(user, exchange_id, market_id, client_order_id)`.

A replay with the same tuple returns the **existing** order rather than creating a second
one, and is resolved *before* the rate limiter, so it never consumes a slot.

Without one, the server generates a random id, and a retried request is a new order.
Consider a submit that times out at the network layer: the order may well have been
accepted. With `client_order_id`, retrying is free and correct. Without it, retrying may
double your position.

Generate it client-side (a UUID4 is fine), store it alongside your intent *before* you
send, and reuse it for the whole retry sequence.

## Cancelling

```
POST /orders/{order_id}/cancel
```

**Returns `200` even when it didn't cancel.** Non-2xx is reserved for auth, ownership,
not-found and infrastructure — not for "the cancel didn't happen."

```json
{
  "success": false,
  "order_id": "...",
  "venue_reconciled": false,
  "message": "Order is being submitted to exchange. Please try again in a moment."
}
```

- `success: true` — cancelled **and** terminal fill verification complete.
- `success: false` — either the order was already terminal, or verification is still in
  progress. Read `message`.

`Venue accepted cancellation; terminal fill verification pending` is the in-progress
case, and it is the common one: the venue has taken the cancel and Kairos is confirming
the exact fill state before calling the order dead. **Poll the order to a terminal
status** rather than re-issuing the cancel — a second cancel in that window just reports
the state the poll would have told you.

The order's status and the verification receipt answer different questions, and they do
not arrive together. Use the **status** to know the order is dead; use the receipt's
`final_filled_quantity` to know how much filled.

### The cancel-before-submit race

If the order hasn't reached the venue yet, it is cancelled locally via an atomic
conditional update that races safely against the in-flight submission. If the submission
wins, you get `success: false` asking you to retry shortly. Nothing is lost; just try
again.

### Fill-during-cancel

A venue cancel acknowledgement is followed by terminal fill verification. Until the
response carries `terminal_fill_verification.state: "complete"`, **keep any protective
logic active** — a fill may have landed in the gap.

- `filled_quantity` being absent is not zero. Do not infer it.
- `final_filled_quantity` on the completed receipt is the authoritative venue cumulative,
  never the latest fill delta, and it is published only after the corresponding
  trade/position fold.
- Kalshi may complete this synchronously; other venues typically complete through the
  polling worker, so the receipt shows up on a retry or on `GET /orders/{order_id}`.

### Batch cancels

- `POST /orders/cancel-batch` — a specific set of order ids.
- `POST /orders/cancel-all` — everything, optionally filtered. This is your panic button;
  wire it to something you can hit fast.

## Amending

`POST /orders/{order_id}/amend` reprices a resting limit order in one venue round trip,
keeping both the Kairos `order_id` and the venue order id. That's the point: no
supersession to reconcile, no second order whose fill could be booked twice.

- Only on venues advertising `supports_native_amend` (today: **Kalshi**). Anything else is
  `409 EXCHANGE_AMEND_UNSUPPORTED`.
- **Reprice only.** `quantity` is accepted solely to be refused with
  `409 EXCHANGE_AMEND_QUANTITY_UNSUPPORTED` — refused rather than silently ignored, so you
  never believe you resized when you didn't.
- There is deliberately no internal cancel-and-replace fallback. That substitution changes
  queue position and order identity, so it's your decision to make, explicitly.

## A correct submit loop

```
1. build intent, generate client_order_id, persist it locally
2. POST /orders
     - 2xx        → record order_id
     - timeout    → retry with the SAME client_order_id
     - 429        → back off (no Retry-After header exists), then retry
     - 4xx        → read error_details.code, fix or abandon; do not blind-retry
3. poll GET /orders/{order_id} until terminal, with a deadline
4. on deadline: cancel, then re-check status — the cancel may have raced a fill
5. reconcile filled_quantity into your own position book
```
