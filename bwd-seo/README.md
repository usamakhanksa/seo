# Best Web Developer — SEO / AEO / GEO Monitoring

**Production site audited:** https://bestwebdeveloper.org  
**Deployment:** GitHub Actions read-only monitoring; does **not** change WordPress production content or force Google indexing.

## Included evidence

- `data/gsc-baseline.csv`: 1,769 deduplicated GSC URL/reason records from the 16 November 2026 export.
- `data/scheduled-future-posts.csv`: 50 WordPress future posts with verified scheduled publication dates; never generate duplicate placeholder pages for them.
- `scripts/seo_integrity.py`: standard-library Python crawler; checks robots access, HTTP, redirects, sitemap inventory, meta directives, canonical, language, title, meta description, H1, JSON-LD and hreflang counts.
- `tests/test_integrity.py`: safety tests for robots handling, parsing, and future articles.
- `.github/workflows/bwd-seo-integrity.yml`: runs each six hours, on changes, and via manual dispatch.

## Reporting

The workflow checks 275 rotating known URLs per regular run (up to 2 concurrent workers), stores `bwd-seo/reports/audit.csv`, `summary.json`, and `summary.md` as a GitHub Actions artifact retained for 30 days.

Run tests: `python -m unittest discover -s bwd-seo/tests -v`.

Run a manual full inventory audit using **Actions → Best Web Developer SEO AEO GEO Integrity → Run workflow → full=true** (resource intensive). A full audit is not enabled by default to avoid overloading the live origin.

## Boundaries

This is **technical monitoring only**, not automatic remediation. Never interpret `TECHNICALLY_ELIGIBLE` as Google indexed. GSC needs authenticated URL Inspection and validation for indexing status. Intentional noindex URLs, duplicates, WP admin, query parameters, and future posts should not be forcibly indexed. WordPress changes require a verified restorable backup and separate release validation.

The independent ChatGPT six-hour monitoring task may also report detected issues; this repository is the audit trail and does not replace the origin's WordPress cron.
