# People enrichment handoff

Updated 2026-09-17 UTC for GTM outreach policy and title extraction recovery. Read [ARCHITECTURE.md](ARCHITECTURE.md) for module boundaries and ordered filtering rules, and [EVAL-gtm-title-recovery.md](EVAL-gtm-title-recovery.md) for this change's evaluation. Earlier chronological handoff notes are preserved in `backups/architecture-cleanup/HANDOFF-before-cleanup.md`.

## Current delivery and policy

Latest Excel: `backups/gtm-title-recovery/export-001/people_gtm.xlsx`, exported with the application's existing exporter from the frozen JSON `backups/gtm-title-recovery/run-001/results.json`. **1,659 People: 1,081 supported, 326 employment_unconfirmed, 252 title_missing; 146 Review; 55 Companies; 349 discarded.** Export manifest: `export-001/export.json`. Replay and export make zero new API calls. The prior workbook/JSON in `backups/company-mention-filter/run-001/` remains unchanged at 1,437 People / 470 Review.

Measured change: two repaired-title entries and 252 blank-title leads moved Review→People. The name-only-company rule discards 31 prior People and 71 Review. One prior People row (Joe/Joseph Boys) now needs identity review for conflicting displayed names; no nickname equivalence is inferred. All 11 prior manual annotations remain, and no previous former/conflict record enters People. **873 offline tests pass.** See the GTM evaluation report for limits and replay details.

The user clarified that the tool is for **GTM outreach**, with ROI more important than exact categorization. Reliable identities and source-backed facts remain required; unknown titles must stay blank rather than be invented. Product includes Product Marketing and Product Partnerships. Noncritical implementation decisions do not need repeated confirmation.

Current admission policy:

1. Discard real candidates when **Evidence Text**, excluding occurrences of the person's complete supplied name, mentions none of the target company name, domain, or configured aliases. Matching ignores case/repeated whitespace and requires whole phrases. Query text, target columns, generated notes, and source URL alone do not qualify. Apply this before conflicting-name checks and to failed-processing evidence too. Neither People nor Review retains these records; company Notes record discard counts.
2. During department searches, department/level/role-type labels are advisory. Founder/C-level-only searches retain their selected-category boundary.
3. Missing/unsupported identity, invalid profile/evidence URL, unresolved unsupported title extraction, explicit identity/employer/title conflicts, invalid employment status, `current` without verification, or an explicitly ended copied role go to Review. A clearly different person's named headline blocks admission even when the title is missing.
4. In department searches, missing title alone can enter People as `title_missing`, with a blank Title and separate employment notes. Otherwise retain the person as `supported` or `employment_unconfirmed`. Uncertain current employment alone is not a Review gate. Deduplicate within a company, preferring an admissible complete title over a missing one; keep separate company associations.
5. Technical failures retain surviving evidence as `processing_failed`. Retry transient model errors at most twice; count every attempt, reuse retrieved hits, disable implicit SDK retries, and stop on account/quota/configuration errors.

The absent-company gate removed exactly 247 prior rows: 28 People and 219 Review, with zero API calls. Every retained row is unchanged. A company-word match alone does not establish employment: skills, surnames, and namesakes remain limitations.

## Review findings before title recovery

The 470 Review rows have mutually exclusive primary triggers:

- 334: name/profile present but extracted title missing.
- 8: extracted name and title both missing.
- 6: a nonempty extracted title fails source-text grounding.
- 59: copied target-company role is explicitly former/ended.
- 63: employer/title conflicts.

There are no processing failures or category-only holds in this delivery. Review means the saved extracted row did not pass available-evidence checks; it does not establish that the person is irrelevant. Search headlines/snippets can omit information visible on a full LinkedIn page, which the tool does not fetch. Some rows also expose extraction mistakes: John Gross's available Chief Innovation Officer headline was omitted; Mark Butler's title was combined with a management description. See the architecture document for source examples.

## Architecture cleanup and validation

- `people/identity.py` owns canonical profile URLs and shared company/phrase matching. Providers and evaluator no longer import these helpers from the orchestration service.
- `people/evidence.py` owns deterministic evidence diagnostics and Candidate construction, without network/provider/service dependencies. `classification.py` retains the unchanged model contract, API transport, response validation, retries, and usage accounting.
- `service.canonical_linkedin_url`, `service.has_company_mention`, and `OpenAIRoleClassifier._candidate` intentionally forward to shared implementations for existing callers and saved replay scripts.
- Background jobs snapshot company inputs and criteria before starting the worker. Config defaults come from the settings dataclass; invalid request-limit overrides fail before constructing clients.
- No unreferenced private functions or unused imports were found in the inspected application source. This is not proof that every runtime path is reachable. The existing company workflow remains intact.

