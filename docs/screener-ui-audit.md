# Screener UI audit

## Fixed issues

- Clear disappeared when no filter chips remained and failed to reset ETF scope, sorting, pagination, view, source, watchlist scope, and column filters. Clear is always available and restores stocks excluding ETFs, market-cap descending, Overview, page 1 (preserving the selected market).
- Clicking an active recommended screener did not toggle back to the default view. All preset exit paths now share the reset behavior.
- Recommended screener server results used market-cap ordering while the UI used percentage change. Definitions now carry their sorting into execution and rendering; saved screeners retain their saved sorting.
- Reapplying server preset factors to daily snapshot fields incorrectly removed matches, particularly averaged volume factors. Server membership is retained while additional user filters are applied separately.
- Rapid interactions could let an older render erase a newer page. Render generations and dataset/market guards prevent stale commits.
- Opening directly into a preset could omit the recommended-screeners rail. Panel loading now also runs on this path.
- Legacy persisted defaults and incomplete deep links could restore unintended ETF scope or sorting. State migration and explicit link defaults correct this; links include column filters and explicit ETF inclusion.
- Editing or removing preset filters left invisible preset membership active. Such edits now leave preset mode.
- Filter, signal, taxonomy, ticker, source and page-size changes could strand users on later pages. These changes reset pagination; Last is clamped to the actual final page, including preset results.
- Numeric column filtering shared a function name with the main filter dialog and mutated applied filters before Apply. Separate draft handlers preserve cancellation and commit only on Apply.
- Text column filters incorrectly used numeric inputs. They now use selectable facets, preserve drafts during loading, and avoid duplicate overlays.
- Ticker controls lost their displayed values after rerendering; selected taxonomy values could disappear from limited option lists. Both retain selected values.
- Missing field values sorted first in ascending mode, and field detection sampled only the first 50 rows. Missing values now sort last, and known absent factors correctly produce no matches.
- RSI quick signals ran against a source without RSI enrichment. They switch to the enriched source.
- Preset warming did not return a payload to a simultaneous click. Shared requests now return their result.
- Watchlist stars only added entries and could not remove them. They now toggle with optimistic updates, isolated rollback and an API soft-removal path.
- Exports could use a dataset from another scope, and displayed/exported row numbers restarted on later pages. Dataset keys and global offsets now stay consistent.
- Preset responses capped at 300 could imply complete results. Potentially truncated results are labeled.

## Validation

- Reproduced reset, preset-toggle and rapid-click blank-page failures on the deployed portal before changes.
- Browser-tested the actual edited HTML with local synthetic data: all 22 recommended screener cards selected and toggled off, six views, five quick signals, pagination, column filters, and export controls.
- `node --test web/api/tests/ui/screener.test.cjs`: 12 passing regression tests.
- `PYTHONPATH=web/api:web/worker python -m pytest web/api/tests/test_api.py -q`: 36 passing API tests.
- Local preview is provided by `web/api/tests/ui/preview.py` on port 8876. Its data is synthetic; it does not verify production market-provider availability or production job execution.

The live deployment is unchanged until this branch is merged and deployed. Server presets retain the existing 300-result limit; this change exposes that limit rather than removing it.
