# Required lint gate resolved

3 October 2026. The repository's full configured `ruff check .` now passes, including the inherited portal/worker baseline and the current candidate. No lint job was disabled and no rule group was removed.

Cleanup separates mechanical formatting from reviewed changes. Backed up the 123 files in the initial lint report to a local temporary directory. Formatting those files preserved their parsed AST exactly. Formatting/import cleanup was then followed by explicit fixes: pytest fixture imports use intentional re-exports, callback closures bind loop values, legacy zip truncation is declared with `strict=False`, ambiguous local names are descriptive, and translated API exceptions suppress implicit chaining. Reviewed simple suppress/return/lambda conversions preserve their existing control flow. FastAPI Depends declarations are registered as intentional immutable-default calls; late initialization-dependent imports have narrowly documented E402 annotations. No new product/auth/team workflow is enabled.

The full root suite exposed earlier test assumptions about embedded prompt source and graph construction. News and conflict/Hold guards now inspect the actual resolved prompt templates rather than expecting text inside refactored functions; their semantic assertions remain. The constructor-bypassing portfolio test fixture initializes the callback field used by graph execution. Product prompt content and graph runtime behavior were not altered to satisfy these tests.

Final local evidence on Python 3.12:

- Configured strict Ruff: all checks pass.
- Portal/worker: 787 tests pass in 12.02 seconds.
- Root: 1,008 tests and 91 subtests pass; two documented skips (optional Bedrock dependency and unavailable live DeepSeek key).
- Screener/Desk JavaScript: 186 tests pass.
- All 22 captured original preset filter and declared sort/direction contracts exactly match the current catalog.
- `git diff --check` passes.

This cleanup is broad because the committed web baseline also failed the existing full-repository lint gate. Static design/assets and provider financial values are unchanged by the cleanup. Keep formatting/import changes distinguishable during candidate review. These local checks are not GitHub-hosted Linux/multi-version CI, live source qualification, or deployed UX acceptance. Live US/HK classification/presets, target-platform cutover and exact-commit deployment remain required.
