# Qurio Guided Demo evidence

This directory contains the retained source database for the read-only portfolio demo.

- Dataset: 1,000 closed Binance Spot `BTCUSDT · 4h` bars, with zero cadence gaps.
- Provider: DeepSeek `deepseek-chat`; Mock fallback was disabled.
- Result: three canonical-distinct candidates; RSI mean reversion passed the single sealed holdout.
- Source database SHA-256:
  `a7204efb8585801d1a114ff963a3fb3c17df6520e717c38ec7c9027063b016e4`.

The database contains retained research state, market bars and evidence. It contains no Provider
credential. `scripts/prepare_qurio_guided_demo.py` verifies its digest, migrates a generated copy
to the current schema and serves only that copy through the read-only demo launcher.

This is product-loop evidence, not a profitability claim.
