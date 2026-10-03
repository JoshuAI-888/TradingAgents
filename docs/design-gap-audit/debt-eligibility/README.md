# Debt-factor eligibility correction

Local data-contract checkpoint, 2 October 2026. R02/R09 remain open.

## Corrected behavior

The derived LT debt/equity percentage previously accepted negative equity or negative debt. Such a result could satisfy a maximum-debt filter. It now requires finite nonnegative long-term debt and strictly positive finite equity, retaining zero debt. Zero/invalid primary equity cannot borrow a positive alternate, and conflicting supplied equity keys yield unavailable. Total debt/equity remains a direct provider percentage; negative/nonfinite/non-numeric responses are withheld rather than treated as low leverage. LT and total debt are separate fields; total debt is never substituted for long-term debt.

Both fields have versioned eligibility contracts. Fresh pre-correction cached values are withheld and prioritized by the existing bounded correction sweep. API eligibility independently rejects negative debt values even if stamped with the current contract. Failed retrieval still preserves old data and its clock, without making it eligible. Current values retain the contract in their origins. Labels consistently specify percent; no thresholds or original preset definitions changed.

These contracts establish numeric transformation and input eligibility only. They do **not** establish a matching balance-sheet date, currency, denominator scope or reporting basis. Further input/provenance qualification is still required before enabling advanced peer/debt analysis. Issuer leverage definitions can differ: for example, [BrightSpire’s annual report](https://www.sec.gov/Archives/edgar/data/1717547/000171754725000038/brsp2024annualreportarsfil.pdf) describes a net-debt calculation. This application does not silently substitute an issuer-specific net or adjusted ratio for these two fields.

## Tests

**426 API/worker tests and 117 JavaScript tests pass**. `git diff --check` passes.

New cases cover negative/zero equity, negative debt, invalid numerics/overflow, conflicting equity keys, zero debt, legacy/current cache contracts, and actual fetcher → nightly persistence → screener filtering. The integrated regression confirms invalid debt inputs cannot pass a maximum 30% LT-debt screen, while genuine zero and 25% results can. Negative direct total-debt percentages cannot pass the filter either. Existing generation, ownership and all-preset preservation tests remain green.

Commands:

```sh
PYTHONPATH=web/api:web/worker /private/tmp/tradingagent-ui-venv/bin/python3 -m pytest web/api/tests web/worker/tests -q
node --test web/api/tests/ui/screener.test.cjs
git diff --check
```

## Public-provider sample

[Recorded selected input/output fields](public-probe.json) were captured through the actual fetcher at **2026-10-02T09:18:50.461337+00:00**, using yfinance 1.7.0 in the disposable test runtime. Two public ticker-info reads, no production writes:

| Canonical code | LT debt / equity inputs | Supplied total debt/equity | Output |
| --- | --- | --- | --- |
| US.MCD | Both absent | Absent | Both debt fields unavailable |
| US.KO | Both absent | 115.519 | Direct provider percentage preserved; LT field unavailable |

Both responses contained total debt, but that value was not substituted for missing long-term debt. Their generic fiscal/quarter timestamps were not assigned to an absent ratio observation. [Replay verification](probe-verification.json) checks canonical identity, exact raw/output agreement, missing-input behavior, actual API eligibility and rejection of fresh unversioned caches. The positive direct ratio is not an independently reconciled balance-sheet calculation; these two samples cannot establish full-market coverage or source-unit/period agreement.

## Remaining gates

Qualify exact debt/equity input definitions, financial currency, matching balance-sheet date and source clocks; obtain broader eligible coverage and Moomoo reconciliation. Current runtime/provider/production contracts, complete exports/peers, migrations/cutover/rollback and investment-team acceptance remain open. No deployment or merge occurred. No chart/UI layout changed; prior screenshots are not evidence of these public financial samples.
