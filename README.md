# Company GTM Enricher

`company-gtm-enricher` is a local CSV enrichment tool for lightweight go-to-market research. Upload a CSV that contains company names, enrich each row with public business data, and download a refreshed CSV in one pass.

## What It Adds

For each company, the tool appends:

- `HQ City`
- `HQ State`
- `Country`
- `Approximate Annual Revenue`
- `Current Total Funding`

It can also add audit columns:

- `Enrichment Confidence`
- `Source URLs`
- `Enrichment Status`
- `Research Notes`

## How It Works

- Streamlit provides the local web UI for upload, preview, processing, and download.
- Pandas handles CSV parsing and output generation.
- A provider layer keeps enrichment logic separate from the UI.
- The default live provider uses the OpenAI API to do public-web research and return a structured JSON payload.
- OpenAI requests are batched by unique company names to reduce request count.
- A mock provider is included for dry runs and UI testing without an API key.
- The UI shows elapsed runtime and writes an interim backup CSV every 10 minutes during long runs.

## Project Structure

See [Architecture and admission rules](ARCHITECTURE.md) for the People workflow, module boundaries, exact filtering policy, and current Review diagnostics.

```text
.
├── app.py
├── backups/
├── examples/
│   └── companies.csv
├── src/company_gtm_enricher/
│   ├── cli.py
│   ├── config.py
│   ├── cost_estimator.py
│   ├── csv_tools.py
│   ├── enrichment_service.py
│   ├── models.py
│   ├── providers/
│   └── people/
├── tests/
├── .env.example
├── .gitignore
├── LICENSE
└── pyproject.toml
```

## Quick Start

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

### 3. Configure API keys

In the web UI, open **API keys** in the sidebar and enter your OpenAI key. **People → Search + LLM** also needs a Serper key. Demo/mock runs need neither.

For CLI use or server defaults, create `.env` only if it does not already exist:

```bash
test -f .env || cp .env.example .env
```

Fill in `OPENAI_API_KEY` and, for people search, `SERPER_API_KEY`. Restart Streamlit after editing `.env` to reload the defaults. `.env` is ignored by Git.

Nonempty sidebar keys override server defaults for the current session. Blank fields use the corresponding server key, so an app owner can provide Serper while users supply their own OpenAI key. The sidebar shows which source is in use without displaying server keys. **Clear entered keys** restores server defaults; keys are locked while a run is active.

Entered keys are sent to the Streamlit server to make API requests and held in that session's memory. The app does not persist entered keys to `.env` or include them in run settings. Reloading into a new session requires entering them again. The app owner's configured keys remain available to sessions with blank inputs.

If a running development server reports an unexpected keyword argument or a missing result attribute after pulling changes, stop and restart Streamlit. Imported modules and existing session objects can retain an older interface across code updates; a browser refresh alone may not reset both. Restarting clears in-memory run state, while saved files remain available.

### 4. Run the app

```bash
python -m streamlit run app.py
```

The app will open locally and let you:

- upload a CSV
- select the company-name column
- choose the provider
- tune the request batch size
- estimate cost across curated OpenAI, Claude, and MiniMax models before starting
- run enrichment
- pause, resume, or stop an in-flight run
- see elapsed runtime while the job is active
- download the latest interim backup if a 10-minute flush has occurred
- download the enriched CSV

## CLI Usage

### People enrichment

The **People** mode has two sources: **Demo (no API calls)** and **Search + LLM**. Demo uses synthetic people with blank LinkedIn URLs. Search + LLM uses Serper's search index, then OpenAI structured extraction and suggested grouping, followed by deterministic evidence checks. The app never requests LinkedIn pages directly.

For the offline walkthrough, select **People**, keep the Demo source, click **Use demo companies**, then **Run people demo**. Founders and C-level are selected by default. Department, leadership, and individual-contributor selectors accept multiple choices and custom labels. Suggestions live in `src/company_gtm_enricher/people/role_options.json`.

A department search is active when at least one department and one leadership or individual-contributor level are selected. Those labels guide retrieval and suggested grouping. Department and level labels are approximate: an evidence-backed profile may remain in People when its label is unknown, differs from a preference, or describes an adjacent role. Original titles are retained, and Notes explain grouping uncertainty or adjacent roles so users can judge relevance. Without an active department search, results remain limited to the selected founder/C-level title categories.

