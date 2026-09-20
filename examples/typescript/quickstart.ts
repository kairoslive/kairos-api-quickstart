/**
 * Kairos API quickstart: find a market, place a limit order, poll it, cancel it.
 *
 * Run `npm run quickstart -- --dry-run` first — it does every read-only step and
 * prints the order it would submit, without sending it.
 *
 * Credentials come from the environment (or a .env file at the repo root):
 *   KAIROS_CLIENT_ID / KAIROS_API_KEY / KAIROS_CLIENT_SECRET
 *
 * Those are the names the "Copy all as .env" button in Settings -> API Tokens produces.
 */

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";

const EXECUTION_URL = process.env.KAIROS_EXECUTION_URL ?? "https://execution.kairos.trade";
const MARKET_DATA_URL = process.env.KAIROS_MARKET_DATA_URL ?? "https://md.kairos.trade";

// A deliberately unmarketable resting bid: 1 cent on a market that isn't trading at
// 1 cent, so it rests on the book instead of filling. 600 x $0.01 = $6.00, which clears
// the $5 minimum notional that applies to API-key BUY orders.
const DEFAULT_PRICE = "0.01";
const DEFAULT_QUANTITY = "600";

const TERMINAL_STATUSES = new Set(["filled", "cancelled", "expired", "failed"]);

interface Outcome {
  outcome: string;
  normalized_outcome?: string;
  token_id?: string;
  outcome_index?: number;
}

interface Market {
  market_id: string;
  title?: string;
  outcomes?: Outcome[];
}

interface OrderSubmitResponse {
  order_id: string;
  status: string;
}

interface Order {
  status?: string;
  filled_quantity?: string;
}

interface CancelResponse {
  success?: boolean;
  message?: string;
  filled_quantity?: string | null;
}

class KairosError extends Error {}

/** Several error body shapes are in use, and some endpoints send no body at all. */
async function describeError(resp: Response): Promise<string> {
  const text = await resp.text().catch(() => "");
  if (!text) return `HTTP ${resp.status}`;
  try {
    const payload = JSON.parse(text);
    const details = payload?.error_details ?? {};
    const code = details.code ?? payload?.code;
    const message = details.message ?? payload?.error ?? text;
    return code ? `HTTP ${resp.status} ${code}: ${message}` : `HTTP ${resp.status} ${message}`;
  } catch {
    return `HTTP ${resp.status} ${text.slice(0, 200)}`;
  }
}

class KairosClient {
  // All three headers are required on every authenticated request. A partial set is a
  // 401 — it does not fall back to the anonymous tier.
  private readonly headers: Record<string, string>;

  constructor(clientId: string, apiKey: string, apiSecret: string) {
    this.headers = {
      "X-Client-Id": clientId,
      "X-Api-Key": apiKey,
      "X-Api-Secret": apiSecret,
      "Content-Type": "application/json",
    };
  }

  /** Market data needs no credentials. */
  static async listMarkets(provider: string, limit = 20): Promise<Market[]> {
    const url = `${MARKET_DATA_URL}/v1/markets?provider=${encodeURIComponent(provider)}&limit=${limit}`;
    const resp = await fetch(url);
    if (resp.status === 503) {
      // The provider's active-market listing hasn't been populated yet. Not a problem
      // with the request — retry shortly.
      throw new KairosError(
        `${provider} listing is warming up (cache_cold). Try another provider or retry in a few seconds.`,
      );
    }
    if (!resp.ok) throw new KairosError(await describeError(resp));
    const body = (await resp.json()) as { markets?: Market[] };
    return body.markets ?? [];
  }

