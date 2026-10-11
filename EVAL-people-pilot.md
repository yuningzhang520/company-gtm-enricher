# First live people pilot — 2026-09-16

The People workflow completed real Serper retrieval, OpenAI classification, deterministic filtering, and Excel export for three companies. The keys work. The initial result below diagnosed admission problems; the controlled follow-up at the end records the fixes. Neither run establishes readiness for a complete employee scan.

## Scope and reproducibility

- Input: [three companies and verified domains](examples/people_pilot.csv): LangChain, Sierra, Replit.
- Criteria: founders/co-founders and C-level only; no department or seniority selections.
- Limits: two queries and twenty unique candidate profiles per company; ten search results per query.
- Model: `gpt-5-mini`; recorded retry responses identify `gpt-5-mini-2025-08-07`.
- The search/API calls used configured local keys. No direct LinkedIn pages were fetched.

```bash
.venv/bin/python -m company_gtm_enricher.cli --mode people --provider openai \
  --input examples/people_pilot.csv --output people_pilot.xlsx \
  --result-json people_pilot.json --max-queries-per-company 2 --max-candidates 20
```

This command makes new paid-provider requests. Search results and model outputs can change. The retained artifacts below are the record of this pilot.

## Observed execution

The first attempt used a 30-second request timeout. Replit completed; LangChain and Sierra returned generic classification errors. The old message did not distinguish timeout from connection failure, so their precise failure causes cannot be reconstructed. Search credentials were valid and returned six reported credits of usage.

Only those two failed companies were retried, with a 90-second OpenAI timeout. Both completed. Their classification calls took 26.64 and 21.32 seconds; the larger limit provides headroom but does not prove that timeout caused the original failures. The local `.env` now uses `PEOPLE_TIMEOUT_SECONDS=90`. SDK timeout and connection failures now have separate credential-safe messages; no automatic LLM retries were added.

| Attempt | Companies attempted | Serper requests / reported credits | OpenAI requests | Returned input / output tokens | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Initial | 3 | 6 / 6 | 3 | 1,821 / 2,394 | 96.66 s |
| Retry failed companies | 2 | 4 / 4 | 2 | 3,509 / 3,888 | 54.05 s |
| Total | 5 company attempts | 10 / 10 | 5 | 5,330 / 6,282 | 150.71 s |

Token counts cover the three successful responses. Two failed requests returned no usage, so these counts are not a complete billing record. OpenAI dollar charges and remaining Serper account balance were not measured. The elapsed total sums execution attempts and excludes manual research and debugging.

## Output

The combined output selects the latest successful attempt for each company. Usage includes both attempts, rather than presenting the retry as free work.

| Company | People: supported by search text | Review |
| --- | ---: | ---: |
| LangChain | 3 | 13 |
| Sierra | 1 | 17 |
| Replit | 4 | 14 |
| Total | 8 | 44 |

There are 52 retained candidate rows. The Review share is **44/52 = 84.6%**; this includes unrelated people, unclear roles, incomplete evidence, and omitted classifications. It is not a false-positive rate. “Supported” describes search evidence, not independently certified current employment.

## Predeclared founder reference

The reference was assembled from official sources before inspecting provider output. It contains six founders, not every founder or executive at these companies.

