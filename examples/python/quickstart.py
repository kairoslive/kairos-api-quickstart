#!/usr/bin/env python3
"""Kairos API quickstart: find a market, place a limit order, poll it, cancel it.

Run `python quickstart.py --dry-run` first — it does every read-only step and prints
the order it would submit, without sending it.

Credentials come from the environment (or a .env file at the repo root):
    KAIROS_CLIENT_ID / KAIROS_API_KEY / KAIROS_CLIENT_SECRET

Those are the names the "Copy all as .env" button in Settings -> API Tokens produces.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

import requests

EXECUTION_URL = os.environ.get("KAIROS_EXECUTION_URL", "https://execution.kairos.trade")
MARKET_DATA_URL = os.environ.get("KAIROS_MARKET_DATA_URL", "https://md.kairos.trade")

# A deliberately unmarketable resting bid: 1 cent on a market that isn't trading at
# 1 cent, so it rests on the book instead of filling. 600 x $0.01 = $6.00, which clears
# the $5 minimum notional that applies to API-key BUY orders.
DEFAULT_PRICE = "0.01"
DEFAULT_QUANTITY = "600"

TERMINAL_STATUSES = {"filled", "cancelled", "expired", "failed"}


class KairosError(RuntimeError):
    pass


class KairosClient:
    """Thin wrapper over the two services this quickstart touches."""

    def __init__(self, client_id: str, api_key: str, api_secret: str) -> None:
        self._session = requests.Session()
        # All three headers are required on every authenticated request. A partial set
        # is a 401 — it does not fall back to the anonymous tier.
        self._session.headers.update(
            {
                "X-Client-Id": client_id,
                "X-Api-Key": api_key,
                "X-Api-Secret": api_secret,
                "Content-Type": "application/json",
            }
        )

    # -- market data (no credentials needed, but harmless to send them) ------------

    @staticmethod
    def list_markets(provider: str, limit: int = 20) -> list[dict]:
        resp = requests.get(
            f"{MARKET_DATA_URL}/v1/markets",
            params={"provider": provider, "limit": limit},
            timeout=15,
        )
        if resp.status_code == 503:
            # The provider's active-market listing hasn't been populated yet. Not a
            # problem with the request — retry shortly.
            raise KairosError(
                f"{provider} listing is warming up (cache_cold). Try another provider "
                f"or retry in a few seconds."
            )
        resp.raise_for_status()
        return resp.json().get("markets", [])

    # -- execution ----------------------------------------------------------------

    def submit_order(self, body: dict) -> dict:
        resp = self._session.post(f"{EXECUTION_URL}/orders", json=body, timeout=30)
        if resp.status_code != 200:
            raise KairosError(f"submit failed: {describe_error(resp)}")
        return resp.json()

    def get_order(self, order_id: str) -> dict:
        resp = self._session.get(f"{EXECUTION_URL}/orders/{order_id}", timeout=15)
        if resp.status_code != 200:
            raise KairosError(f"read failed: {describe_error(resp)}")
        return resp.json()

    def cancel_order(self, order_id: str) -> dict:
        resp = self._session.post(
            f"{EXECUTION_URL}/orders/{order_id}/cancel", timeout=30
        )
        if resp.status_code != 200:
            raise KairosError(f"cancel failed: {describe_error(resp)}")
        # A 200 here does NOT mean the order was cancelled — read `success`.
        return resp.json()


def describe_error(resp: requests.Response) -> str:
    """Several error body shapes are in use, and some endpoints send no body at all."""
    detail = ""
    try:
        payload = resp.json()
        if isinstance(payload, dict):
            details = payload.get("error_details") or {}
            code = details.get("code") or payload.get("code")
            message = details.get("message") or payload.get("error") or payload
            detail = f" {code}: {message}" if code else f" {message}"
    except ValueError:
        if resp.text:
            detail = f" {resp.text[:200]}"
    return f"HTTP {resp.status_code}{detail}"


def load_dotenv() -> None:
    """Minimal .env reader so the example has one dependency instead of two."""
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
        return


def credentials() -> tuple[str, str, str]:
    load_dotenv()
    # The settings UI calls the third value the "Client secret" and its "Copy all as
    # .env" button emits KAIROS_CLIENT_SECRET; the header it becomes is X-Api-Secret.
    # Accept either spelling so a pasted .env works as-is.
    secret = os.environ.get("KAIROS_CLIENT_SECRET") or os.environ.get("KAIROS_API_SECRET", "")
    values = [
        os.environ.get("KAIROS_CLIENT_ID", ""),
        os.environ.get("KAIROS_API_KEY", ""),
        secret,
    ]
    if not all(values):
        sys.exit(
            "Missing credentials. Copy .env.example to .env and fill in\n"
            "KAIROS_CLIENT_ID, KAIROS_API_KEY and KAIROS_CLIENT_SECRET.\n"
            "Create one at kairos.trade → profile picture → Settings → API Tokens,\n"
            "then use the dialog's 'Copy all as .env' button."
        )
    return values[0], values[1], values[2]


def pick_market(markets: list[dict], outcome_label: str) -> tuple[dict, dict]:
    """First market that exposes the requested outcome with a usable token id."""
    wanted = outcome_label.strip().lower()
    for market in markets:
        for outcome in market.get("outcomes") or []:
            normalized = (outcome.get("normalized_outcome") or outcome.get("outcome") or "").lower()
            if normalized == wanted and outcome.get("token_id"):
                return market, outcome
    raise KairosError(f"no market in this page has a '{outcome_label}' outcome")


def poll_until(
    client: KairosClient,
    order_id: str,
    deadline_s: float,
    stop_at: set[str] = TERMINAL_STATUSES | {"live"},
) -> dict:
    """Poll until the order reaches one of `stop_at`, or the deadline passes.

    Note `executing`: the spec lists it among the internal states, and you do see it
    come back from GET while the worker is submitting to the venue. Treat any status
    outside your stop set as "still working".
    """
    started = time.monotonic()
    order = {}
    while time.monotonic() - started < deadline_s:
        order = client.get_order(order_id)
        status = order.get("status")
        filled = order.get("filled_quantity", "0")
        print(f"   status={status} filled={filled}")
        if status in stop_at:
            return order
        time.sleep(1.0)
    return order


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="polymarket",
                        help="polymarket | kalshi | predictfun | hyperliquid")
    parser.add_argument("--outcome", default="yes", help="outcome to bid on (default: yes)")
    parser.add_argument("--market-id", help="target a specific market instead of the first listed")
    parser.add_argument("--token-id", help="outcome token id; required with --market-id")
    parser.add_argument("--price", default=DEFAULT_PRICE, help="limit price, 0-1 scale")
    parser.add_argument("--quantity", default=DEFAULT_QUANTITY, help="shares")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds to poll for the venue ack")
    parser.add_argument("--cancel-timeout", type=float, default=60.0,
                        help="seconds to wait for a cancel to settle to a terminal state")
    parser.add_argument("--dry-run", action="store_true",
                        help="do the read-only steps and print the order, submit nothing")
    args = parser.parse_args()

    notional = float(args.price) * float(args.quantity)
    if notional < 5:
        print(f"! notional is ${notional:.2f}; API-key BUY orders require >= $5.00")

    # ---- 1. find a market (no credentials needed) ------------------------------
    if args.market_id:
        if not args.token_id:
            sys.exit("--market-id requires --token-id (it selects which outcome you are buying)")
        print(f"1. using the market you named ...")
        market = {"market_id": args.market_id, "title": None}
        outcome = {"outcome": args.outcome.title(), "token_id": args.token_id}
    else:
        print(f"1. listing active {args.provider} markets ...")
        markets = KairosClient.list_markets(args.provider)
        market, outcome = pick_market(markets, args.outcome)
    print(f"   {market.get('title') or market['market_id']}")
    print(f"   market_id={market['market_id']}  outcome={outcome['outcome']}")
    print(f"   token_id={outcome['token_id']}")

    # ---- 2. build the order ----------------------------------------------------
    # client_order_id is the idempotency key. Generate it BEFORE sending, and reuse
    # the same value on every retry so a timeout can't become two positions.
    body = {
        "exchange_id": args.provider,
        "market_id": str(market["market_id"]),
        "token_id": str(outcome["token_id"]),
        "outcome": outcome["outcome"],
        "side": "buy",
        "kind": "limit",
        "quantity": str(args.quantity),   # decimal strings, not floats
        "price": str(args.price),         # required on EVERY order, including market
        "time_in_force": "GTC",
        "client_order_id": str(uuid.uuid4()),
        "source": "api",
    }
    print(f"\n2. order to submit (${notional:.2f} notional):")
    for key, value in body.items():
        print(f"   {key}: {value}")

    if args.dry_run:
        print("\n--dry-run: stopping here. Nothing was sent.")
        return 0

    client = KairosClient(*credentials())

    # ---- 3. submit -------------------------------------------------------------
    print("\n3. submitting ...")
    ack = client.submit_order(body)
    order_id = ack["order_id"]
    # A 200 means validated + persisted + ENQUEUED. Not live on the venue yet.
    print(f"   order_id={order_id} status={ack['status']}  (queued != live)")

    # ---- 4. poll to a real state ----------------------------------------------
    print("\n4. polling for the venue's answer ...")
    order = poll_until(client, order_id, args.timeout)
    if order.get("status") in TERMINAL_STATUSES:
        print(f"   order reached terminal state '{order['status']}' — nothing to cancel")
        return 0

    # ---- 5. cancel -------------------------------------------------------------
    print("\n5. cancelling ...")
    result = client.cancel_order(order_id)
    print(f"   success={result.get('success')} message={result.get('message')}")

    if not result.get("success"):
        # This is the NORMAL first response, not an error: the venue accepted the
        # cancel but terminal fill verification is still pending, so Kairos will not
        # yet claim the order is dead. The order row stays `live` for a few seconds
        # and then folds to `cancelled`. Poll it out — do not assume either outcome,
        # because a fill can still land in this window.
        print("   not confirmed yet — polling the order to a terminal state")
        final = poll_until(client, order_id, args.cancel_timeout, TERMINAL_STATUSES)
        status = final.get("status")
        if status not in TERMINAL_STATUSES:
            print(f"   STILL WORKING after {args.cancel_timeout:.0f}s (status={status}).")
            print("   Keep any protective logic active and retry the cancel.")
            return 1
        filled = final.get("filled_quantity", "0")
        print(f"   settled: status={status} filled={filled}")
        if float(filled or 0) > 0:
            # A partial fill landed before the cancel did. This is a real position.
            print(f"   NOTE: {filled} shares filled before the cancel — you hold a position.")
        return 0

    print("\nDone. Found a market, placed a resting bid, and cancelled it.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KairosError as exc:
        sys.exit(f"error: {exc}")
    except KeyboardInterrupt:
        sys.exit(130)
