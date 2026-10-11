# Employment uncertainty and failure recovery — 2026-09-17

**Latest explicit user rule:** records whose retained source text contains none of the target company name, domain, or configured aliases are now discarded from both People and Review. The [current workbook](backups/company-mention-filter/run-001/results.xlsx) and [JSON](backups/company-mention-filter/run-001/results.json) contain **1,437 People (1,433 distinct profiles), including 356 employment-unconfirmed rows, and 470 Review rows**. Offline replay removed **247 rows: 28 from People and 219 from Review**, with zero API calls. All remaining person rows are exactly unchanged; company notes record discard counts. This checks literal presence, not whether a company word denotes an employer rather than a skill or namesake. The earlier recovery figures below remain historical.

The current rule has **780 passing tests**. Final source/code/artifact hashes and discard totals were checked; the restarted browser demo completed 4 People / 2 Review and displayed the updated rule and download controls. The new replay and audit are under `backups/company-mention-filter/`.

The earlier policy incorrectly treated failure to prove current employment as a factual mismatch. Complete, source-grounded names, original titles, and profile links now remain in People with `employment_unconfirmed` when the current company association is uncertain. Department and level labels remain advisory.

[Updated workbook](backups/review-policy-followup/final-001/results.xlsx) and [JSON](backups/review-policy-followup/final-001/results.json): **1,465 company/contact rows, representing 1,460 distinct profiles; 689 Review rows**. All 55 companies finished processing. Coverage remains partial.

| Measurement | Result |
| --- | ---: |
| People supported by retained current-role text | 1,081 |
| People with unconfirmed employment/company association | 384 |
| Original 623 complete-field Review rows now in People | 481 |
| Original 609 employment-only Review rows now in People | 474 |
| Review rows lacking one or more core fields | 544 |
| Complete-field Review: employment/person/title conflict | 80 |
| Complete-field Review: explicitly ended/former copied role | 59 |
| Complete-field Review: unsupported copied title | 6 |
| Remaining technical-failure rows | 0 |

The 609-row group still has 135 records in Review: 79 source-matching conflicts and 56 former-role findings under the revised rules. These are automated evidence judgments, not independent verification of every person. In total, 509 earlier Review rows moved to People, including 28 recovered Rogo contacts; three earlier People rows moved to Review because the exact copied role had an explicit ended date. Names, titles, profile URLs, source text, and observation timestamps outside Rogo are unchanged. All 2,154 company/profile records and their original evidence remain available.

## Evidence standards

- **Unconfirmed, retained in People:** name/title/profile are grounded, but a current marker is absent, the model's employment label is uncertain, the employer spelling/branding is ambiguous, or the text cannot conclusively establish the current target-company association. Notes state this limitation. Input aliases do not independently prove company identity.
- **Review:** missing or unsupported name/title/profile facts; an explicit different-person or foreign-employer binding of the copied role; or an ended/former target-company role without corresponding present evidence. Dates and former markers are scoped to the copied role. A company rename, unrelated previous employer, or old different-level role cannot by itself veto a current role.
- **Processing failure:** retained evidence uses `processing_failed`. A completed extraction with no supported title is a data gap, not a transport failure.

Regression cases include Fin's `formerly Intercom`, unrelated former employers, `Sr.` punctuation, Max Freeman's current SVP versus old VP role, company-name punctuation, multi-role headlines, and a copied title appearing in several experience cards. Ambiguous parsing falls back to uncertainty. Camille Fournier's copied Rent The Runway role, Nik Koblov's ended Ramp role, and the previously verified namesake Fin payments-company record remain Review.

Earlier manual holds that established only ambiguity now become unconfirmed People, with their audit notes retained. The independently evidenced Fin namesake conflict remains held. The reusable input still omits the overbroad OpenCode/Anomaly alias; this replay preserves the actual historical input and explicitly annotates the earlier ambiguity. Greater inclusion does not establish higher factual precision or current employment.

## Retry and measured usage

The production People provider now permits **two transient retries, at most three total model attempts**, controlled by `PEOPLE_LLM_MAX_RETRIES=0..2`. It retries timeout/connection failures and HTTP 408/409/429, excluding exhausted quota, and 5xx errors. SDK implicit retries stay disabled. Waits are one and two seconds, every attempt counts, and the saved search hits are reused. Authentication/quota/configuration errors stop; refused or malformed/incomplete responses are not automatically retried. The default timeout is now 90 seconds per attempt.

The original first pass intentionally reserved 55 model attempts with retries disabled. Those historical counters remain unchanged. Its Rogo timeout was followed up separately using the same 40 saved hits, a 120-second timeout, and a hard cap of **two additional model attempts**. It succeeded on the **first additional request**, taking **45.99 seconds**, with **5,530 input / 4,496 output tokens and zero new searches**. It returned all 40 observations: **28 People / 12 Review** under the final policy. The remaining 12 lack a supported title; no technical failure remains. Returned usage is not an account bill.

The other 54 companies were replayed entirely offline from their saved structured responses. The revised prompt was exercised on Rogo only; this is not a fresh 55-company model evaluation or new retrieval. No full-batch rerun occurred.

## Validation and artifacts

**749 tests pass.** Tests cover uncertainty admission, explicit-conflict controls, date scoping, bounded retries, quota/authentication exclusions, attempt accounting, and failure evidence. The restarted local Streamlit app completed its offline two-company demo with four People, two Review, unlocked controls, and an Excel download.

The final artifact checks verified original profile/evidence preservation, non-Rogo copied-field equality, all three workbook sheets against JSON, literal cells, correct hyperlinks, configured-key exclusion, and source/code hashes. The final folder contains `audit.json` with every movement and `validation.json` with check results. The Rogo folder contains a durable request ledger, saved request/response, inputs, and an exact executed-script copy matching its ledger hash. Earlier runs and intermediate replays remain untouched.

Offline reproduction, with a new output folder:

```bash
.venv/bin/python backups/review-policy-followup/replay.py \
  --output backups/review-policy-followup/new-offline-copy \
  --rogo-result backups/review-policy-followup/rogo-retry-001/result.json
```

This command rejects network access and makes no API calls. Do not rerun the live retry to reproduce a saved result.