| Company | Reference person | Official role source | Final placement |
| --- | --- | --- | --- |
| LangChain | Harrison Chase | [Company About](https://www.langchain.com/about) | People |
| LangChain | Ankush Gola | [Company About](https://www.langchain.com/about) | People |
| Sierra | Bret Taylor | [Company About](https://sierra.ai/about) | Review; name remains in original evidence |
| Sierra | Clay Bavor | [Company About](https://sierra.ai/about) | People |
| Replit | Amjad Masad | [Official biography](https://replit.com/blog/author/amjad-masad) | Review |
| Replit | Haya Odeh | [Company leadership](https://replit.com/about) | Review |

All six names surfaced in candidate evidence, while **3/6 reached People**. Five personal URLs also matched an independently searched reference URL; Bret's URL had no equally strong independent URL reference and should remain unverified. Name appearance is not proof of a correct profile match or exhaustive retrieval.

The three missed admissions show different issues:

- **Amjad Masad:** search text explicitly contains a founder/CEO statement, but copied-title/role flags and employment evidence validation sent the candidate to Review. The original classification response was not retained, so the exact quote should be captured before changing the gate.
- **Haya Odeh:** the evidence uses `Repl.it` alongside `replit.com`, while the input is `Replit`. Affiliation validation failed. This is a useful case for explicit company-alias handling; it does not justify accepting arbitrary similar names.
- **Bret Taylor:** the returned result is titled “Bret Taylor - OpenAI” and merely mentions introducing people at Sierra. It does not state his Sierra founder role. Holding it in Review is appropriate; another evidence source is needed.

## Manual corroboration of the eight supported rows

| Person | Corroboration | Limit |
| --- | --- | --- |
| Harrison Chase | LangChain [Interrupt NYC](https://interrupt.langchain.com/nyc) lists Co-Founder and CEO | Current published event biography |
| Ankush Gola | [LangChain](https://www.langchain.com/about) confirms co-founder; [Princeton's March 18, 2026 biography](https://ai.princeton.edu/events/2026/ankush-gola-langchain) supports CTO | CTO evidence is dated |
| Julia Schottenstein | Search-indexed [personal site](https://schottenstein.dev/) states LangChain COO | Direct page retrieval timed out |
| Clay Bavor | [Sierra About](https://sierra.ai/about) confirms Co-Founder | Company-published role |
| Luis Héctor Chávez | [Replit leadership](https://replit.com/about) confirms CTO | Company-published role |
| Ghazi Masood | [Replit leadership](https://replit.com/about) confirms CRO | Additional “Go to Market Advisor” wording not separately checked |
| Stacey La Torre | [Replit leadership](https://replit.com/about) confirms Chief People Officer | Company-published role |
| Jake Anderson | Search-indexed [CEO appointment announcement](https://www.linkedin.com/posts/amjadmasad_welcoming-jake-as-replits-first-chief-marketing-activity-7433302669089443840-KKJZ) names Replit's first CMO | Appointment corroboration; LinkedIn page not directly fetched |

No role contradictions were found in these eight observations. This is a small, selected sample with mixed evidence strength; it is not a general precision estimate or an independent identity verification of all profile URLs.

## Artifacts and next work

Local artifacts are under `backups/live-pilot-20260916-ksd31z4g/`, ignored by Git:

- `pilot_results.xlsx`: combined People, Companies, Review workbook.
- `pilot_results.json`: combined output, settings, and cumulative usage.
- `run.json`, `people.xlsx`: unchanged initial attempt, including failures.
- `retry_run.json`, `retry_people.xlsx`: unchanged retry results.
- `retry_evidence.json`: retained search hits and structured API responses for the retry; no credentials.

Workbook row counts and required sheets were verified; JSON/workbook content was checked for exclusion of the configured keys. Automated regression suite: **203 tests passed** after adding safe timeout/connection diagnostics.

## Controlled admission follow-up — 2026-09-16

The follow-up reused exactly the same 52 retained search profiles. It made three new `gpt-5-mini` classification calls, with no repeat of the six original retrieval queries. Complete structured responses were retained this time so later admission corrections could be replayed offline.

Changes:

- Known company aliases are explicit CSV/UI/CLI input; Replit's pilot input now includes `Repl.it`. Similar company names are not inferred aliases.
- A copied title must be linked to the target employer. Founder/C-level labels from another employer cannot qualify a target-company employee, and employer prefixes such as `Sierra Space` do not match `Sierra`.
- An unsupported auxiliary C-level flag no longer vetoes an independently supported Founder flag. A wrong quote can be repaired only from an explicit named profile headline, with an audit note and no override of former/unclear employment.
- The live classifier copied sentence-ending periods into three LangChain titles. Regression tests now cover this real response format; admission was corrected using those saved responses without more API calls.
- Classification failures now preserve retrieved evidence in Review. The company stays in error; nonfatal errors continue and account/configuration errors stop with later companies pending.

The original three LangChain and one Sierra supported rows survived replay of their original model responses. Reclassification also recovered Amjad and Haya. A separately bounded, exact-profile Serper query for Bret returned the same insufficient snippet; it used **one additional search credit** and was not inserted into the controlled 52-profile comparison. Sierra's official About page corroborates his founder role, but the current provider does not join that page to a profile based only on a matching name. Bret remains in Review.

Follow-up classification usage: **3 OpenAI requests, 6,018 input tokens, 8,196 output tokens, 102.61 seconds**. The final deterministic replay used no network calls. Search usage for the controlled comparison is zero; the separate diagnostic search above is recorded independently. These are incremental counters, not a dollar bill or a fresh-search coverage estimate.

| Same retained profiles | Initial admission | Corrected admission |
| --- | ---: | ---: |
| LangChain People / Review | 3 / 13 | 3 / 13 |
| Sierra People / Review | 1 / 17 | 1 / 17 |
| Replit People / Review | 4 / 14 | 6 / 12 |
| Total People / Review | 8 / 44 | **10 / 42** |
| Reference founders admitted | 3 / 6 | **5 / 6** |

All eight previously supported profile URLs remain supported. Review share is now **42/52 = 80.8%**, still not a false-positive rate. Bret's profile remains in Review with his name in the original evidence; the model again omitted a structured observation for that hit. Workbook sheet counts, founder-reference coverage, preservation of the original supported profiles, and exclusion of configured credentials were checked. **249 offline tests pass** after the corrections.

Artifacts in the same ignored pilot folder:

- `fixed_results.xlsx` / `fixed_results.json`: current output with original paid classification usage and offline replay metadata.
- `fixed_evidence.json`: all 52 supplied profiles, prompts, structured observations, and per-call timing; no API credentials.
- `before_punctuation_fix_results.json`: intermediate output retained to show the discovered regression.
- `followup_evidence.json`: the single unsuccessful targeted-profile evidence check.
- `reclassify_saved.py`: repeats the three paid classification calls on saved evidence; `replay_fixed_responses.py`: rechecks the saved responses with no network calls.

Next: evaluate supplementary company-source evidence and explicit profile identity linkage for unresolved people, then broaden the reference set and department criteria. An Apollo comparison, complete roster recall, refresh cadence, and cost per verified lead remain unmeasured.

## Explicit company founder links — 2026-09-17

A new, optional source closes the remaining reference gap with explicit published links. [Sierra's careers page](https://sierra.ai/careers) links to a [company job posting](https://jobs.ashbyhq.com/Sierra/149f368c-52d5-408f-ba26-ad888f318a00). Its published `JobPosting` description identifies Bret Taylor and Clay Bavor as co-founders and hyperlinks their individual names to their LinkedIn profiles. Its hiring organization identifies Sierra and `https://sierra.ai/`. These facts were retained from the public HTML/structured description, without rendering scripts or fetching LinkedIn.

The implementation handles this as a narrow explicit-link source: `/about`, `/careers`, and at most one linked job page within a three-request total cap. It does not match two people solely by name. It rejects customer-role wording, former-founder statements, quotation blocks, and grouped names under one link; conflicting profile names remain in Review. The feature is opt-in in the live UI and through `--company-founder-pages`; when founders are not selected it does not run. All original query/unique-profile limits remain in effect; conflicting observations can expand Review rows for one profile. Unsupported page formats simply yield no extra founder records.

The controlled run reused the same saved search results and model responses. Only company-page retrieval was live:

| Company | Public-page requests | Extra linked founder observations | People / Review |
| --- | ---: | ---: | ---: |
| LangChain | 3 | 0 | 3 / 13 |
| Sierra | 3 | 2 | 2 / 16 |
| Replit | 3 | 0 | 6 / 12 |
| Total | **9** | **2** | **11 / 41** |

Clay was already supported; Bret is the one net new People row. The same personal URL is removed from Review after its explicit company-source identity and founder statement are resolved; the original weak profile-index snippet remains in Evidence Text. All ten previously supported profile URLs are retained. Founder-reference coverage is **6/6**, and Review share is **41/52 = 78.8%**. These development cases were used to improve the implementation; this result is neither held-out precision nor full-roster recall.

Incremental execution took **3.05 seconds**, with **0 Serper requests, 0 LLM requests, and 9 public-page requests**. Earlier paid retrieval/classification is not included in these incremental counters; links to prior artifacts preserve that history. No extra vendor API charge was incurred by this source test; total lead-acquisition dollar cost remains unmeasured. LangChain's redirect consumed its remaining page budget and is reported as one page failure; existing profile evidence was retained.

New local artifacts under `backups/company-source-pilot/`:

- `results.xlsx` / `results.json`: final combined results, source chains, original index evidence, incremental usage, and prior-run reference.
- `evaluation.json`: output of the reusable offline evaluator against `examples/people_pilot_reference.json`.
- `pages.json` / `page-*.html`: requested URLs, allowed hosts, final URLs or failures, and retained public pages.
- `run_company_sources.py`: reproduces the controlled experiment with at most nine fresh public-page requests and no API keys/search/model calls.

The six reference names are unchanged from the original predeclared sample. The machine-readable reference now also records Bret's explicitly linked URL from the company posting; this does not retroactively upgrade his original evidence. Evaluation requires exact company/profile/full-name agreement for URL-based supported coverage, surfaces duplicate or conflicting identities, and separately labels references without a URL. It makes no network calls:

```bash
.venv/bin/python -m company_gtm_enricher.people.evaluation \
  --result backups/company-source-pilot/results.json \
  --reference examples/people_pilot_reference.json \
  --output backups/company-source-pilot/evaluation.json
```

Validation: **390 offline tests pass**. Workbook row counts, source-chain retention, preserved prior profiles, resolved-profile deduplication, and exclusion of configured credentials were checked. Final quotation/group-name guards were replayed against the saved Sierra HTML with both founders still supported and no new requests. Next use a held-out company/reference set and senior department roles before expanding the paid scan; arbitrary founder-page formats and company C-level/department-page extraction remain unsupported by this supplementary source.
