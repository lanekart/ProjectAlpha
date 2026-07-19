# Upstox Post-Reactivation Live Acceptance Runbook

This runbook is for the first minimal live acceptance test after Upstox account
segment reactivation is confirmed. Recorded simulation diagnostics do not count
as live acceptance.

## Bounded Command

Run the protocol audit first:

```bash
poetry run python -m alpha provider upstox protocol-audit
```

Expected pre-activation result:

```text
Overall Classification: PROTOCOL_ADAPTER_READY_FOR_LIVE_TEST
```

Use exactly one cash-equity instrument key and a finite event/time bound:

```bash
poetry run python -m alpha provider upstox live-acceptance \
  --instrument-key NSE_EQ|INE303R01014 \
  --max-events 25 \
  --timeout-seconds 60 \
  --format text \
  --output .alpha/upstox_live_acceptance.json
```

Recommended first instrument: one liquid NSE cash-equity instrument from the
local Upstox instrument registry. Do not use wildcard, index-wide, or
all-market subscriptions.

## Procedure

1. Confirm at least one Upstox trading segment is active.
2. Run `poetry run python -m alpha provider upstox protocol-audit`.
3. Generate a fresh Upstox authorization code.
4. Exchange the code:
   `poetry run python -m alpha provider upstox exchange-code`
5. Validate the token:
   `poetry run python -m alpha provider upstox validate-token --remote`
6. Confirm Feed V3 authorization:
   `poetry run python -m alpha provider upstox status --authorize-feed`
7. Run the bounded command above during market hours.
8. If the market is closed, the command may prove authentication/feed
   connectivity but must return
   `LIVE_CONNECTIVITY_PASS_DATA_ACCEPTANCE_PENDING_MARKET_HOURS` when no real
   market events arrive.
9. Review the evidence file for provider timestamp, instrument key, resolved
   symbol, last traded price, volume, latency, freshness, decoder outcome, and
   clean shutdown status.

## Expected Classifications

- `LIVE_ACCEPTANCE_PASS`: real live event evidence arrived for the exact
  requested instrument and the connection closed cleanly.
- `LIVE_CONNECTIVITY_PASS_DATA_ACCEPTANCE_PENDING_MARKET_HOURS`: auth/feed path
  could be exercised but no market event arrived in the bounded run.
- `TOKEN_UNAVAILABLE`: no configured access token.
- `TOKEN_EXPIRED`: local token metadata indicates expiry.
- `TOKEN_REMOTE_VALIDATION_FAILED`: remote profile validation failed.
- `NO_ACTIVE_TRADING_SEGMENTS`: Upstox reports inactive account segments.
- `FEED_AUTHORIZATION_FAILED`: Feed V3 authorization failed.
- `INSTRUMENT_NOT_RESOLVED`: instrument key is not present in the local
  registry or is a wildcard/all-market request.
- `LIVE_CONNECTION_FAILED`: live provider could not open.
- `SUBSCRIPTION_FAILED`: subscription was rejected before events arrived.

## Evidence Rules

Evidence is written only when `--output` is supplied. The JSON report contains:
run ID, start/end time, `provider_mode=LIVE`, preflight results, instrument
identity, event/protocol evidence, normalization outcomes, completed bar
results, disconnect outcome, order API call count, classification, and failure
reasons.

The report must not contain access tokens, authorization codes, API secrets,
account identifiers, or full confidential provider headers.

## Protocol Notes

The adapter is built around the documented Upstox Feed V3 contract:

- Feed authorization uses the Feed V3 authorize endpoint.
- The one-time `authorized_redirect_uri` must not be logged in full and is
  consumed once per connection attempt.
- The WebSocket subscription request is sent as binary bytes containing the
  documented `guid`, `method`, `data.mode`, and `data.instrumentKeys`
  structure.
- `ltpc` is the default mode for the acceptance harness unless a future command
  explicitly requests fuller data.
- Incoming Feed V3 messages are decoded through the provider-local
  `MarketDataFeedV3.proto` binding.
- The first protocol message is expected to be market status.
- The second protocol message is expected to be a market-data snapshot.
- Subsequent protocol messages are live updates.
- Standard WebSocket ping/pong frames may be handled by the WebSocket client as
  heartbeat.

Current protobuf setup:

- Schema location: `alpha/live/upstox_proto/MarketDataFeedV3.proto`
- Binding location: `alpha/live/upstox_proto/market_data_feed_v3_pb2.py`
- Provenance: `alpha/live/upstox_proto/SCHEMA_PROVENANCE.md`

The provider-local binding is deterministic and covers Alpha's consumed V3
fields. A future full `protoc` regeneration should use the stored proto as the
source of truth and update the schema hash tests.

## Cleanup And Interruptions

The harness is bounded by `--max-events` and `--timeout-seconds`. It disconnects
on success, timeout, interrupt, connection error, or subscription error. If the
process is interrupted, rerun only after checking that the previous report says
`clean_shutdown=true`.

## Simulation Boundary

`provider upstox readiness-audit` uses sanitized contract fixtures and can prove
downstream processing only. It cannot set `LIVE_ACCEPTANCE_COMPLETE` and cannot
produce `LIVE_ACCEPTANCE_PASS`. Only reports with `provider_mode=LIVE` from the
bounded live-acceptance command can satisfy live acceptance.

The current recorded fixture is a sanitized contract fixture derived from the
implemented decoder contract. It is not proof of exact production wire
compatibility unless generated from an official Upstox schema. The first live
run must compare actual event fields against Alpha's internal decoder contract.
Unknown live fields should be preserved diagnostically where safe, not converted
into fabricated defaults.

Official-schema-generated protocol fixtures are stored separately under
`alpha/live/protocol_fixtures`. They test decoder and sequencing behavior but
are still not captured live Upstox traffic.

If Upstox returns `UDAPI100058`, stop the live test. Reactivate at least one
segment in Upstox, wait for activation confirmation, and generate a fresh
authorization code.
