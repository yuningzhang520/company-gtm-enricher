# Department-role pilot — 2026-09-17

Ramp and CoreWeave exercise a new part of the workflow: senior Engineering and Product roles with Founder/C-level categories disabled. The first run admitted eight profiles but found only one of three predeclared positive references. This exposes retrieval gaps and classification weaknesses; it is not evidence that a wider scan is ready.

## Frozen scope and reference

Before calling either paid provider, the company input, criteria, reference, source notes, and baseline code hashes were saved in `backups/department-pilot/frozen_manifest.json` (frozen at `2026-09-17T12:10:55.107945+00:00`). These two companies had not been used in the earlier LangChain/Sierra/Replit development pilot. Reference research was separate from the application's search/model requests; its time and cost are not included in the provider counters.

- Input: [two companies and domains](examples/people_department_pilot.csv).
- Departments: Engineering and Product.
- Leadership levels: EVP, SVP, VP, Head, Director. IC levels: Senior Staff, Staff, Principal. Selection uses exact levels, not a minimum-rank hierarchy.
- Four search groups per company, ten results requested per group, forty unique profiles maximum per company. All eight planned groups ran; neither candidate cap was reached.
- No founder/company-page supplementation. Search and model retries were disabled for this pilot. Production search still permits one bounded retry.
- Classification: `gpt-5-mini`, local timeout 90 seconds. The recorded responses identify `gpt-5-mini-2025-08-07`.

The [positive reference](examples/people_department_reference.json) was based on public source evidence before retrieval:

