# Changes request failure and recovery

Local follow-up for R12. The broader recovery, real-data, platform and investment-team release gates remain open.

## Behavior

Comparison loads and debounced search immediately label retained rows as belonging to the previous successful request. Row selection is disabled while loading; existing selected/bulk/export guards remain. A current failed request clears the active pair payload, renders “Comparison unavailable” rather than a baseline setup claim, preserves known retained-history metadata and exposes Retry comparison. Retry retains the requested cohort/query/pair controls. Successful current requests clear the notice; obsolete failures cannot restore it or overwrite newer rows.

An empty notice has no layout footprint. The recovered desktop first row remains 491.828125 CSS px at 1487 × 1058. Current helper fingerprint is `20261003-comparison-recovery2`.

## Verification

JavaScript suite: **150 passed**, zero failed. Three new tests cover pending retained rows/disabled selection, payload clearing/failure/retry success, late failed request after newer success, and immediate search-debounce disclosure. Log: `/private/tmp/screener-comparison-recovery-ui.log`.

Actual offline API/browser preview on port 8904 uses the ordinary comparison route with synthetic capture history. `RESEARCH_COMPARISON_FAILURE_FIXTURE=1` delays the first Exited request for two seconds, returns HTTP 503 once, and then delegates subsequent requests to the original route. The final fixture keys failure to the Exited cohort so repeated initial renders do not consume the intended test event. Test-only harness process was reset to repeat the final code; production services were untouched.

1. **Pending — clear retained-data scope.** New matches initially shows S2001. Clicking Exited displays the notice while retaining those prior rows; DOM confirms row selection disabled. [Inspected screenshot](01-pending.png).
2. **Failure — honest unavailable state.** HTTP 503 shows Comparison unavailable and Retry; known capture/history controls remain. No empty cohort, false exits or successful-comparison counts are presented. [Inspected screenshot](02-failed.png).
3. **Phone — contained recovery control.** At 390 × 844, document scroll width is 390 and Retry is 44 px high. [Inspected screenshot](03-phone-failed.png).
4. **Recovered — requested cohort restored.** Phone Retry returns Exited S0001, one match and the original pair; notice is empty and checkbox enabled. At restored 1487 × 1058 and scroll zero, first row is 491.828125 px. [Inspected screenshot](04-recovered.png).

Viewport override was reset. No new live vendor data, new download reconciliation, backend test-suite run, production change or merge is claimed by this UI packet. Existing Settings model-catalog outage/pricing fixes already have separate evidence and were not rebuilt. R12 still needs broader view/offline/real-account qualification; all R01–R15 release work remains tracked in the current build plan.
