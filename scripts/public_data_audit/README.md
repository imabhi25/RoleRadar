# Public-data audit

A read-only, repeatable audit of every publicly listed job, built so a fix can be measured with the same checks before and after.

```bash
python scripts/public_data_audit/crawl.py https://roleradar-jobs.vercel.app OUT        # GET-only crawl: list, detail, companies, filters
cd frontend && AUDIT_DIR=OUT npx vitest run --config ../scripts/public_data_audit/vitest.audit.config.ts   # render every job as the UI does
python scripts/public_data_audit/analyze.py OUT                                        # metrics.json: counts + job ids per check
python scripts/public_data_audit/compare.py BEFORE AFTER                               # before/after table (RESTRICT_TO=<dir> for the same job set)
```

* `crawl.py` only issues `GET`s to the public job endpoints.
* `ui_render.audit.ts` runs the front end's own code (`renderDescription`, `summarizePosting`, `getJobCardCompensation`,
  `buildJobFacts`, `summarizeLocations`) on each crawled job, so every figure is about **what a reader sees**, not only raw API fields.
* `analyze.py` is written independently of the ingestion and UI rules it audits (own regular expressions and thresholds).
* `replay_snapshot.py` + `rehearse.sh` load a crawl into a scratch PostgreSQL database, apply the migration under test exactly as
  production will, serve it with the real API and re-crawl it: a repair is rehearsed on real rows before it ships.

Not automated here (done by hand against the employers' own APIs): that each job still exists at its source, and the
upstream values behind the individual findings.

Check definitions that are heuristics, not verdicts: `summary_missing_*` compares the clause around a pattern match in the Full
posting with the Summary, policies block and fact tiles; `pay_stated_in_text_*` looks for a range with pay words (salary, pay
range, compensation, base, wage) before it and no equity/bonus word nearer.