| Company | Person | Expected department / level | Role and identity evidence |
| --- | --- | --- | --- |
| Ramp | Zack Field | Engineering / Senior Staff | [Company author page](https://ramp.com/authors/zack-field); [indexed personal profile](https://www.linkedin.com/in/zackeryfield) |
| CoreWeave | Chen Goldberg | Engineering or Product / EVP | [Current company leadership page](https://www.coreweave.com/leadership/chen-goldberg); the [original interview show notes](https://www.lastweekinaws.com/podcast/screaming-in-the-cloud/the-non-magical-approach-to-cloud-based-development-with-chen-goldberg/) explicitly link her profile |
| CoreWeave | Corey Sanders | Product / SVP | [Company release](https://www.coreweave.com/news/coreweave-expands-mission-control-to-accelerate-enterprise-ai-adoption); [indexed personal profile](https://www.linkedin.com/in/corey-sanders-842b72) |

Chen's current leadership page says EVP of Product & Engineering, corroborated by a [company-authored post](https://www.linkedin.com/posts/coreweave_after-8-years-scaling-kubernetes-at-one-activity-7461768927031808000-i85q). An older investor bio still says SVP; that would count as a stale level in this reference. Her old interview is used only to corroborate profile identity, not current employment. Corey's early appointment was Strategy; the later company release and [event announcement](https://www.linkedin.com/posts/goldbergchen_gtc-activity-7437616562783633408-w_D2) identify Product.

One additional negative control was frozen separately: **Nik Koblov must not be admitted as a current Ramp employee**. An [old Ramp announcement](https://ramp.com/blog/strengthening-our-leadership-bench) lists him as EVP of Engineering, but his [personal profile](https://www.linkedin.com/in/koblov) names OpenRouter and includes his announcement of joining it. Review is acceptable for this check. Mere absence would not demonstrate that stale evidence was correctly handled.

## First run: held-out result

| Measurement | Ramp | CoreWeave | Total |
| --- | ---: | ---: | ---: |
| Unique profiles retained | 34 | 31 | 65 |
| Structured model observations | 16 | 14 | 30 |
| People | 3 | 5 | 8 |
| Review | 29 | 26 | 55 |
| Excluded by selected criteria | 2 | 0 | 2 |
| Positive reference in People with expected labels | 0/1 | 1/2 | **1/3** |

Corey was found with the expected Product/SVP labels. Zack and Chen were absent from the retrieved profiles themselves; admission changes cannot recover them from this evidence. Nik was retrieved with an OpenRouter headline and an ended Ramp experience entry. The model marked that role former and the pipeline kept it in Review.

Both API calls completed without a timeout. The model omitted structured observations for 35 retrieved profiles; their raw evidence remains in Review with blank extracted name/title. The initial Review share is **55/63 = 87.3% of emitted rows**; the two clearly excluded profiles are not in that denominator. Review share is not a false-positive rate.

| Observed usage | Value |
| --- | ---: |
| Serper requests / reported credits | 8 / 8 |
| OpenAI requests | 2 |
| Returned input / output tokens | 6,690 / 4,978 |
| Total pipeline elapsed | 79.33 s |

These counts do not establish a dollar charge or cost per verified lead. The three-positive reference is far too small to estimate full-roster recall or population precision.

## Diagnosed behavior

The retained first-run evidence showed three different problems:

1. **Retrieval coverage:** two positive references never reached the classifier even though all planned groups ran. This requires a controlled retrieval comparison, not a looser admission rule.
2. **Affiliation formatting:** exact copied titles such as `Head of Engineering. Ramp.` and `Director of Engineering @ Ramp` were rejected despite explicit same-hit employer evidence. The original parser handled `Title. Company` only when the model copied `Title`, and did not handle `@`.
3. **Role mapping:** `Senior Director of Engineering` was mapped to `Director`, violating exact-level selection. `Head of Applied Research` was also mapped to Product without an explanation supporting that department. The initial audit additionally raised the Partnerships/Marketing boundary, which the user clarified after the run.

The original eight People rows therefore should not be described as eight independently verified qualifying leads. In particular, the level mismatch is a known admission error. Remaining rows were not independently verified for current employment beyond their supplied indexed evidence.

**User clarification after the frozen run:** Product includes product management, Product Marketing, and Product Partnerships. Marketing/Partnerships titles are therefore not automatically out of scope. This clarification does not change the frozen reference or first-run outputs, establish the actual org-chart department of every person, or justify mapping Applied Research to Product. At that point the classifier received labels rather than definitions; the later implementation and measured limitations are recorded below.

## Controlled admission replay

Two local corrections were checked against the same saved responses, without changing the prompt, regenerating observations, or making requests:

- Recognize an explicit single-role `Title. Company.` or `Title @ Company` employer suffix. Similar-name companies, composite roles across employers, and former/unclear employment remain guarded. Original copied titles and evidence are retained.
- When an explicit modifier is omitted from a mapped level (for example, Senior Director mapped to Director), send the conflict to Review. This does not assign a new level or introduce a rank ordering; supported Founder/C-level categories can still qualify independently when selected.

| Same evidence and model observations | First run | Corrected replay |
| --- | ---: | ---: |
| Ramp People / Review | 3 / 29 | 10 / 22 |
| CoreWeave People / Review | 5 / 26 | 4 / 26 |
| Total People / Review | 8 / 55 | **14 / 48** |
| Excluded by exact selections | 2 | 3 |
| Positive reference coverage | 1/3 | **1/3** |
| Nik negative control | Review | Review |

Seven Ramp records gained supported affiliation formatting. Nitin moved from People to Review because Senior was omitted from his mapped level. Harshdeep's affiliation is now supported, so his correctly mapped Senior Director level can be excluded by the actual selection rather than remaining in Review for a formatting error. This explains why the number of emitted rows decreases from 63 to 62 while all 65 candidate profiles remain accounted for.

The added admissions include Alex's still-unexplained Applied Research → Product assignment and Courtney's model-current Product Operations entry, whose indexed experience text has a start date but no explicit Present marker. These are retained limitations, not evidence of improved verified precision. The corrected output still needs role/freshness review before use as a job-search contact list. No department-policy hardcoding was added.

Validation: **445 offline tests passed**. The earlier 52-profile founder/C-level responses were also replayed without requests; all ten previously admitted profiles were preserved. Both workbooks' row counts and literal cells, the department negative control, rank-conflict placement, original artifact hashes, and exclusion of configured credentials were checked. The replay writes `replayed_results.json` / `replayed_results.xlsx` and `replayed_evaluation.json`; its incremental search and model requests are zero, with original paid usage retained separately in run settings.

Next work should prioritize explicit department definitions (including the user's broad Product scope), completeness of structured extraction, and a bounded retrieval comparison using spelling variants such as Engineering/Engineer and expanded executive levels. Keep the same request budget and preserve this first result. A fresh reference sample is required before calling a later result held-out; more admitted rows on this development sample are not enough.

## Configurable department definitions follow-up

The user approved implementing department definitions after the earlier replay. UI and CLI now share editable presets in `people/role_options.json`; the Product preset includes Product Marketing and Product Partnerships. Selected definitions travel with `PeopleCriteria` into the classifier request and run metadata. A custom JSON file can override CLI presets; a blank description clears that department's definition. Definitions are mapping context, not employment evidence, and do not alter retrieval queries. Python callers may omit definitions to keep label-only guidance.

The run snapshots the definitions before processing companies, and direct classifier calls revalidate a fresh copy before spending. Edits to the caller's dictionary cannot silently change a running service's criteria. Offline tests cover this boundary, input validation, UI edit persistence/session isolation/active-run locking, CLI preflight, and exact filtering independently of the model's semantic accuracy.

After **497 offline tests passed**, six development checks, definitions, source hashes, and code hashes were frozen in `backups/department-definitions-pilot/manifest.json`. The original eight search responses were replayed to reconstruct the same 65 profiles. Two new model calls used the same model and limits. No new Serper requests or company-page lookups occurred; this was not a new held-out sample.

| Same retrieved evidence | Previous corrected observations | New definitions + model responses |
| --- | ---: | ---: |
| Ramp People / Review | 10 / 22 | 3 / 31 |
| CoreWeave People / Review | 4 / 26 | 0 / 30 |
| Total People / Review | 14 / 48 | **3 / 61** |
| Excluded | 3 | 1 |
| Positive reference coverage | 1/3 | **0/3** |
| Profiles without structured observations | 35 | 36 |

The declared cases showed mixed behavior:

- Abby's Product Marketing title mapped to Product, explicitly citing the supplied definition, but the `| Ramp` title form still failed the affiliation parser and remained in Review.
- Alex's Applied Research role no longer mapped to Product; the model abstained with an empty department and an explanation tied to the definitions. It remains Review.
- Jareau's Partnerships profile had no structured observation, so this call does **not** validate its intended Product classification.
- Nitin now has the exact Senior Director label and is not admitted as Director. Nik remains Review as a former employee.
- Corey mapped to Product but received `Senior Vice President` instead of the selected `SVP`, plus a copied trailing separator in the title. He moved to Review and no longer counted as supported reference coverage.

**Overall admission regressed.** Several returned titles contained dates or profile separators, and one contained a sentence fragment. Thirty-six profiles had no structured observation. The two visible department decisions demonstrate that definitions influenced mapping, not that precision or usable coverage improved. These fresh responses also vary from the prior call, so this single comparison cannot isolate the effect of the definition text from other prompt changes or model variation. [OpenAI's Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs) likewise distinguishes schema adherence from semantic correctness.

Incremental usage: **2 OpenAI requests, 7,192 input tokens, 4,804 output tokens, 52.38 seconds; 0 search requests/credits**. Both model requests completed. No additional paid retries were made. Original search/model artifacts and previous workbooks remain unchanged. Dollar charges were not measured.

Artifacts in `backups/department-definitions-pilot/`: `results.json` / `results.xlsx`, full `evidence.json`, `evaluation.json`, predeclared `checks.json` and observed `check_results.json`, `definitions.json`, `manifest.json`, and `reclassify.py` (paid, repeat-guarded). The new output needs review and should not be presented as an improvement over the previous workbook.

Next: fix extraction completeness and the separation of copied title text from canonical level labels before wider scanning. Verify semantic improvements with explicit cases and retained failure observations. Configurable definitions are delivered; overall department-quality acceptance is still unmet.

## Extraction stability and bounded follow-up

The next approved increment addressed extraction omissions and inconsistent level spellings without changing retrieval. Requests require one observation for every source ID, with exact array length and explicit unknown fields. Job-role phrases are separated from canonical labels. JSON-configured lexical aliases map full VP/SVP/EVP spellings to equivalent selected labels without collapsing distinct levels; explicit modifier contradictions remain Review. Grounded trailing separators and an explicit named role/company headline can be handled locally while retaining the original evidence.

All runs below use the same 34 Ramp and 31 CoreWeave profiles. Definitions, criteria, and source evidence are unchanged. Model requests, responses, hashes, and a four-attempt ledger are saved in `backups/extraction-stability-pilot/`.

| Development comparison | People | Review | Excluded | Missing observations | Reference coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior definitions run | 3 | 61 | 1 | 36 | 0/3 |
| New extraction contract, two calls | 19 | 42 | 4 | 0 | 1/3 |
| One corrective Ramp call + offline CoreWeave headline replay | 21 | 40 | 4 | 0 | 1/3 |
| Separate manual evidence review | 18 | 43 | 4 | 0 | 1/3 |

The first two calls restored Corey with the exact SVP label and produced all 65 observations. Five Ramp observations still omitted explicit person names because their sources lacked Ramp affiliation. A final prompt adjustment emphasized extracting each fact independently of the selected filters. Its one Ramp call recovered those names, available partnerships-leader titles, and an explicit Product Partnerships function. All five names remain in Review. The unchanged CoreWeave response was replayed locally: Shadi's complete named profile headline now supports its copied role-only title despite a mismatched model quote. The final automatic output contains 65 names, but this is not proof that every other field was extracted correctly.

The final prompt was tested on Ramp only. CoreWeave retains the earlier response, and the frozen synthetic fixture described below was not rerun after this adjustment. Request versions remain explicit in the saved evidence.

### Semantic failures remain visible

- Bryant's **Head of Financial Partnerships** was newly admitted as Product solely because it contains Partnerships. The text supplies no product/platform context. This is an unsupported mapping under the approved definition, which includes **Product Partnerships**, not all partnerships.
- Sales, Finance, and Risk still became blank department fields because they were unselected. All three predeclared checks failed; selection still influences extraction despite the instruction to separate them.
- Calvin's composite **VP of Special Projects / Founding Engineer** still received Engineering + VP. He moved to Review because employment changed to unclear for lack of dates, not because the composite mapping was corrected. That semantic check failed.
- Several Review titles retain employer/hiring text. One unrelated-company founder title/quote was rewritten rather than copied; grounding checks kept it in Review.
- Read W.'s Staff Product Operations Manager title is literal, but the model justified IC classification from the selected level list. Courtney's Director role has a start date without an explicit Present/end marker, although her headline supports current Product Operations affiliation. These need role/freshness confirmation.

Manual review moved Bryant, Read W., and Courtney from People to Review and appended the composite-role concern to Calvin's existing Review row. Original model fields, sources, and automatic outputs remain untouched. The annotated **18 People / 43 Review** workbook is an inspection aid; manual review is not a newly implemented application feature or proof of current employment. The automatic pipeline still produces 21/40 on those responses. Neither count is an independently verified precision estimate.

### Frozen synthetic contract check

`tests/fixtures/people_extraction_contract.json` contains 12 explicitly fictional cases, frozen before its model call. Company/person identities and profile URL identifiers are synthetic. Expectations and rationales were never sent to the model. Cases cover full executive-level spellings, exact Senior Director exclusion, Product Marketing/Partnerships, research, former employment, a conflicting employer domain, sparse evidence, and senior IC roles.

The first prompt returned all 12 observations: **11/12 exact field-and-placement matches**, seven expected People admitted, three expected Review cases retained, one expected exclusion, and one additional safe abstention. The research case kept an empty department and entered Review instead of retaining an accurate unselected research label and being excluded. **Zero negative/uncertain cases entered People.** The abstention is not counted as an exact pass. This tests these synthetic cases only; it does not establish real-world precision or complete-roster recall. After analysis it is a development fixture, not a fresh held-out benchmark for subsequent tuning.

### Usage, verification, and artifacts

| Increment | Model requests | Input tokens | Output tokens | API elapsed |
| --- | ---: | ---: | ---: | ---: |
| Two-company saved-evidence run | 2 | 8,026 | 9,919 | 122.76 s |
| Synthetic fixture | 1 | 2,237 | 2,293 | 28.98 s |
| Corrective Ramp call | 1 | 4,183 | 3,947 | 48.58 s |
| Total | **4** | **14,446** | **16,159** | **200.32 s summed call time** |

Search requests/credits and company-page requests were **zero**. Automatic retries were disabled; all four requests completed. Summed API duration is not end-to-end wall time because some work overlapped. Dollar charges were not measured. The final automatic workbook retains its one-call incremental usage; earlier paid usage is recorded separately above and in the ledger.

**593 offline tests passed.** All ten earlier founder/C-level admissions survived an offline replay. Company facts rendered after server restart, and the actual People demo completed with four synthetic People/two Review, unlocked controls, and an Excel download. The new workbooks' row counts, literal cells, run settings, absence of configured secrets, and earlier artifact integrity were checked.

Artifacts in `backups/extraction-stability-pilot/`:

- `results.json` / `results.xlsx`, `saved-evidence.json`, and `evaluation.json`: first 19/42 output.
- `synthetic-evidence.json`, `synthetic-checks.json`: original 11/12 fixture measurement.
- `followup-results.json` / `.xlsx`, `followup-evidence.json`, and `followup-evaluation.json`: automatic 21/40 output, preserving the new unsupported admission.
- `reviewed-results.json` / `.xlsx`, `reviewed-evaluation.json`, and `manual_review.py`: explicit local audit annotations and 18/43 output; no API calls.
- `manifest.json`, `followup-manifest.json`, and `call_ledger.json`: frozen source/code/expectation hashes and the four attempts. `run.py` and `followup.py` are paid, repeat-guarded scripts; do not rerun to reproduce an offline comparison.

Next work is the remaining semantic extraction/policy failures and fresh real-case validation, followed by bounded retrieval comparison. Zack and Chen are still absent from the saved search results. Wider company scanning and overall department-quality acceptance remain pending.

## Approved title/profile-first policy replay

The user clarified that accurate original titles and corresponding LinkedIn profiles matter more than precise classification, and approved changing the inclusion policy. In active department searches, department/level/role-type labels now serve as search preferences and advisory grouping. Unknown or different labels receive Notes while supported profiles stay in People. Founder/C-level-only searches keep their category limits. Identity, original-title, URL, employer, conflict, and failure checks remain.

An offline replay of the same 65 saved observations produced **41 People / 24 Review**, retaining all 21 earlier automatic People. Of the 20 additions, 16 were previously in Review for classification alone and four were excluded by exact label preferences. Ramp now has 23 People/11 Review and CoreWeave 18/13. Across all 65 candidates, names, titles, profile/evidence URLs, raw text, timestamps, and all factual-support flags are unchanged. All 20 additions already passed those factual checks; all 24 factual failures remain Review, including Nik, Alan, Calvin, and the rewritten founder-title example.

This is a policy change rather than a precision, extraction, or retrieval improvement. Adjacent roles are visible for the user to judge from their titles. Some titles still retain headline wording despite fuller role text elsewhere in the snippet. Current employment was not independently verified. The updated prompt was not invoked live during this replay. No search/model/public-page requests or new API charges were incurred.

Current artifacts are in `backups/evidence-first-replay/`: `results.xlsx` / JSON, `candidates.json`, `audit.json`, `manifest.json`, and offline `replay.py`. `identity-reference.json` omits the old grouping expectations while retaining the same company/name/profile references; `identity-evaluation.json` reports **1/3**, with the other two references still absent from retrieval. `label-diagnostics.json` preserves the earlier label comparison separately. The original reference and every historical result remain unchanged; old strict-policy fixture scores are not rescored as if they measured this new policy.

**619 offline tests pass.** The earlier founder-only replay remains 10 People/42 Review with all ten prior profiles retained. The new workbook's counts, literal cells, clickable profile URLs, metadata, absence of configured keys, and original artifact hashes were checked. Department-label disagreement is now advisory and no longer the delivery gate; future evaluation should prioritize source-supported names/titles/profiles, employer association, useful coverage, and cost.

## Reproduce the offline evaluation

```bash
.venv/bin/python -m company_gtm_enricher.people.evaluation \
  --result backups/department-pilot/results.json \
  --reference examples/people_department_reference.json \
  --output /tmp/department-evaluation.json
```

The evaluator accepts optional `expected_departments` and `expected_seniority` arrays. Presence in People is reported separately from matching the declared role labels; title, department, and level remain visible for mismatches. This comparison does not independently verify that a model-assigned label is true. A negative control is recorded and inspected separately rather than mixed into the positive-coverage denominator.

The ignored local artifact folder contains the immutable first `results.json` / `results.xlsx`, `evidence.json` with search results and complete model responses, `reference.json`, `reference_notes.json`, `criteria.json`, `companies.csv`, and the frozen manifest. `run_pilot.py` makes paid calls and refuses a repeat; `replay_results.py` uses only saved responses, loads no keys, and writes separately named replay artifacts. Once these cases guide a fix, subsequent results on them are development results, not another held-out test.
