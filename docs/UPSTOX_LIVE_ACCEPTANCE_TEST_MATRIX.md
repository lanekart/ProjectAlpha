# Upstox Live Acceptance Test Evidence Matrix

| Test name | Behaviour covered | Fixture/event used | Assertions made | Failure path covered |
| --- | --- | --- | --- | --- |
| `test_upstox_live_acceptance_preflight_refusals[TOKEN_UNAVAILABLE]` | Missing token refusal | Fake auth local `TOKEN_MISSING` | no connection, `provider_mode=LIVE`, zero order calls | `TOKEN_UNAVAILABLE` |
| `test_upstox_live_acceptance_preflight_refusals[TOKEN_EXPIRED]` | Expired token refusal | Fake auth local `TOKEN_EXPIRED` | no connection, zero order calls | `TOKEN_EXPIRED` |
| `test_upstox_live_acceptance_preflight_refusals[TOKEN_REMOTE_VALIDATION_FAILED]` | Remote validation refusal | Fake auth remote rejected | no connection, zero order calls | `TOKEN_REMOTE_VALIDATION_FAILED` |
| `test_upstox_live_acceptance_preflight_refusals[NO_ACTIVE_TRADING_SEGMENTS]` | Inactive segment refusal | Fake auth reason includes `UDAPI100058` | no connection, zero order calls | `NO_ACTIVE_TRADING_SEGMENTS` |
| `test_upstox_live_acceptance_preflight_refusals[FEED_AUTHORIZATION_FAILED]` | Feed authorization refusal | Fake Feed V3 authorization failure | no connection, zero order calls | `FEED_AUTHORIZATION_FAILED` |
| `test_upstox_live_acceptance_refuses_unknown_and_wildcard_instrument` | Instrument safety | Registry missing key and wildcard key | unknown/wildcard rejected before provider open | `INSTRUMENT_NOT_RESOLVED` |
| `test_upstox_live_acceptance_connection_and_subscription_failures` | Connection/subscription safety | Fake provider connect and subscribe exceptions | clean shutdown attempted | `LIVE_CONNECTION_FAILED`, `SUBSCRIPTION_FAILED` |
| `test_upstox_live_acceptance_bounded_events_and_exact_instrument` | Bounded event count and exact instrument matching | Three fake live ticks for requested key | only two events accepted with `max_events=2`; subscription acknowledged | none, pass path |
| `test_upstox_live_acceptance_timeout_market_closed_classification` | Market-closed/no-data handling | Connected fake provider with no ticks | zero fabricated events; connectivity-pending classification | data acceptance pending market hours |
| `test_upstox_live_acceptance_interrupt_cleanup` | Interrupt cleanup | Fake provider raises interrupt in stream | clean shutdown, interrupted classification | `LIVE_ACCEPTANCE_INTERRUPTED` |
| `test_upstox_live_acceptance_malformed_duplicate_out_of_order` | Decoder/quality counters | duplicate timestamp, timestamp regression, unknown key | duplicate, out-of-order, unknown counters increment | `LIVE_ACCEPTANCE_FAILED` |
| `test_upstox_live_acceptance_json_export_and_secret_redaction` | JSON export and redaction | Fake live tick and fake auth secret | JSON has `provider_mode=LIVE`; secrets absent | none, export pass |
| `test_upstox_live_acceptance_cli_missing_token_sample_output` | CLI sample failure output | Missing token environment | text shows `TOKEN_UNAVAILABLE`, `Provider Mode: LIVE`, zero order calls | `TOKEN_UNAVAILABLE` |
| `test_live_acceptance_and_simulation_remain_isolated` | Live/simulation isolation | Fake live tick plus readiness simulation | live can pass only with `provider_mode=LIVE`; simulation cannot complete live acceptance | simulation cannot satisfy live acceptance |

Recorded-feed simulation tests remain separate and verify sanitized contract
fixtures, tick/quote normalization, rejection diagnostics, deterministic bars,
readiness audit JSON, and `live_provider_connected=false`.
