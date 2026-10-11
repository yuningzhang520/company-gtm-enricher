# People enrichment feature

Status: GTM outreach policy, bounded literal-title recovery, independent employment judgment, fair query coverage, bounded retries, and company-mention filtering are implemented. Latest offline replay: **1,659 People (1,081 supported, 326 employment_unconfirmed, 252 title_missing), 146 Review, 349 discarded**, with zero new API calls. See `EVAL-gtm-title-recovery.md` for measured changes and limitations. The earlier 1,437 People / 470 Review Excel delivery and all original/recovery artifacts remain intact. Department/level labels remain advisory; company-word presence is a minimum requirement, not proof of employment.

## Problem and outcome

**Current use case: GTM outreach.** Optimize usable-lead yield per search/review cost while keeping factual fields source-backed. In department searches, missing title alone may enter People as `title_missing` with a blank Title; missing/unverified identity, invalid profile, explicit conflicts, and ungrounded extractions still require Review. Copy job titles independently of employer judgment, and never fill unknowns from inference.

The current tool enriches company records. Users also need founders, C-level executives, and senior AI, product, infrastructure, and engineering staff, with names, titles, and LinkedIn URLs.

Add a people workflow to the existing CSV tool. Make it usable end to end and demonstrate its quality with a small manually checked reference set. The contribution should provide concrete evidence of requirements scoping, integration, evaluation, and delivery for FDE applications.

**Latest user clarification, 2026-09-17:** precise department categorization is not important if the person, original job title, LinkedIn profile, and target-company association agree. Department/level labels are approximate discovery and navigation aids. During an active department search, supported adjacent or uncertain-category profiles remain visible with Notes so the user can judge the original title. Identity, title, profile mismatch, wrong company, and explicit former employment remain evidence issues to flag. The filtering, classification diagnostics, UI/CLI explanations, and run metadata now implement this clarification.

## Scope

- Read companies from uploaded CSVs; preserve list tags and accept user-supplied identity information. The 55-row example is data, not application policy. Ambiguous names need resolution rather than an assumed identity.
- Discard real candidates when their saved source text mentions none of the target company name, domain, or configured aliases. Do not put these records in Review. Apply the same rule to saved evidence from failed processing; report discarded counts separately from admitted/reviewed contacts. Company-name presence is not itself proof of employment.
- Configure people criteria through multi-select controls with custom labels; represent leadership and senior individual contributors separately. Presets are editable data. Start real-data validation with founders/C-level, then expand through the same workflow.
- Retrieval/LLM receives the criteria as search and mapping context and preserves original titles and unknowns. During department searches, exact-label agreement is diagnostic only: unknown or different labels receive a Note rather than exclusion or Review. Actual titles stay visible so adjacent roles can be judged. Without an active department search, retain the selected founder/C-level category boundary.
- **Product scope clarified on 2026-09-17:** include Product Marketing and Product Partnerships alongside product management. Definitions are now explicit configuration shared by UI/CLI presets, editable per run, and recorded with results. Applied Research is not automatically Product under this clarification. The classifier receives definitions as mapping guidance, with no deterministic semantic guarantee; the measured follow-up still failed overall quality acceptance.
- Serper retrieves indexed profile results; OpenAI Responses returns structured observations tied to source IDs. Code assigns URLs from those returned search results. Keep direct LinkedIn fetching out of this workflow.
- Optional company founder evidence reads at most three public pages per company. Admit only explicit linked founder names from the company site, or an officially linked job page whose company/domain metadata agrees. Retain both source chain and original indexed evidence; names alone cannot establish a cross-source profile match. This source uses no extra search/LLM calls and does not generalize to arbitrary leadership-page formats.
- Export an Excel workbook with People, Companies, and Review sheets. Include name, title, LinkedIn URL, and supporting evidence/status. People output columns are selectable from the supported fields.
- Keep complete, source-grounded name/title/profile records in People when only employment freshness or company association is uncertain, with `employment_unconfirmed` and explanatory Notes. During department searches, allow a missing title alone as `title_missing`, preserving a blank Title and separate uncertainty notes. Missing/unsupported identities, invalid links, unresolved unsupported titles, explicit identity/employer/title conflicts, or clearly ended copied roles require Review. Technical failures use `processing_failed`; retry transient model errors at most twice, counting each request and reusing search results. An indexed URL alone does not establish identity or current employment. Never invent a URL or silently represent a limited search as complete.
- Reuse upload, run-control, progress, and partial-output patterns with the adaptations the people result requires. Preserve existing company enrichment behavior.
- Accept OpenAI/Serper password inputs in the web sidebar with per-session overrides and local `.env` fallback. Keep entered keys out of shared process configuration and persisted results; do not prefill server credentials into the browser.