  async submitOrder(body: unknown): Promise<OrderSubmitResponse> {
    const resp = await fetch(`${EXECUTION_URL}/orders`, {
      method: "POST",
      headers: this.headers,
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new KairosError(`submit failed: ${await describeError(resp)}`);
    return (await resp.json()) as OrderSubmitResponse;
  }

  async getOrder(orderId: string): Promise<Order> {
    const resp = await fetch(`${EXECUTION_URL}/orders/${orderId}`, { headers: this.headers });
    if (!resp.ok) throw new KairosError(`read failed: ${await describeError(resp)}`);
    return (await resp.json()) as Order;
  }

  async cancelOrder(orderId: string): Promise<CancelResponse> {
    const resp = await fetch(`${EXECUTION_URL}/orders/${orderId}/cancel`, {
      method: "POST",
      headers: this.headers,
    });
    if (!resp.ok) throw new KairosError(`cancel failed: ${await describeError(resp)}`);
    // A 200 here does NOT mean the order was cancelled — read `success`.
    return (await resp.json()) as CancelResponse;
  }
}

/** Minimal .env reader so the example has no runtime dependencies. */
function loadDotenv(): void {
  for (const candidate of [resolve(process.cwd(), ".env"), resolve(import.meta.dirname, "../../.env")]) {
    if (!existsSync(candidate)) continue;
    for (const line of readFileSync(candidate, "utf8").split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
      const index = trimmed.indexOf("=");
      const key = trimmed.slice(0, index).trim();
      const value = trimmed.slice(index + 1).trim().replace(/^['"]|['"]$/g, "");
      if (process.env[key] === undefined) process.env[key] = value;
    }
    return;
  }
}

function credentials(): [string, string, string] {
  loadDotenv();
  // The settings UI calls the third value the "Client secret" and its "Copy all as .env"
  // button emits KAIROS_CLIENT_SECRET; the header it becomes is X-Api-Secret. Accept
  // either spelling so a pasted .env works as-is.
  const secret = process.env.KAIROS_CLIENT_SECRET || process.env.KAIROS_API_SECRET || "";
  const values: [string, string, string] = [
    process.env.KAIROS_CLIENT_ID ?? "",
    process.env.KAIROS_API_KEY ?? "",
    secret,
  ];
  if (values.some((value) => !value)) {
    console.error(
      "Missing credentials. Copy .env.example to .env and fill in\n" +
        "KAIROS_CLIENT_ID, KAIROS_API_KEY and KAIROS_CLIENT_SECRET.\n" +
        "Create one at kairos.trade → profile picture → Settings → API Tokens,\n" +
        "then use the dialog's 'Copy all as .env' button.",
    );
    process.exit(1);
  }
  return values;
}

function pickMarket(markets: Market[], outcomeLabel: string): [Market, Outcome] {
  const wanted = outcomeLabel.trim().toLowerCase();
  for (const market of markets) {
    for (const outcome of market.outcomes ?? []) {
      const normalized = (outcome.normalized_outcome ?? outcome.outcome ?? "").toLowerCase();
      if (normalized === wanted && outcome.token_id) return [market, outcome];
    }
  }
  throw new KairosError(`no market in this page has a '${outcomeLabel}' outcome`);
}

const sleep = (ms: number) => new Promise((done) => setTimeout(done, ms));

/**
 * Poll until the order reaches one of `stopAt`, or the deadline passes.
 *
 * Note `executing`: the spec lists it among the internal states, and you do see it come
 * back from GET while the worker is submitting to the venue. Treat any status outside
 * your stop set as "still working".
 */
async function pollUntil(
  client: KairosClient,
  orderId: string,
  deadlineMs: number,
  stopAt: Set<string> = new Set([...TERMINAL_STATUSES, "live"]),
): Promise<Order> {
  const started = Date.now();
  let order: Order = {};
  while (Date.now() - started < deadlineMs) {
    order = await client.getOrder(orderId);
    console.log(`   status=${order.status} filled=${order.filled_quantity ?? "0"}`);
    if (order.status && stopAt.has(order.status)) return order;
    await sleep(1000);
  }
  return order;
}

function arg(name: string, fallback: string): string {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : fallback;
}

async function main(): Promise<number> {
  const provider = arg("provider", "polymarket");
  const marketIdArg = arg("market-id", "");
  const tokenIdArg = arg("token-id", "");
  const outcomeLabel = arg("outcome", "yes");
  const price = arg("price", DEFAULT_PRICE);
  const quantity = arg("quantity", DEFAULT_QUANTITY);
  const timeoutMs = Number(arg("timeout", "20")) * 1000;
  const cancelTimeoutMs = Number(arg("cancel-timeout", "60")) * 1000;
  const dryRun = process.argv.includes("--dry-run");

  const notional = Number(price) * Number(quantity);
  if (notional < 5) {
    console.log(`! notional is $${notional.toFixed(2)}; API-key BUY orders require >= $5.00`);
  }

  // ---- 1. find a market (no credentials needed) ------------------------------
  let market: Market;
  let outcome: Outcome;
  if (marketIdArg) {
    if (!tokenIdArg) {
      console.error("--market-id requires --token-id (it selects which outcome you are buying)");
      return 1;
    }
    console.log("1. using the market you named ...");
    market = { market_id: marketIdArg };
    outcome = { outcome: outcomeLabel.charAt(0).toUpperCase() + outcomeLabel.slice(1), token_id: tokenIdArg };
  } else {
    console.log(`1. listing active ${provider} markets ...`);
    const markets = await KairosClient.listMarkets(provider);
    [market, outcome] = pickMarket(markets, outcomeLabel);
  }
  console.log(`   ${market.title ?? market.market_id}`);
  console.log(`   market_id=${market.market_id}  outcome=${outcome.outcome}`);
  console.log(`   token_id=${outcome.token_id}`);

  // ---- 2. build the order ----------------------------------------------------
  // client_order_id is the idempotency key. Generate it BEFORE sending, and reuse the
  // same value on every retry so a timeout can't become two positions.
  const body = {
    exchange_id: provider,
    market_id: String(market.market_id),
    token_id: String(outcome.token_id),
    outcome: outcome.outcome,
    side: "buy",
    kind: "limit",
    quantity: String(quantity), // decimal strings, not floats
    price: String(price), // required on EVERY order, including market
    time_in_force: "GTC",
    client_order_id: randomUUID(),
    source: "api",
  };
  console.log(`\n2. order to submit ($${notional.toFixed(2)} notional):`);
  for (const [key, value] of Object.entries(body)) console.log(`   ${key}: ${value}`);

  if (dryRun) {
    console.log("\n--dry-run: stopping here. Nothing was sent.");
    return 0;
  }

  const client = new KairosClient(...credentials());

  // ---- 3. submit -------------------------------------------------------------
  console.log("\n3. submitting ...");
  const ack = await client.submitOrder(body);
  // A 200 means validated + persisted + ENQUEUED. Not live on the venue yet.
  console.log(`   order_id=${ack.order_id} status=${ack.status}  (queued != live)`);

  // ---- 4. poll to a real state ----------------------------------------------
  console.log("\n4. polling for the venue's answer ...");
  const order = await pollUntil(client, ack.order_id, timeoutMs);
  if (order.status && TERMINAL_STATUSES.has(order.status)) {
    console.log(`   order reached terminal state '${order.status}' — nothing to cancel`);
    return 0;
  }

  // ---- 5. cancel -------------------------------------------------------------
  console.log("\n5. cancelling ...");
  const result = await client.cancelOrder(ack.order_id);
  console.log(`   success=${result.success} message=${result.message}`);

  if (!result.success) {
    // This is the NORMAL first response, not an error: the venue accepted the cancel
    // but terminal fill verification is still pending, so Kairos will not yet claim the
    // order is dead. The order row stays `live` for a few seconds and then folds to
    // `cancelled`. Poll it out — do not assume either outcome, because a fill can still
    // land in this window.
    console.log("   not confirmed yet — polling the order to a terminal state");
    const final = await pollUntil(client, ack.order_id, cancelTimeoutMs, TERMINAL_STATUSES);
    if (!final.status || !TERMINAL_STATUSES.has(final.status)) {
      console.log(`   STILL WORKING after ${cancelTimeoutMs / 1000}s (status=${final.status}).`);
      console.log("   Keep any protective logic active and retry the cancel.");
      return 1;
    }
    const filled = final.filled_quantity ?? "0";
    console.log(`   settled: status=${final.status} filled=${filled}`);
    if (Number(filled) > 0) {
      // A partial fill landed before the cancel did. This is a real position.
      console.log(`   NOTE: ${filled} shares filled before the cancel — you hold a position.`);
    }
    return 0;
  }

  console.log("\nDone. Found a market, placed a resting bid, and cancelled it.");
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(error instanceof KairosError ? `error: ${error.message}` : error);
    process.exit(1);
  });
