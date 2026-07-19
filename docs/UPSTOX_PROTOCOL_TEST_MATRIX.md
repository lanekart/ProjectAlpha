# Upstox Feed V3 Protocol Test Evidence Matrix

| Test name | Official contract requirement | Fixture used | Assertion | Negative path | Evidential limitation |
| --- | --- | --- | --- | --- | --- |
| `test_upstox_protocol_schema_provenance_and_binding_import` | Schema provenance and importable binding | `MarketDataFeedV3.proto` | source URL, schema version, hash shape, binding import | missing binding would fail import | Provider-local binding covers consumed subset |
| `test_upstox_authorized_uri_redaction_and_single_use` | One-time authorized URI must not be logged fully | synthetic `wss` URI with code | redacted URI, second consume rejected | already consumed URI | No live Upstox URI used |
| `test_upstox_subscription_encoder_payload_and_refusals` | Binary subscription request with `guid`, `method`, `mode`, `instrumentKeys` | deterministic request bytes | exact byte payload and duplicate canonicalization | empty/wildcard refusal | Payload is binary UTF-8 JSON per documented request shape |
| `test_upstox_protocol_decodes_market_status_snapshot_and_ltpc` | Market status and LTPC live-feed decoding | `market_status.bin`, `snapshot_ltpc.bin` | market status not tick, LTPC feed present | malformed handled elsewhere | Fixture is generated, not captured traffic |
| `test_upstox_protocol_normalizes_multiple_instruments_ohlc_and_volume` | Multiple instruments, full feed, OHLC, volume | `live_update_multi_full.bin` | two ticks, OHLC interval, volume | absent LTPC reasons tested separately | Covers consumed full-feed subset |
| `test_upstox_protocol_missing_optional_and_malformed_payloads` | Missing optional fields must not fabricate values; malformed must reject | `missing_optional.bin`, `malformed_payload.bin` | missing `ltq` becomes zero volume; malformed raises | malformed payload rejection | Optional unknown field preservation limited to safe decoded fields |
| `test_upstox_protocol_unknown_future_and_metadata_capture` | Unknown critical messages quarantined; future timestamp flagged; metadata safe | `unknown_type.bin`, `future_timestamp.bin`, malformed fixture | unknown category, future reason, hash/length metadata | decode failure metadata | Does not persist raw provider bytes by default |
| `test_upstox_protocol_sequence_tracker_and_reconnect_reset` | First market status, second snapshot, reconnect reset | in-memory sequence | live-before-snapshot diagnostic, reset clears state | unexpected sequence | Does not reject valid changed order, reports deviation |
| `test_upstox_protocol_audit_cli_text_and_json` | Protocol audit command | generated report | text and JSON classification ready | output redaction | Audit readiness is not live acceptance |
| `test_upstox_protocol_audit_report_ready_and_no_order_api_refs` | Adapter ready without order API imports | generated report | fixture count, malformed rejection, zero order refs | missing schema would downgrade | Static count only, not live runtime proof |

The protocol fixtures are labelled as official-schema-generated fixtures. They
are not captured Upstox production traffic and do not by themselves satisfy live
acceptance.
