# GTM title extraction and admission

The use case is outbound lead discovery. A known person and usable profile can be valuable without a known job title; a fabricated title is not acceptable input for personalization.

## Policy

- A department search can retain a source-grounded name/profile with no extracted title as `title_missing`. The Title cell remains empty; Notes separately describe uncertain employment. All company-mention, identity, URL, explicit-conflict, former-role, and failure checks still apply.
- Missing or unsupported identities, invalid links, conflicting profile names, and unresolved unsupported title extractions stay in Review. Records with no company mention in source text are discarded from both sheets.
- A company word occurring only inside the person's full supplied name is not company evidence. Excluding that name must still leave an independent company-name/domain/alias mention.
- Founder/C-level-only selection still requires a supported title/category. Missing titles cannot manufacture membership in those groups.

## Extraction change

The prompt separates copying literal facts from deciding whether the copied role belongs to the target company. A missing or uncertain employer link does not erase a title available in the same source. This remains one classification request per batch, subject to existing bounded retries.

Local recovery is intentionally narrow: a missing title can be copied from an unambiguous occupational phrase in the same person's named search headline; a stitched title can be repaired only when its complete original role and appended material can be distinguished. Company-only headings, unrelated people, ambiguous composite roles, and unsupported inventions cannot supply a guessed title. Recovered titles pass the existing employment checks against original evidence. Original text, source links, and processing timestamps remain available.

The preliminary replay exposed real false admissions: titles from Cohere Health, True Anomaly, Rent the Runway, Runway East, and cfo.ai could be copied correctly while still being associated with the wrong target. Recovery therefore preserves a Review hold when an explicit headline employer does not exactly match a configured company identity. It also retains role-local former/date ambiguity. A different person's named headline invalidates identity independently of whether a title was extracted.

## Evaluation method

Replay all 55 saved company responses, including the prior successful Rogo retry, without new searches or model calls. Preserve the 11 prior manual annotations and all historical artifacts. Compare against the 1,437 People / 470 Review company-mention delivery.

Measure actual title recoveries separately from `title_missing` admissions. Check that newly recovered titles occur in their source, links remain bound to returned profiles, company-absent candidates remain excluded, and prior explicit employment/identity conflicts cannot silently enter People. This does not independently verify LinkedIn pages, company identity, current employment, or real-world precision. Prompt changes need separate live evaluation before any claim about future model performance.

## Measured result

Replay of 2,154 saved candidates passed, with **zero new search/model calls or tokens**:

| Output | Rows |
| --- | ---: |
| People: supported | 1,081 |
| People: employment_unconfirmed | 326 |
| People: title_missing | 252 |
| **People total** | **1,659** |
| Review | 146 |
| Discarded | 349 |

Relative to 1,437 People / 470 Review, 254 records moved from Review to People: two repaired-title records and 252 unchanged blank-title records. John Gross now has the source phrase `Chief Innovation Officer` while employment remains uncertain; Mark Butler now has `Technical Recruiting` without the fabricated parenthetical. Across all source candidates, 22 titles were recovered/corrected: two enter People, 11 remain Review, and nine remain discarded for missing company evidence. Five unsupported title strings were cleared and remain Review.

The full-person-name exclusion discards 102 additional records: 31 previous People and 71 Review. Every removed People row was inspected; all target-company tokens were solely within its supplied personal name. The previous People groups are IREN 4, Crusoe 1, Sierra 3, Cline 15, Rogo 1, Lindy 2, and Clay 5.

One additional prior People record, Paraform's Joe/Joseph Boys, moves to Review because the same URL has conflicting displayed names. This may be a display-name variation; the system does not infer nickname equivalence or assert that these are definitely different people.

All 11 prior manual annotations remain, with no changed names/titles in those annotated records. No previously explicit former/conflict record enters People. Original evidence, canonical source bindings, and observation timestamps are preserved. Artifacts: `backups/gtm-title-recovery/run-001/{results,replay_candidates,audit,delta}.json`. This run is frozen; reproduce from the repo root with `.venv/bin/python backups/gtm-title-recovery/run-001/replay_saved.py --run --output-dir backups/gtm-title-recovery/run-002`. The prior Excel workbooks remain historical and are not overwritten.

**873 offline tests pass**, including selected-column Excel export of a blank title with mandatory Status, UI counts, higher-quality duplicate replacement, and failure boundaries. A separate read-only adversarial review checked 13 identity/employer/date/invention/annotation cases. These checks validate implemented behavior; they do not measure independently verified lead precision or response/conversion ROI.

The current workbook is `backups/gtm-title-recovery/export-001/people_gtm.xlsx`. It uses the application's existing exporter and the frozen replay JSON, retaining People, Companies, and Review sheets, all source fields, and mandatory Status. Its export manifest records both source and workbook hashes. Exporting made no new search/model calls and did not modify the frozen replay or previous workbooks.
