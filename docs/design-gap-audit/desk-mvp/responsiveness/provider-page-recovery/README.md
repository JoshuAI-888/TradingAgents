# Provider page recovery acceptance

3 October 2026. Local synthetic browser verification, not live market-data acceptance.

The source comparison found a real provider rate-limit attempt and changing website pagination boundaries. The Desk previously merged overlapping continuation pages by code, silently replacing retained values. It now rejects any overlap, duplicate/wrong-market identities, changing totals, cursor cycles, empty continuations and inconsistent completion. Prior rows and the requested cursor remain available for retry. Errors survive sort/render changes; successful continuation clears the error and unlocks the next-page control.

## Browser outcomes

- P/B fixture initially loads 300 provider members / 300 eligible stocks from 1,200 declared members.
- First continuation fails with an injected rate-limit response. Count and results stay retained; Retry next page appears.
- Retrying returns an overlapping page. The page is rejected without deduplication or replacing earlier quotes. Changing sort keeps the recovery message visible.
- A third request for the same cursor returns a valid page: 600 provider members / 588 eligible stocks. The next-page control is enabled and the prior error is cleared.
- Clear returns 1,176 stocks, ETFs excluded, market cap descending. Applying a preset and clicking it again gives the same default.
- With a later continuation still failing, actual CSV exports retain 588 unique US symbols. In-app browser CSV uses percent-change descending; Chrome CSV uses market-cap descending. Both sort checks pass. The browser download event timed out, but the files were saved; their timestamps, hashes and checks are recorded in download-verification.json and copied CSV receipts.
- No browser console errors were observed after the corrected fixture loaded. A stale fixture endpoint signature initially produced server errors; the fixture now accepts the existing route arguments.

Screenshots: rate-limit.png, overlap.png, recovered.png, default-reset.png. Fixture switch: RESEARCH_PROVIDER_PAGE_FAULT_FIXTURE=1. This mode makes the first continuation attempt fail, the second overlap, and subsequent attempts succeed per key/market/cursor. It is confined to the offline preview and does not affect production.

## Validation and limits

189 Desk/screener UI contracts pass, including retained-row identity/value checks, cursor retry, escaping and failure variants. Preview fixture Ruff and formatting checks pass. Backend/root regressions were previously passed; no backend behavior changed in this patch.

Synthetic recovery and CSV checks do not qualify provider freshness, financial reporting periods, HK publication, real stock classifications or production downloads. The live-data and hosted-release gates in review-candidate.md remain open.
