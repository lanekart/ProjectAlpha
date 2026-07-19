# Upstox Market Data Feed V3 Schema Provenance

Source: Upstox Market Data Feed V3 API documentation  
URL: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/  
Retrieved: 2026-07-17

The stored schema models the official V3 fields Alpha currently consumes:

- `type=market_info`
- `type=live_feed`
- `currentTs`
- `marketInfo.segmentStatus`
- `feeds[InstrumentKey].ltpc`
- `feeds[InstrumentKey].fullFeed.marketOHLC.ohlc`

Official documentation confirms:

- Feed V3 requires WebSocket streaming with protobuf-decoded responses.
- The request payload must be sent over the WebSocket in binary form.
- The subscription request includes `guid`, `method`, `data.mode`, and
  `data.instrumentKeys`.
- `sub`, `change_mode`, and `unsub` are supported methods.
- `ltpc`, `option_greeks`, `full`, and `full_d30` are supported V3 modes.
- The first tick provides market status.
- The second tick provides a market-data snapshot.
- Subsequent ticks provide live updates.
- Standard WebSocket ping/pong frames maintain heartbeat when no data is
  available.

Generated-binding workflow:

1. Keep `MarketDataFeedV3.proto` unchanged except when upstream Upstox
   documentation changes.
2. Regenerate or update `market_data_feed_v3_pb2.py` deterministically.
3. Update schema hash expectations and tests.
4. Do not hand-edit generated output except for regeneration from the stored
   schema.

Runtime note:

Project Alpha currently keeps a provider-local deterministic binding/codec for
the consumed schema subset so deterministic tests do not need live network
access. If a full `protoc` toolchain is added later, this file is the source of
truth for regeneration.
