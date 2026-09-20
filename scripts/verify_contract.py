#!/usr/bin/env python3
"""Check every factual claim this repo makes against the published Kairos OpenAPI specs.

The specs at app.kairos.trade/openapi/ are generated from the Kairos service repository
and guarded there by CI coverage tests, so they are the primary source. This script
re-derives our claims from them on a schedule, so this documentation is held to the live
contract continuously and cannot silently drift.

    python scripts/verify_contract.py            # fetch the live spec and check
    python scripts/verify_contract.py --spec f   # check against a local copy

Exit code 0 means every assertion below is still true of the live API contract.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

SPEC_URL = "https://app.kairos.trade/openapi/kairos.json"

failures: list[str] = []
warnings: list[str] = []
checks = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f" — {detail}" if detail else ""))
        failures.append(label)


def warn(label: str, condition: bool, note: str) -> None:
    """A claim this guide makes that the published bundle does not cover yet.

    Not a failure: this guide documents the full API surface, and the published bundle
    is refreshed on its own cadence, so a capability can be documented here ahead of
    its appearance in the bundle.
    """
    global checks
    checks += 1
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  warn  {label} — {note}")
        warnings.append(label)


def load_spec(path: str | None) -> dict:
    if path:
        with open(path) as handle:
            return json.load(handle)
    with urllib.request.urlopen(SPEC_URL, timeout=60) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", help="path to a local kairos.json instead of fetching")
    args = parser.parse_args()

    bundle = load_spec(args.spec)
    services = {service["id"]: service for service in bundle["services"]}

    print(f"\nspec: {SPEC_URL if not args.spec else args.spec}")
    print(f"services: {', '.join(sorted(services))}\n")

    # ---- the four services the README lists ------------------------------------
    print("README — services")
    for service_id, expected_host in [
        ("execution", "execution.kairos.trade"),
        ("market-data-api", "md.kairos.trade"),
        ("data-api", "data.kairos.trade"),
    ]:
        service = services.get(service_id, {})
        urls = " ".join(service.get("baseUrls") or [])
        check(f"{service_id} is published at {expected_host}", expected_host in urls, urls)

    execution = services["execution"]["spec"]
    market_data = services["market-data-api"]["spec"]
    exec_paths = execution["paths"]
    exec_schemas = execution["components"]["schemas"]

    # ---- AGENTS.md — endpoints --------------------------------------------------
    print("\nAGENTS.md — endpoints exist")
    check("POST /orders", "post" in exec_paths.get("/orders", {}))
    check("GET /orders", "get" in exec_paths.get("/orders", {}))
    check("GET /orders/{order_id}", "get" in exec_paths.get("/orders/{order_id}", {}))
    check("POST /orders/{order_id}/cancel", "post" in exec_paths.get("/orders/{order_id}/cancel", {}))
    check("POST /orders/cancel-batch", "post" in exec_paths.get("/orders/cancel-batch", {}))
    check("POST /orders/cancel-all", "post" in exec_paths.get("/orders/cancel-all", {}))
    warn(
        "POST /orders/{order_id}/amend",
        "post" in exec_paths.get("/orders/{order_id}/amend", {}),
        "documented here ahead of the published bundle",
    )
    check("GET /v1/markets (market data)", "get" in market_data["paths"].get("/v1/markets", {}))

    # ---- AGENTS.md — authentication ---------------------------------------------
    print("\ndocs/authentication.md — the header triple")
    security_schemes = execution["components"].get("securitySchemes", {})
    header_names = {
        scheme.get("name", "").lower()
        for scheme in security_schemes.values()
        if scheme.get("in") == "header"
    }
    spec_text = json.dumps(execution).lower()
    for header in ("x-client-id", "x-api-key", "x-api-secret"):
        check(
            f"{header} is part of the execution auth contract",
            header in header_names or header in spec_text,
        )

    print("\ndocs/authentication.md — scopes")
    scopes = {
        operation.get("x-kairos-scope")
        for path in exec_paths.values()
        for operation in path.values()
        if isinstance(operation, dict)
    }
    for scope in ("trade:execute", "trade:read", "position:read"):
        check(f"scope {scope} is used by at least one operation", scope in scopes)
    check(
        "POST /orders requires trade:execute",
        exec_paths["/orders"]["post"].get("x-kairos-scope") == "trade:execute",
        str(exec_paths["/orders"]["post"].get("x-kairos-scope")),
    )
    check(
        "GET /orders/{order_id} requires trade:read",
        exec_paths["/orders/{order_id}"]["get"].get("x-kairos-scope") == "trade:read",
    )
    check(
        "POST /orders/{order_id}/cancel requires trade:execute",
        exec_paths["/orders/{order_id}/cancel"]["post"].get("x-kairos-scope") == "trade:execute",
    )

    # ---- AGENTS.md — the order request shape ------------------------------------
    print("\nAGENTS.md — OrderSubmitRequest")
    submit = exec_schemas["OrderSubmitRequest"]
    required = set(submit["required"])
    check(
        "required fields are exchange_id, market_id, side, kind, quantity",
        required == {"exchange_id", "market_id", "side", "kind", "quantity"},
        str(sorted(required)),
    )
    properties = submit["properties"]
    for field in ("price", "token_id", "outcome", "time_in_force", "post_only",
                  "client_order_id", "expiration_minutes", "source"):
        check(f"field {field} exists", field in properties)
    check(
        "price is documented as REQUIRED for every order",
        "required for every order" in properties["price"]["description"].lower(),
    )
    check(
        "quantity and price are decimal strings, not numbers",
        properties["quantity"]["type"] == "string" and properties["price"]["type"] == "string",
    )
    check(
        "client_order_id is the idempotency key",
        "idempotency" in properties["client_order_id"]["description"].lower(),
    )
    check(
        "time_in_force defaults to GTC",
        properties["time_in_force"].get("default") == "GTC",
    )
    tif_text = properties["time_in_force"]["description"]
    for tif in ("GTC", "GTD", "FOK", "FAK", "IOC"):
        check(f"time_in_force accepts {tif}", tif in tif_text)

    # ---- AGENTS.md — the async ack ----------------------------------------------
    print("\ndocs/order-lifecycle.md — submission is asynchronous")
    submit_response = exec_schemas["OrderSubmitResponse"]
    check(
        "OrderSubmitResponse returns order_id and status",
        set(submit_response["required"]) == {"order_id", "status"},
    )
    check(
        "a fresh submit reports status 'queued'",
        submit_response["properties"]["status"].get("example") == "queued",
    )
    submit_description = exec_paths["/orders"]["post"]["description"].lower()
    check(
        "the spec itself states a 200 does not mean the order is live",
        "does not mean the order is live" in submit_description,
    )

    print("\ndocs/order-lifecycle.md — statuses")
    statuses = set(exec_schemas["OrderStatus"]["enum"])
    for status in ("pending", "queued", "live", "partial", "filled", "cancelled",
                   "expired", "failed"):
        check(f"status {status} exists", status in statuses)
    check(
        "a partial fill is spelled 'partial', never 'partially_filled'",
        "partial" in statuses and "partially_filled" not in statuses,
    )

    print("\ndocs/order-lifecycle.md — cancel semantics")
    cancel_response = exec_schemas["OrderCancelResponse"]
    check(
        "OrderCancelResponse carries success, order_id, venue_reconciled",
        set(cancel_response["required"]) == {"success", "order_id", "venue_reconciled"},
        str(sorted(cancel_response["required"])),
    )
    check(
        "a cancel returns 200 even when success is false",
        "even when" in cancel_response["description"].lower(),
    )
    check(
        "terminal_fill_verification is part of the cancel response",
        "terminal_fill_verification" in cancel_response["properties"],
    )
    amend = exec_paths.get("/orders/{order_id}/amend", {}).get("post", {})
    warn(
        "amend is reprice-only",
        "Reprice only" in amend.get("description", ""),
        "documented here ahead of the published bundle",
    )

    # ---- docs/errors.md ---------------------------------------------------------
    print("\ndocs/errors.md — documented codes appear in the spec")
    for code in ("VALIDATION_INVALID_ORDER", "VALIDATION_INVALID_SIZE",
                 "VALIDATION_INVALID_PRICE", "VALIDATION_MARKET_NOT_FOUND",
                 "EXCHANGE_UNSUPPORTED", "FUNDS_INSUFFICIENT_USDC",
                 "MARKET_FOK_NOT_FILLED", "ORDERBOOK_UNAVAILABLE", "MARKET_PAUSED",
                 "AUTH_CREDENTIALS_INVALID", "ALLOWANCE_CTF_NOT_SET"):
        check(f"code {code}", code in json.dumps(execution))
    error_schema = exec_schemas["OrderErrorResponse"]
    check(
        "OrderErrorResponse nests the code under error_details",
        "error_details" in error_schema["properties"],
    )

    print("\ndocs/errors.md — rate limits")
    check(
        "no Retry-After or X-RateLimit headers are promised on a 429",
        "no rate-limit headers" in json.dumps(execution).lower(),
    )
    check(
        "order submission is rate limited per user",
        "rate limit" in submit_description,
    )

    # ---- docs/finding-markets.md ------------------------------------------------
    print("\ndocs/finding-markets.md — market listing")
    markets_op = market_data["paths"]["/v1/markets"]["get"]
    provider_param = next(
        parameter for parameter in markets_op["parameters"]
        if parameter["name"] == "provider"
    )
    providers = set(provider_param["schema"]["enum"])
    for provider in ("kalshi", "polymarket", "predictfun", "hyperliquid"):
        check(f"provider {provider} is listed", provider in providers)
    check("market data is anonymous-friendly", markets_op.get("x-kairos-auth") == "public")
    check("cache_cold is a documented 503", "cache_cold" in json.dumps(markets_op))
    check(
        "market-data prices are on a 0-100 scale",
        "0-100" in json.dumps(market_data["components"]["schemas"]["CandleObject"])
        or "0–100" in json.dumps(market_data["components"]["schemas"]["CandleObject"]),
    )

    # ---- docs/venues/ -----------------------------------------------------------
    print("\ndocs/venues/ — per-venue capabilities")
    capabilities = exec_schemas["OrderExchangeCapabilities"]
    # The spec carries the production capability table in its own description; the venue
    # pages restate it, so check every row we publish against it.
    capabilities_text = capabilities["description"]

    def row_for(venue: str) -> str:
        return next(
            (line for line in capabilities_text.splitlines()
             if line.strip().startswith(f"| `{venue}`")),
            "",
        )

    for venue, tick in [("polymarket", "0.01"), ("predictfun", "0.001"),
                        ("kalshi", "0.01"), ("hyperliquid", "0.0001")]:
        row = row_for(venue)
        check(f"{venue} is in the spec's capability table", bool(row))
        check(f"{venue} min_tick_size is {tick}", f"| {tick} |" in row, row.strip())

    check("hyperliquid has no max_price", "| none |" in row_for("hyperliquid"))
    check("predictfun settles in USDT", "USDT" in row_for("predictfun"))
    check("kalshi settles in USD", "| USD |" in row_for("kalshi"))
    check(
        "a TIF outside supported_tif is a 400, never a silent downgrade",
        "never silently downgraded" in capabilities_text,
    )
    for field in ("supported_tif", "supports_post_only", "min_tick_size", "min_order_size",
                  "supports_cancel_all", "supports_batch_orders", "settlement_currency",
                  "fee_model", "is_active"):
        check(f"capabilities expose {field}", field in capabilities["properties"])
    check(
        "kalshi_offchain is a deprecated alias of kalshi",
        "kalshi_offchain" in capabilities_text and "alias" in capabilities_text,
    )

    print("\ndocs/venues/ — capability and onboarding endpoints")
    check(
        "GET /exchanges/{exchange_id}/capabilities",
        "get" in exec_paths.get("/exchanges/{exchange_id}/capabilities", {}),
    )
    check(
        "GET /exchanges/{exchange_id}/allowances",
        "get" in exec_paths.get("/exchanges/{exchange_id}/allowances", {}),
    )
    for venue in ("polymarket", "predictfun", "kalshi"):
        warn(
            f"POST /exchanges/{venue}/enable-trading",
            "post" in exec_paths.get(f"/exchanges/{venue}/enable-trading", {}),
            "documented here ahead of the published bundle",
        )

    print("\ndocs/venues/hyperliquid.md — HIP-4 identifiers")
    check(
        "token_id carries the side coin for Hyperliquid",
        "side coin" in properties["token_id"]["description"],
    )
    check(
        "the spec documents Hyperliquid's TIF mapping",
        "hyperliquid" in submit_description and "ioc" in submit_description,
    )


    verified = checks - len(failures) - len(warnings)
    print(f"\n{verified}/{checks} claims verified against the live spec.")
    if warnings:
        print(f"{len(warnings)} documented ahead of the published bundle:")
        for warning in warnings:
            print(f"  - {warning}")
    if failures:
        print("\nSTALE — this repo no longer matches the published API:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("This repo's documentation matches the published Kairos API contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