## Local architecture

Implemented boundaries and ordered admission rules are documented in [ARCHITECTURE.md](ARCHITECTURE.md). The architecture cleanup separates deterministic evidence rules from model transport, shares identity helpers, and snapshots job inputs before thread startup. Offline replay preserves all 1,437 People / 470 Review rows without new requests.

`CSV + people criteria -> PeopleService -> PeopleProvider -> candidates + evidence -> validation/deduplication -> Excel`

- Introduce a people record and result containing multiple people per company. Keep the existing `CompanyEnrichment` contract intact.
- Give the people provider a mock implementation and keep provider-specific requests behind that interface. Avoid a plugin framework or generalized company-service rewrite.
- Separate network discovery from deterministic rules, evidence checks, deduplication, and export so these behaviors can be tested without live requests.
- Use stable company identity where available and canonical profile URLs for deduplication; do not merge different people solely because their names match.
- Make request failures, partial results, and any configured limits visible. Record observed request usage and elapsed time; distinguish measured charges from pricing-based estimates.

## Delivery and evidence

1. **Implemented:** offline input and criteria, people model/provider/service, mock results, Excel export, Streamlit mode and CLI integration. Automated checks cover the original company CLI, people UI, review/deduplication, failures, and stopped-run backups.
2. **Implemented and exercised live:** Serper retrieval, OpenAI classification, grounded evidence handling, explicit query/candidate limits, bounded search retries, fatal account-error stopping, request/token accounting, and export of raw evidence/settings. The first pilot included two classification failures and successful retries; it exposed missing transport diagnostics, now fixed.
3. **Reference pilot and fixes measured:** [Three companies and six predeclared founders](EVAL-people-pilot.md), with source URLs and explicit criteria. Admission fixes improved 8 People / 44 Review to 10 / 42; explicit company-published founder links then improved this to 11 / 41 and 6/6 reference-founder admission. The last increment used nine public-page requests and saved model responses. The offline eval CLI reproduces reference placement and flags identity ambiguity. The later55-company search-only pass and its separate manual delivery audit are recorded in `EVAL-target-companies.md`. Broaden independent references before claiming wider accuracy. Complete-roster recall, held-out precision, account-billed cost, and provider comparisons remain unmeasured. Do not reuse archived research as ground truth.

Report whether the name, original title, LinkedIn profile, and target company agree, plus useful candidate coverage, evidence-related review rate, elapsed time, and cost per correct usable result. Department/level agreement is diagnostic, not the delivery gate. Record sample size and limitations. An Apollo comparison is optional follow-up, using the same reference and scope.

Completion evidence: meaningful automated tests, a reproducible mock demo, a live evaluation report when measured, and a concise PR description explaining the problem, behavior, tradeoffs, and validation. Record actual user feedback when obtained; do not claim adoption or merge outcomes in advance.

## Deferred

General configurable company fields, persistent workspaces, automatic refresh/change tracking, TTL cache infrastructure, additional roster vendors, and unrelated job-runner refactors are outside this initial feature. Document a concrete architectural issue when it affects delivery; expand scope only when needed.

Scan cadence is documented in `PEOPLE-scan-cadence.md`: weekly for ten active targets and every four weeks for the rest, about 850 search attempts per four-week cycle with retries off. No scheduler is implemented. Freshness and actual account charges still require observation; current pricing-based estimates are explicitly separated from measured usage.
