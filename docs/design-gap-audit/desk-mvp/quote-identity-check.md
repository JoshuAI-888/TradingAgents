# Canonical quote identity — local fix and production evidence

3 October 2026. Batch quote lookup stripped everything before the final dot from provider codes. It therefore could not resolve HK-prefixed requests, explicit US prefixes or share-class tickers. A suffix-only lookup could also confuse instruments from different markets.

Changed `stock_quotes` to index the full provider code and resolve each original request through `_stock_code`. API response keys remain the originally requested symbols, preserving Compare compatibility. Single quotes now reject responses whose code differs from the requested canonical instrument, rather than displaying another company's quote.

Tests use the non-fixture API route with a controlled provider snapshot containing HK.00700, US.00700, US.BRK.B, US.B and US.AAPL. They prove that market and share-class identity remain distinct, and that a single HK request cannot display a US instrument. 29 stock-page tests and the complete 774 API/worker tests pass. UI's latest recorded 180 tests also pass. The local fix is not deployed.

Public production read on the same day confirms the batch defect: requested HK.00700, BRK.B and US.AAPL all returned null while available=true. The individual HK.00700 quote returned available=true, code HK.00700 and name TENCENT. This establishes that the observed HK batch failure is not merely absence of a single quote. It does not qualify the HK screener universe, all presets, classification or current provider-app equality.

[Dated public endpoint evidence](public-quote-identity-check.json). Only public symbols and responses were used; no credentials, private database metadata or production writes. Source: [deployed batch endpoint](https://tradingagents-portal.onrender.com/api/stock/quotes?symbols=HK.00700%2CBRK.B%2CUS.AAPL) and [individual HK quote](https://tradingagents-portal.onrender.com/api/stock/HK.00700/quote). Values are observations, not investment conclusions.
