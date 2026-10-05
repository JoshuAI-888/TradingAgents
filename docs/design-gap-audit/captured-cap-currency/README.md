# Captured monetary attribution and cap-sort eligibility

R02/R07/R11 progress, not full market/provider/period/session or release qualification.

## Data contract and behavior

New captures deep-copy supplied price and market-cap observations alongside raw metrics. Optional `metric_observations` retain canonical identity, field, value, unit, currency and supplied provenance. Builder and v3 replay reject conflicting identity/value/unit or malformed currency. Existing captures without this additive metadata still replay; their currency remains unknown, with no market-prefix or company-currency inference.

The shared comparison engine computes cap eligibility over the complete filtered review before paging. Positive finite caps must all carry matching identity/value/unit attribution and one currency. Unknown/mixed currencies cause HTTP 409 on explicit cap sorting; Symbol/Company/status remain usable and membership is retained. Missing/nonpositive caps stay last in a qualified numeric sort. Coverage includes eligible/missing/unknown counts, currencies, filter scope, after-observation-or-before-if-absent basis and no conversion. This covers manual/private scheduled comparisons through the shared engine. It does not establish same-session valuation comparability or complete provider attribution, and monetary criterion sorts need further qualification.

Changes renders known currencies with values; absent/mismatched currency uses the existing `cur?` abbreviation with visible title and accessible “Currency not supplied for this value” label. The cap sort option is disabled when the complete cohort is unqualified. Sort disclosure explains after/before basis, missing handling and no conversion.

Manual/client comparison CSV appends previous/current metric observation JSON and cap-sort metadata after existing columns. Scheduled CSV/SpreadsheetML already retain complete previous/current observation records, so additive metadata remains inside those records. No existing export format is removed.

## Verification

- Full API/worker suite: **616 passed**. Log `/private/tmp/screener-captured-currency-backend.log`.
- UI suite: **151 passed**. Log `/private/tmp/screener-captured-currency-ui.log`.
- Existing cap ordering/missing-last tests now supply explicit USD attribution; their ordering and pagination assertions remain. New cases reject unknown/mixed USD/HKD sorting without losing default membership; capture freezes supplied currency, rejects four replay mutations and accepts older metadata-free records as unknown.
- Client test confirms USD display, absent/mismatched attribution disclosure and appended export metadata. Existing parsed scheduled export tests remain passing; no new real downloaded file reconciliation is claimed in this packet.
- Actual synthetic browser at 1487 × 1058 confirms cap `2.5B cur?`, accessible attribution label, disabled cap option, basis explanation and unchanged first-row placement at 491.828125 px. Qualified known-currency display/sorting is tested in code; no real provider or qualified visual-state screenshot is claimed.

## Desktop menu correction found during visual verification

An inspected screenshot contradicted the open DOM state: the menu existed but generic `details { overflow: hidden }` clipped the absolute dropdown. Both Selection and Sort/export details now explicitly use `overflow: visible`. Fresh DOM hit tests identify actual menu controls at their rendered coordinates. Actual click selects one comparison stock; its selection menu remains visible with the count/actions. The following screenshots were saved and visually inspected:

1. [Visible sort/export and currency eligibility explanation](01-sort-eligibility.png).
2. [Unknown captured currency](02-unknown-cap.png).
3. [Visible desktop selection controls](03-desktop-selection.png).

This corrects the earlier presentation packet's desktop action-menu gap; DOM presence alone was insufficient evidence. Final fingerprint: `20261003-captured-cap-currency2`. Viewport reset and preview retained for continuation. No merge, production deployment or automation activation occurred. Real Auth/PostgREST/migration/runtime, fresh Moomoo membership, supported factors/periods, device/accessibility/performance and release gates remain open.
