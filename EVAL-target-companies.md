# First full target-list pass — 2026-09-17

This run applies the approved title/profile-first policy to the user's 55 company targets. Department and seniority labels are advisory. It is a first contact-discovery pass, not an exhaustive roster or a population-precision benchmark.

**Later follow-up:** the [employment-uncertainty policy and targeted Rogo recovery](EVAL-review-policy.md) produces 1,465 People / 689 Review, including 384 unconfirmed employment records, using one additional model request and no new searches. The figures below describe the original frozen first pass and are preserved unchanged.

## Result

[Delivery workbook](backups/target-companies-live/run-001/delivery.xlsx): **959 company/contact rows representing 958 distinct LinkedIn profiles**, plus **1,195 Review rows**. One profile has supported associations with two target companies and an explicit duplicate-contact Note. The workbook includes all 55 company summaries. The [delivery JSON](backups/target-companies-live/run-001/delivery.json) retains the metadata and evidence.

| Measurement | Observed |
| --- | ---: |
| Companies searched | 55 |
| Successful search requests / returned credits | 550 / 550 |
| Model attempts / responses returned | 55 / 54 |
| Distinct returned profile URLs summed within companies | 2,835 |
| Distinct profiles retained within companies | 2,154 |
| Automatic People / Review rows | 966 / 1,188 |
| Delivery People / Review rows | 959 / 1,195 |
| Returned input / output tokens | 299,233 / 285,387 |
| Cached input tokens reported | 0 |
| Pipeline elapsed | 2,073.56s (34min34s) |

Rogo's one model attempt raised `APITimeoutError`. Its ten searches succeeded and forty retained profiles remain in Review with their original evidence. No retry occurred. The run finished with `completed_with_errors`: 54 companies completed processing, one has an error, and none remain pending. All company coverage is partial; the 40-profile cap omitted 681 distinct URLs from returned search results across the 55 companies, before any question of unreturned employees.

At the [published standard `gpt-5-mini` rates](https://developers.openai.com/api/docs/pricing), the returned token usage estimates **$0.645582**, approximately **$0.65**. This excludes unknown billable usage for the timed-out call and any Serper charges; it is not an account bill. The recorded 54 responses identify `gpt-5-mini-2025-08-07`. The account's remaining Serper allowance was not queried.

The artifact audit verified frozen input/source hashes, all 55 company rows in input order, global/per-company request caps, the 40-profile retention cap, exact automatic candidate-to-People field mapping, workbook row counts and profile hyperlinks, literal spreadsheet cells, and absence of configured API keys. Manual changes are separately documented below; all other source facts remain unchanged in the delivery copy.

## Reproduce the scope

- [Ready input](examples/target_companies_ready.csv): 55 distinct companies, 64 memberships across the original three lists. Original names, official identity sources, alias decisions, and verification dates are retained. [Original input](examples/target_companies.csv) is unchanged.
- Founders and C-level; AI, Product, Infrastructure, Engineering; EVP/SVP/VP/Head/Director; Distinguished/Fellow/Principal/Staff/Senior. Product includes Product Marketing and Product Partnerships.
- Ten search queries per company, ten requested results per query, at most forty distinct profiles retained for one model call. Retrieval now executes every selected query within the query cap, merges repeated profiles' evidence, and allocates candidates round-robin across successful query groups. It no longer stops searching when the candidate cap fills.
- Two companies in flight; global hard caps of 550 Serper attempts and 55 OpenAI attempts, plus ten/one per company. No automatic retries or resume. Optional company-page retrieval is off. No direct LinkedIn page requests.
- `gpt-5-mini`, 90-second configured request timeout, low reasoning effort, 16,384 maximum output tokens. Source hashes, settings, and input were frozen before calls.

The ignored [run folder](backups/target-companies-live/run-001/) holds `frozen_manifest.json`, `input.csv`, `criteria.json`, durable `ledger.json`, partial/final `results.json` and `results.xlsx`, and per-company query/hit/model/candidate evidence. The [one-off runner](backups/target-companies-live/run_batch.py) refuses existing output folders. Do not rerun a completed command to reproduce an offline evaluation.

## Validation and interpretation

Before the live pass, 629 repository tests passed. A separate network-disabled fake-provider check exercised the runner end to end, including input ordering, workbook export, overwrite refusal, fatal account-error stopping, nonfatal evidence retention, concurrent per-company/global attempt caps, and credential-safe diagnostics. The restarted Streamlit app completed a two-company demo with four synthetic People and two Review rows; this incurred no search/model requests.

People means the supplied indexed text supports the exported identity, title, profile, and company relationship. It does not mean someone has independently visited each profile or confirmed current employment. Review preserves missing/conflicting facts, explicit former employment, and extraction failures. Source observation time records when the tool processed the evidence, not when a job changed. Category uncertainty alone is not a Review reason in this run.

Company identity research through public official pages was separate from the application's paid search/model counters. No Apollo comparison or complete-roster recall is claimed. Prior small reference sets are development checks reused here, not newly held-out evaluation data.

Operational refresh guidance and current provider pricing sources are in [scan cadence](PEOPLE-scan-cadence.md). Successful-response token estimates can be computed from saved usage; the provider account's actual charges and remaining free balance are not available to this run.

## Manual evidence findings

The delivery copy applies recorded human-style evidence judgments to the saved automatic results, without new application search/model calls. The audit inspected 32 distinct rows across nine companies, including targeted namesake and development-reference checks; this was not random sampling and does not estimate population precision.

- Hold Julia Rose's CoreWeave row: its headline names Weights & Biases and the supplied CoreWeave experience lacks a current/end marker.
- Hold five OpenCode rows supported only by generic `Anomaly` evidence. Two other OpenCode rows explicitly connect the people to the product team. The reusable ready input now removes the overbroad alias; `run-001/input.csv` preserves the actual first-run input.
- Hold Aashiq D.'s Fin row: [the company's investor page](https://sequoiacap.com/companies/fin) identifies the namesake payments company at fin.tech, separate from [the target Fin/Intercom](https://fin.ai/about).
- Restore Haya Odeh's Replit row: its source explicitly states the present-tense Co-Founder and VP of Design role at the supplied `Repl.it` alias and links replit.com. The model inferred former employment from legacy branding without an ended-role passage. The delivery Note records the manual correction while preserving the copied name, title, profile, and evidence.

The final cross-company duplicate check inspected four additional company observations. It holds Dmitriy Kharchenko's Descript row because the headline describes current work at Augment and the Descript experience lacks a current marker; his Augment Code record remains. Rohan Chandra's SpaceXAI/Cursor records both remain, with a one-contact Note because the saved evidence includes a present Cursor role and an acquisition reference. In total, eight automatic People rows move to Review and one Review row moves to People. An earlier delivery draft remains archived separately.

The original automatic JSON/workbook remain unchanged. `manual-audit.json` records each movement and its reason. Manual correction is not a tested general solution to company-name ambiguity or unsupported employment inferences.

The reused three-person department reference still has one person in People: Corey Sanders. Zack Field and Chen Goldberg are absent from raw retrieval, not merely filtered out. Nik Koblov's negative control is retrieved and retained in Review. The reused founder reference has four of six in automatic People and five of six after the Haya correction. Bret Taylor's current indexed text supplies no Sierra title; the prior optional company-page pilot resolved that case, but this run deliberately did not fetch company pages. These checks are not comparable full-roster recall or a newly held-out benchmark.