**Architecture-cleanup baseline: 791 offline tests passed.** That saved-response audit checked all 2,154 source records: 2,143 unannotated Candidates matched exactly, and 11 earlier manual annotations retained identical extracted source fields. Service replay preserved every one of the 1,437 People and 470 Review rows and all 55 company counts, with unchanged prompt/schema. Historical audit: `backups/architecture-cleanup/`. The subsequent title-recovery change intentionally changes extraction and admission; it has a separate replay in `backups/gtm-title-recovery/run-001/`.

## Run locally

```bash
.venv/bin/python -m streamlit run app.py
.venv/bin/python -m pytest -q
```

The local app uses `http://127.0.0.1:8501`. **Company facts** is the original workflow. **People → Demo (no API calls)** gives an offline walkthrough. **Search + LLM** needs an uploaded company CSV and OpenAI/Serper credentials. Built-in fictional demo companies are blocked in live mode.

Keys are already configured in ignored `.env`; never print them. Password inputs in the API keys sidebar override server defaults for that Streamlit session only. They do not modify environment variables or persisted run settings. Restart Streamlit after changing `.env` or incompatible imported/session models. Jobs live in memory; pause/stop occurs between companies. Backups preserve completed/partial results.

CLI live usage: `--mode people --provider openai --input companies.csv --output people.xlsx --result-json people_run.json`. People model defaults to `gpt-5-mini`, independently of company facts. Optional company-founder pages are bounded and were disabled in the full-list run.

## Historical evidence and spend

Preserve all artifacts. Do not repeat paid runs to reproduce existing results.

- Original 55-company run: `backups/target-companies-live/run-001/`; 550 successful Serper requests and 55 OpenAI attempts, 54 responses, one Rogo timeout, zero retries. The original budget was fully consumed. Historical manually audited delivery: 959 People / 1,195 Review. See `EVAL-target-companies.md`.
- Rogo recovery: `backups/review-policy-followup/rogo-retry-001/`; reused 40 saved hits, one additional model request, zero searches, 5,530 input / 4,496 output tokens. No processing failure remains. Other companies replayed offline.
- Pre-company-mention delivery: `backups/review-policy-followup/final-001/`; 1,465 People / 689 Review. This also holds all 2,154 saved Candidates used for the current policy replay. See `EVAL-review-policy.md`.
- Prior company-mention delivery: `backups/company-mention-filter/run-001/`; 1,437 People / 470 Review. Architecture cleanup preserved it exactly.
- Current GTM delivery: `backups/gtm-title-recovery/export-001/people_gtm.xlsx`; 1,659 People / 146 Review / 55 Companies, exported from the separate frozen `run-001/results.json`.
- Earlier pilot/research artifacts remain historical, not a general accuracy benchmark. `backups/planning-before-feature-ZKDGrZGm/` preserves the original broad planning files.

Input for future runs: `examples/target_companies_ready.csv`, 55 company names / 64 list memberships. Its broad OpenCode/Anomaly alias was removed after namesake findings; the original full-run `input.csv` stays frozen. Saved-run replay uses that frozen input. Company identities, complete-roster recall, held-out precision, and billed cost remain incompletely measured.

## Next useful work

The prompt now separates title copying from employer judgment. Deterministic recovery copies narrowly supported headline roles and keeps ambiguous or conflicting employer/date/person evidence in Review. No extra extraction request is added. Broader company namesake disambiguation and retrieval gaps remain relevant to contact usefulness; do not optimize department labels or silently promote conflicting rows to raise counts. Preserve evidence and measure changes before considering any new paid run. Zack and Chen were absent from prior retrieval.

The approved direction is a reviewable feature within the existing tool, not a general platform redesign. Durable job queues, databases, persistent workspaces, scheduling, TTL-cache infrastructure, additional roster vendors, and unrelated company-provider migrations remain deferred unless a concrete requirement arises. See `PLAN-people-enrichment.md` for scope and `PEOPLE-scan-cadence.md` for proposed scan frequency; no scheduler is implemented.
