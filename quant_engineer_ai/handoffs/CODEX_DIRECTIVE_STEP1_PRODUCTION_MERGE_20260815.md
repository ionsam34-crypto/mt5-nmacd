# CODEX DIRECTIVE — STEP 1: PRODUCTION MERGE
**Date:** 2026-08-15  
**Status:** QUEUED — do not start until Step 0 reports all sections closed  
**Prerequisite:** Step 0 accepted baseline (kill switch ON at selected threshold) must be established first

---

## Objective

Merge every research-only parameter value — exit delays, three stack caps, cap-freeze fix, and the kill switch configuration — into the single EA file that would run a live account. Then prove the merge worked by reproducing the new Step 0 accepted baseline exactly.

If the merge does not reproduce cleanly: **stop**. Do not move forward on a configuration that can't be verified.

---

## Parameters to Merge

| Parameter | Source | Value | Notes |
|---|---|---|---|
| Pullback exit delay | Research file | 28 | Confirmed in Step 0 run |
| Continuation exit delay | Research file | 30 | Confirmed in Step 0 run |
| Transition exit delay | Research file | 30 | Confirmed in Step 0 run |
| Stack cap — Pullback | Research file | TBD from Step 0 | |
| Stack cap — Continuation | Research file | TBD from Step 0 | |
| Stack cap — Transition | Research file | TBD from Step 0 | |
| Cap-freeze fix | Research file | Applied | Confirm it merges cleanly |
| Kill switch threshold | Step 0 Section 1a sweep result | TBD | |
| Kill switch pivot lookback | Step 1b specification | 5 H1 bars (default) | Owner may adjust after test |
| Spread guard | Step 0 Section 3 | 500 points | Confirm active |

---

## Merge Verification

After merging:

1. Run the exact same bundle as Step 0: Pullback 28 / Continuation 30 / Transition 30, kill switch ON at the selected threshold
2. The result must match the Step 0 accepted baseline to within acceptable rounding (±$5 or <0.05% deviation)
3. Report the reproduction result — exact equity curve endpoint, max DD, gross profit/loss
4. If it matches: merge is accepted
5. If it doesn't match: stop, report the discrepancy, do not proceed

---

## After Successful Merge

Next steps (directives not yet written):
- Code audit — review the merged EA for logic errors, dead code, unintended interactions
- Out-of-sample test — run on a date range not used in any optimization
- Live readiness review — confirm all checklist items (spread guard, symbol spec, emergency stop, sizing decision)
