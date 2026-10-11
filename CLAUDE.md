# Project working agreements

Read `HANDOFF.md` for current status and `PLAN-people-enrichment.md` for scope.

- The user approved a feature-first direction: add people enrichment with only necessary local architecture changes. Do not restart the redesign discussion.
- Preserve the existing company-enrichment behavior. A general configurable company-field engine is deferred.
- Company inputs and people criteria are configuration. Do not embed the target companies or role policy into processing code.
- Latest user priority: accurate person, original job title, LinkedIn profile, and target-company association. Department/level labels are approximate discovery aids, not a classification-accuracy acceptance gate. Preserve useful evidence-backed candidates when only their category is uncertain; still flag identity, title, employer, or profile-link problems.
- The use case is GTM outreach: balance useful leads against verification cost. Employment uncertainty alone is not a Review gate. During department searches, a missing title alone may enter People as `title_missing`, with a blank Title and an explicit note; identity, profile, evidence, company-mention, and conflict checks still apply. Founder/C-level-only selection still needs category support. Never infer a missing title or identity from company prestige, grouping labels, URL slugs, or prior knowledge.
- Copy source-backed titles independently from employment judgment. Recover extraction omissions only from an unambiguous source phrase; do not stitch fragments. Keep unresolved unsupported extractions, missing/unverified identities, invalid links, explicit mismatches, and ended roles in Review. Retry transient model failures within a counted bound, reusing search evidence; do not retry account/quota/configuration errors.
- Latest explicit user rule: discard real records whose source evidence text contains none of the target company name, domain, or configured aliases. They belong in neither People nor Review. Search queries, generated notes, and the target Company column do not count as source evidence. A company-word match alone still does not prove employment.
- Keep planning inexpensive and explanations concise. No multi-agent planning or research fan-outs; ask before work that exceeds the agreed scope or spend.
- Prefer an end-to-end usable feature, meaningful evaluation, and a reviewable change over speculative infrastructure.
- Run `.venv/bin/python -m pytest` before and after code changes. The existing baseline has 13 tests; add relevant tests for new behavior.
- Archived research is historical context, not verified evidence or approved requirements.