Each selected department has an editable **definition** under Department roles. The default Product definition includes Product Marketing and Product Partnerships; defaults for AI, Infrastructure, and Engineering are also editable in `role_options.json`. Custom departments start with a blank definition. Clearing a definition returns that department to label-only guidance. Edits stay in the current web session, including when a department is deselected and later reselected; they do not change the defaults for other users. The controls are locked during a run.

Definitions guide suggested department grouping. Evidence checks require a grounded identity, original title, and profile link, and distinguish uncertain current employment from conflicting company evidence. Current-employment uncertainty alone can remain in People with an explicit status. Definitions do not expand search queries or the query budget, and a definition is not evidence that a person holds a role. The actual definitions are snapshotted in run settings and exported with the results. Python callers can pass `PeopleCriteria(department_definitions={...})` for selected departments; omitted definitions retain label-only behavior at that API boundary. UI and CLI apply the shared presets.

Equivalent level spellings (for example, Senior Vice President and SVP) normalize to the same label through `people/seniority_aliases.json`. This keeps grouping consistent while preserving distinctions such as Senior Director and Director; it does not determine eligibility or create a minimum-rank threshold. The classifier requests one source-bound observation per hit. Copied job titles and suggested classification labels are separate fields; schema completeness does not establish semantic correctness.

The CLI uses the same workflow:

```bash
python -m company_gtm_enricher.cli --mode people --provider mock \
  --input examples/people_demo.csv --output people_demo.xlsx
```

Use `examples/target_companies.csv` to try the larger sample; its `input_name` column is detected automatically. Optional `domain`, `lists`, and `aliases` columns are detected, or can be mapped with `--domain-column`, `--lists-column`, and `--aliases-column`. The web UI provides the same optional column mappings. Duplicate normalized name/domain pairs merge their tags and aliases. An ambiguous name is not automatically resolved to a real company.

For the user's live target list, [target_companies_ready.csv](examples/target_companies_ready.csv) adds company names, official domains, explicit aliases, and identity-source notes checked on 2026-09-17. It preserves all 55 original inputs and 64 list memberships. Product inputs such as Bolt and Vercel/v0 map to their employers; the original `input_name` remains available for comparison. These mappings identify the search targets, not individual employment. The original two-column input is unchanged.

Use `aliases` for known previous or alternate names, separated by `;` or `|`. For example, `examples/people_pilot.csv` supplies `Repl.it` as an alias for Replit, allowing evidence that uses its older name to be matched. Aliases are explicit input, not guesses from similar spelling, and do not merge companies with different names or domains. Commas within an alias are preserved; quote the CSV cell when it contains a comma.

Use aliases that distinguish the intended employer. A correct but shared name can still introduce a namesake company: the first full pass found this with OpenCode's creator name `Anomaly`. The reusable ready CSV now omits that alias, and the delivery copy holds generic Anomaly-only matches for company-identity review. The run's frozen input preserves what was actually searched.

Additional criteria example:

```bash
python -m company_gtm_enricher.cli --mode people --provider mock \
  --input examples/people_demo.csv --output people_demo.xlsx \
  --departments "AI,Engineering" --leadership-levels "Director,Head" \
  --ic-levels "Staff,Principal" --columns "Company,Name,Title,LinkedIn URL"
```

Use `--no-founders` or `--no-c-level` to skip those search groups. In a founder/C-level-only search, these flags also control which title categories qualify; an active department search may retain returned profiles with grounded names, titles, and profile links, including explicitly marked current-employment uncertainty. Former employment and conflicting person, title, or company evidence still require Review. The workbook always contains **People**, **Companies**, and **Review**, with a synthetic-data banner on every sheet for demo runs. Selected People columns always retain Status; Review keeps all diagnostic fields. The mock supplies one uncertainty example per company to demonstrate review handling, not a measured error rate.

The CLI can override definitions using a JSON object mapping labels to descriptions, such as [this example](examples/department_definitions.json):

```bash
python -m company_gtm_enricher.cli --mode people --provider mock \
  --input examples/people_demo.csv --output people_demo.xlsx \
  --no-founders --no-c-level --departments "Product" --leadership-levels "Director,Head" \
  --department-definitions examples/department_definitions.json --result-json people_demo.json
```

