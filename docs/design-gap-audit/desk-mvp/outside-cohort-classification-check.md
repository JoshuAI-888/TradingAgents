# Outside-cohort preset classification

3 October 2026. Found a normalization bypass in preset display hydration: provider members outside a pinned quote cohort had raw `stock-basicinfo.stock_type` copied directly into the UI. The provider's broad ETF/trust/fund category could therefore be treated as an exact ETF subtype despite the normalized generation contract.

The fallback now uses the existing evidence-bound classifier. Fresh explicit equities remain stocks. A broad trust/fund category without subtype evidence becomes UNKNOWN, retaining its raw provider type, identity, receipt timestamp, normalization reason and full classification record. No company-name heuristic, guessed subtype or new provider request is introduced. Existing pinned classifications remain unchanged.

Classification records are validated for the entire received batch before assigning any type, preventing a malformed later record from leaving earlier rows partly classified. The assembled outside-cohort row receives a cache receipt after classification; quote fields retain their individual earlier source receipts. This receipt is not a trade/session timestamp, and the row is not assigned to the pinned quote generation.

Evidence: **787 API/worker tests pass**. Regression cases prove that an outside-cohort broad trust/fund label remains unknown, the pinned equity and live price retain their origins, unknown/outside counts are accurate, the new classification record validates against its assembled receipt, and malformed type metadata cannot partially assign types. `git diff --check` passes. No static code changed; latest UI checkpoint remains 186 tests.

This does not acquire missing subtype evidence or repair legacy stored labels. Live US/HK raw/normalized taxonomy and provider membership reconciliation remain release gates, including explicit equity REIT retention and exact ETF exclusion. Production remains unchanged.