Overrides match selected labels without regard to case. A blank string removes that default definition; omitted entries retain presets. A reusable file may contain other departments, but only selected definitions reach the model. Invalid JSON/definition values and attempts to overwrite the definitions input are rejected before provider construction. Demo output tests the workflow only; it does not measure semantic classification quality.

For live search, enter OpenAI and Serper keys in the **API keys** sidebar or configure `OPENAI_API_KEY` and `SERPER_API_KEY` in the local `.env`, choose **Search + LLM**, and upload your company CSV. [Serper](https://serper.dev/) provides Google search results, including profile links and snippets; OpenAI extracts and classifies those results. These are separate services with separate credentials. Provide company domains where possible; a missing domain contributes to company-identity uncertainty but does not alone force Review. Source text must still mention the supplied company name or an alias. Built-in fictional demo companies cannot be submitted through the live UI.

To obtain the search key, [create a Serper account](https://serper.dev/signup), then copy its API key from the account dashboard into the sidebar's **Serper API key** field or `SERPER_API_KEY` in `.env`. The endpoint and authentication header are already implemented. Sidebar entries take effect without restarting the app.

Serper is the first retrieval implementation because its structured links/snippets fit evidence grounding and let search budgets be measured separately from classification. This is an MVP choice, not a measured comparison against other providers. Search-index coverage and freshness still need evaluation. As checked on 2026-09-17, [Serper's homepage](https://serper.dev/) offers 2,500 free queries without a credit card; it does not promise a monthly reset. For 55 companies, founders/C-level plan 110 searches; adding four departments' leadership groups plans 330, and adding their IC groups plans 550. These estimates exclude retries and assume the caps permit all planned queries. The default four-query cap omits later groups when more are selected; increase it to the planned group count for that scope. All queries within that budget run before candidates are selected round-robin across successful query groups. The candidate cap limits the distinct profiles sent to classification, with omitted returned profiles counted in Companies notes. OpenAI usage is billed separately.

```bash
python -m company_gtm_enricher.cli --mode people --provider openai \
  --input companies.csv --output people.xlsx --result-json people_run.json \
  --max-queries-per-company 4 --max-candidates 40
```

`OPENAI_PEOPLE_MODEL` defaults to `gpt-5-mini` independently of the existing company model. `PEOPLE_TIMEOUT_SECONDS` defaults to **90 seconds per attempt**. `PEOPLE_MAX_QUERIES_PER_COMPANY` and `PEOPLE_MAX_CANDIDATES` set the live limits; the CLI also accepts `--model`. API keys are never included in run metadata.

The production People provider defaults to **two model retries**, allowing at most **three attempts** for a classification batch. Set `PEOPLE_LLM_MAX_RETRIES` to `0`, `1`, or `2`; `0` disables these retries. Only SDK timeout/connection failures and HTTP 408, 409, 429 (excluding exhausted quota), or 5xx responses are retried, with waits of one and then two seconds. Each retry reuses the retrieved search hits; it does not rerun Serper searches. Every actual model attempt, including failures, increments request usage. OpenAI SDK implicit retries are disabled, so retries do not multiply across layers. Refusals and malformed/incomplete model output are not retried automatically. Search retries are separately bounded; authentication, credit, or model-configuration errors stop subsequent company requests.

Retrieval receives the selected role groups. The LLM copies names/titles and suggests structured labels from supplied search text; it cannot supply profile URLs or make the final inclusion decision. Profile URLs come from returned search results or explicitly named company links when the optional founder source is enabled. During a department search, an uncertain or mismatched grouping label alone does not force Review. Evidence handling is visible in the mandatory Status column:

Before admission to either sheet, real records must contain the target company name, domain, or a configured alias in their retained **Evidence Text**, outside occurrences of the person's complete supplied name. Matching ignores case and repeated whitespace and uses whole phrases. Records with no match are discarded from both People and Review, including retained evidence from failed processing. Queries, target columns, generated notes, and a source URL alone do not satisfy this check. Companies notes report discard counts. A match is only a minimum evidence requirement: a skill keyword or namesake can still match without proving employment.

| Sheet | Status | Meaning |
| --- | --- | --- |
| People | `supported` | Name, original title, profile, and current-company association are supported by retained source evidence. |
| People | `employment_unconfirmed` | Name, original title, and profile are grounded, but current employment is uncertain; no explicit former-employment or conflicting association was established. Notes explain the uncertainty. |
| People | `title_missing` | During department searches, the name/profile pass evidence checks but no title was extracted. Title stays blank; Notes separately describe employment uncertainty. This is a lead for consideration, with no job-title claim for personalized outreach. |
| Review | `needs_review` | Identity/profile evidence is missing or unsupported, a title extraction cannot be grounded or safely repaired, or the evidence describes former employment or a person, title, or company mismatch. Founder/C-level-only searches also require category support. |
| Review | `processing_failed` | Discovery or classification failed; available evidence is preserved for a later retry rather than treated as an extracted lead. |

No People status means employment was independently verified. A missing title alone does not justify losing a usable GTM lead, but an invented title must never become a personalization fact. Title copying and employment judgment are separate: an uncertain employer association must not erase a supported title. A deterministic recovery may copy an unambiguous role from the same person's search headline; it cannot invent or concatenate words. **Observed At** is the time the evidence was processed, not the date the person's job changed.

Search coverage is always partial. Query caps prioritize founders/C-level, then departments in selection order; later groups may be skipped. The UI warns before a capped run, and Companies records omissions, failures, and retained-candidate counts. Every workbook reports run settings and request/token usage. `--result-json` preserves the complete run for evaluation. API charges are not inferred from request counts.

The [55-company first-pass report](EVAL-target-companies.md) records the wider run's scope and evidence: **550 search requests and 55 model attempts, with no retries**. Those historical counts predate the new model-retry defaults and remain unchanged. [Scan cadence](PEOPLE-scan-cadence.md) recommends a weekly refresh for ten active application targets and a four-week refresh for the rest, separating base requests from potential retries. No recurring scan or scheduler is enabled.

The [GTM title-recovery replay](EVAL-gtm-title-recovery.md) now yields **1,659 People / 146 Review**, with 326 unconfirmed-employment rows and 252 blank-title leads. Two repaired titles and 252 unchanged blank-title records enter People; 102 name-only company matches are discarded, and one ambiguous displayed-name record moves to Review. All 2,154 saved candidates were replayed without new API calls. Download the [latest Excel](backups/gtm-title-recovery/export-001/people_gtm.xlsx), exported from the validated JSON `backups/gtm-title-recovery/run-001/results.json`; the new prompt has not been live-tested.

The earlier [company-mention policy replay](EVAL-review-policy.md) yielded **1,437 People / 470 Review**, including 356 People with unconfirmed employment, and discarded 247 records with no company mention. Its [workbook](backups/company-mention-filter/run-001/results.xlsx) remains a historical artifact and has not been overwritten. Rogo's earlier recovery used one additional model request and zero searches. These are contact-discovery results, not independently verified current employment.

The code is tested with injected search/API responses and a [three-company pilot with a controlled follow-up](EVAL-people-pilot.md). Reclassifying the same 52 saved profiles after admission/alias fixes increased supported People from 8 to 10 and reference-founder coverage from 3/6 to 5/6; 42 profiles remain in Review. The follow-up used three new OpenAI calls; a separate one-credit Serper diagnostic did not resolve the remaining founder's missing evidence. Classification failures preserve retrieved evidence in Review while keeping the company in error. This is a small reference check, not complete-roster recall; dollar charges remain unmeasured. The implementation follows [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and [Serper's published search example](https://github.com/Serper-API/search_with_lepton/blob/main/search_with_lepton.py).

The optional **Check company founder links** checkbox adds company-published evidence. It reads `/about` and `/careers`, and may follow one directly linked public job page. It accepts explicit “Our founders/co-founders are …” statements with named LinkedIn links; externally hosted jobs must identify the same company and domain in their `JobPosting` metadata. It does not infer a profile from a matching name. At most three HTTP requests per company are allowed, including redirects and failed requests; LinkedIn pages are never fetched. The candidate limit counts unique profiles; conflicting names for one profile may produce multiple Review observations. This source covers a narrow statement format and may find nothing. It adds no Serper or LLM calls, is off by default, and runs only when founders are selected.

```bash
.venv/bin/python -m company_gtm_enricher.cli --mode people --provider openai \
  --input examples/people_pilot.csv --output people.xlsx --result-json people.json \
  --company-founder-pages
```

On the same saved pilot evidence, the optional source resolved Bret's profile using Sierra's own linked job page: **11 People / 41 Review, 6/6 reference founders**. This added nine public-page requests across three companies and no new paid API calls. It is a development-sample result, not a held-out precision or complete-roster estimate. Page request counts and source chains are retained in output.

Evaluate an exported run against an explicit reference without making requests:

```bash
.venv/bin/python -m company_gtm_enricher.people.evaluation \
  --result people.json --reference examples/people_pilot_reference.json --output evaluation.json
```

The report distinguishes exact profile/name/company matches from weaker name-only coverage, shows missing/Review entries and identity conflicts, and preserves the run's observed usage. References can also provide `expected_departments` and `expected_seniority` as nonempty lists of acceptable exact labels; see [the department reference](examples/people_department_reference.json). `people_reference_count` records presence in People, including `employment_unconfirmed` rows; `supported_reference_count` requires an unambiguous row with Status `supported` and matching supplied role expectations. These reference label checks measure grouping agreement separately from the current People inclusion policy. A role mismatch stays visible with its observed title, department, and seniority. The report does not independently verify current employment or titles, and does not invent billed costs.

A [separate department-role pilot](EVAL-people-departments.md) on Ramp/CoreWeave found only 1/3 predeclared references under the previous exact-label policy. Its first output was 8 People / 55 Review; offline formatting/rank corrections changed this to 14 / 48 on the same evidence. At that stage, one known level mismatch went to Review, while department ambiguity and retrieval gaps remained. These counts are not verified precision or complete coverage. The initial paid run used eight search credits and two model calls; the corrections required no additional requests.

A later two-call development follow-up supplied the new department definitions to the same 65 profiles, without new searches. Product Marketing mapped to Product and Applied Research abstained from that mapping, but overall admission regressed to **3 People / 61 Review, 0/3 reference coverage** because extraction and level formatting remained inconsistent. Configurability is implemented; better overall classification quality is not established. Both outputs and full responses are preserved in the evaluation report's artifact locations.

Subsequent bounded extraction work returned observations for all 65 profiles and restored 1/3 reference coverage under that policy. Its final automatic output was **21 People / 40 Review**; manual evidence review moved three uncertain/unsupported admissions to Review, leaving **18 / 43** in a separately annotated workbook. One remaining grouping error mapped Financial Partnerships to Product without product evidence. A separate fictional 12-case fixture matched 11 cases, with one safe abstention; this is not measured real-company precision. Four model calls and zero new searches were used. Full comparisons, failed checks, and artifact locations are in the [department evaluation report](EVAL-people-departments.md).

An earlier department-search policy change retained evidence-backed profiles despite approximate or mismatched grouping labels, while still requiring supported current affiliation. Offline replay of the same 65 saved observations yielded **41 People / 24 Review**, retaining all 21 earlier automatic admissions and adding 20 whose factual evidence was already supported. Names, original titles, profile URLs, company evidence, and their support flags were unchanged; all 24 factual failures remained Review under that policy. This replay made **zero API calls**, and identity-reference coverage remained 1/3 because the other two reference profiles were absent from retrieval. Its workbook is `backups/evidence-first-replay/results.xlsx`. These are historical results from before the `employment_unconfirmed` status described above, not newly verified employment, more complete extraction, or improved retrieval. That offline replay did not live-test its prompt. At that stage, the full suite had **619 passing tests**.

The UI supports pause/resume/stop between companies and downloads of partial results. Pending companies and provider failures remain visible in Companies. UI runs save local Excel backups every 10 minutes between companies and on completion or stop; unexpected failures retain available partial results. Backups use unique filenames under `backups/`. CLI runs write the requested Excel and optional JSON outputs, returning exit code 2 when the run fails or has company errors while preserving available results. Run state is held in memory; saved workspaces and restart/resume are not included.

### Company enrichment

You can also run enrichment without the web UI:

```bash
python -m company_gtm_enricher.cli --input examples/companies.csv --output enriched.csv --provider mock
```

Example with a live provider:

```bash
python -m company_gtm_enricher.cli --input companies.csv --output companies_enriched.csv --provider openai
```

Useful flags:

- `--company-column` to explicitly choose the company-name column
- `--model` to override the OpenAI model
- `--batch-size` to choose how many unique companies go into each request
- `--no-audit-columns` to keep the output narrower

## Runtime Behavior

- The app processes unique company names in batches and reuses results for duplicates in the same upload.
- `Pause` holds the run state in memory and resumes between batches.
- `Stop` ends the run and writes a backup CSV if any rows were already processed.
- The original uploaded file is never modified in place.
- A completed run exposes the final `Download enriched CSV` action in the UI.
- Interim backup files are written under `backups/` and can be downloaded from the run-status section.

## Cost Estimator

- The UI includes a `Cost Estimator` section that compares 6 curated models.
- Included providers: OpenAI, Anthropic, and MiniMax.
- Included models:
  - OpenAI: `GPT-5`, `GPT-5 mini`
  - Anthropic: `Claude Sonnet 4.5`, `Claude Haiku 4.5`
  - MiniMax: `MiniMax-M2.5`, `MiniMax-M2.5-highspeed`
- The estimator uses:
  - company count
  - batch size
  - shared prompt tokens per request
  - estimated input tokens per company
  - estimated output tokens per company
- MiniMax pricing is shown in provider-native `CNY`; OpenAI and Anthropic are shown in `USD`.
- The estimator is informational only and does not affect the actual enrichment run.

## Interim Backups

- The worker writes an interim backup CSV every `10` minutes during an active run.
- If the run is stopped or fails after partial progress, it flushes one more backup immediately.
- Unprocessed rows in a backup are marked with `Enrichment Status = pending`.
- Backup files are local-only and ignored by git.

## Input Requirements

- CSV format only
- At least one column containing company names
- If the file has a single column, the app uses it automatically
- If the file has multiple columns, the app lets you select the company-name column

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Required for live enrichment |
| `OPENAI_MODEL` | `gpt-4o-mini-search-preview` | Search-capable model used by the OpenAI provider |
| `OPENAI_TIMEOUT_SECONDS` | `45` | Company-enrichment OpenAI request timeout |
| `OPENAI_BATCH_SIZE` | `10` | Default number of unique companies per OpenAI request |
| `MAX_COMPANIES_PER_RUN` | empty | Optional cap for UI batch size. Empty or `0` means unlimited |
| `SERPER_API_KEY` | empty | Search credential for live People enrichment |
| `OPENAI_PEOPLE_MODEL` | `gpt-5-mini` | Model for People extraction and suggested grouping |
| `PEOPLE_TIMEOUT_SECONDS` | `90` | People search/model timeout in seconds per attempt; maximum 120 |
| `PEOPLE_LLM_MAX_RETRIES` | `2` | Transient model retries, from 0 to 2; at most three attempts |
| `PEOPLE_MAX_QUERIES_PER_COMPANY` | `4` | People search query limit, from 1 to 20 |
| `PEOPLE_MAX_CANDIDATES` | `40` | Distinct profiles sent to classification, from 1 to 100 |

## Notes on Data Quality

- Revenue and funding are intentionally approximate.
- Public company data is often easier to verify than private-company data.
- The audit columns are useful when you need to review low-confidence rows manually.
- Duplicate company names in the same upload are cached during a run to avoid duplicate lookups.
- Pause or stop actions take effect between request batches, so a large batch may need to finish before the UI reflects the action.
- Interim backups are written to `backups/` every 10 minutes and again on stop/failure when partial progress exists.

## Current Limits

- The current UI keeps active run state in memory while the app process is alive.
- If the Streamlit process is restarted before the next backup flush, the most recent in-memory progress can still be lost.
- Backup cadence is time-based, not row-count-based.

## Tests

Run the test suite with:

```bash
python -m pytest
```

## Future Improvements

- Extend bounded retry handling to the original company-enrichment workflow
- Add optional source weighting or domain allowlists
- Add background job processing for larger CSV files
- Export a second review-only CSV for low-confidence rows

## License

MIT
