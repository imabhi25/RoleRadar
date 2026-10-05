"""
Command-Line Interface for RoleRadar ATS Ingestion Pipeline.
Supports single-company sync, full registry sync (--all), and dry-run execution.
"""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.clients import BROAD_SOURCES
from ingestion.discovery import DiscoveryStatus, export_new_candidates, run_discovery
from ingestion.pipeline import sync_broad_source, sync_company

CONFIG_FILE = PROJECT_ROOT / "config" / "target_companies.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingestion.cli")


def load_target_companies() -> List[Dict[str, Any]]:
    """Loads target company configuration from config/target_companies.json."""
    if not CONFIG_FILE.exists():
        logger.error("Configuration file not found at %s", CONFIG_FILE)
        raise FileNotFoundError(f"Configuration file not found at {CONFIG_FILE}")

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def print_summary_table(results: List[Dict[str, Any]], dry_run: bool) -> None:
    """Formats and prints an ASCII summary table of sync results."""
    title = "ROLERADAR ATS INGESTION SUMMARY (DRY-RUN - NO WRITES)" if dry_run else "ROLERADAR ATS INGESTION SUMMARY"
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)
    if dry_run:
        print(f"{'Company':<15} {'ATS':<12} {'Status':<10} {'Fetched':<10} {'SWE Roles':<10} {'US/CA':<10} {'Canada':<8} {'CA early':<9} {'Complete'}")
    else:
        print(f"{'Company':<15} {'ATS':<12} {'Status':<10} {'Fetched':<10} {'SWE Roles':<10} {'Upserted':<10} {'Deactivated':<12}")
    print("-" * 80)

    for r in results:
        comp = r.get("company", "Unknown")[:14]
        ats = r.get("ats", "")[:11]
        status = {"partial_success": "partial"}.get(r.get("status", ""), r.get("status", ""))[:9]
        fetched = str(r.get("jobs_fetched", 0))
        swe = str(r.get("swe_jobs_accepted", 0))
        if dry_run:
            print(
                f"{comp:<15} {ats:<12} {status:<10} {fetched:<10} {swe:<10} "
                f"{r.get('eligible_jobs', '-')!s:<10} {r.get('canada_jobs', '-')!s:<8} "
                f"{r.get('canada_early_career_jobs', '-')!s:<9} {r.get('fetch_complete', '-')}"
            )
            continue
        upserted = str(r.get("jobs_upserted", 0))
        deact = str(r.get("jobs_deactivated", 0))
        print(f"{comp:<15} {ats:<12} {status:<10} {fetched:<10} {swe:<10} {upserted:<10} {deact:<12}")

    print("=" * 80 + "\n")
    print_partial_warnings(results)


def print_partial_warnings(results: List[Dict[str, Any]]) -> None:
    """Surface partially successful companies so persistent problems stay visible in the run log."""
    partial = [r for r in results if r.get("status") == "partial_success"]
    if not partial:
        return
    print(f"WARNINGS: {len(partial)} company sync(s) partially succeeded (valid jobs saved, nothing deactivated unsafely):")
    for r in partial:
        detail = r.get("error_message") or "partial snapshot"
        counts = f"parse_errors={r.get('parse_error_count', 0)} record_errors={r.get('record_error_count', 0)}"
        print(f"  - {r.get('company')} [{r.get('ats')}] {counts}: {detail}")
        # GitHub Actions turns this into a yellow annotation instead of failing the workflow
        print(f"::warning title=Ingestion partial::{r.get('company')} ({counts}): {detail}")
    print()


def run_simplify_cli(args) -> int:
    """Simplify discovery: discover -> resolve official URL -> verify -> persist candidates only."""
    from api.database import get_db_connection
    from ingestion.simplify import (
        attach_simplify_urls, load_known_jobs, persist_candidates, run_simplify_discovery,
    )

    try:
        targets = load_target_companies()
    except Exception as err:
        print(f"Error loading company configuration: {err}", file=sys.stderr)
        return 1

    conn = None
    known_jobs = None
    if not args.dry_run:
        conn = get_db_connection()
        with conn.cursor() as cur:
            known_jobs = load_known_jobs(cur)
    try:
        candidates, report = run_simplify_discovery(targets, known_jobs=known_jobs, max_boards=args.max_boards)
        if conn is not None:
            with conn.cursor() as cur:
                # Only in-scope candidates are stored; closed/invalid rows stay in the report counts.
                in_scope = [c for c in candidates if c.in_scope]
                written = persist_candidates(cur, in_scope)
                attached = attach_simplify_urls(cur, in_scope)
            conn.commit()
            report["candidates_persisted"] = written
            report["simplify_urls_attached_to_official_jobs"] = attached
    finally:
        if conn is not None:
            conn.close()

    print("\n" + "=" * 70)
    print(" SIMPLIFY DISCOVERY REPORT" + (" (DRY-RUN - NO WRITES)" if args.dry_run else ""))
    print("=" * 70)
    for key, value in report.items():
        if key in ("registry_recommendations", "failed_sources"):
            continue
        print(f"{key:<38} {value}")
    print(f"{'failed_sources':<38} {len(report['failed_sources'])}")
    for f in report["failed_sources"][:15]:
        print(f"    - {f['source']}: {f['error'][:90]}")
    print("Registry recommendations (verified, not yet configured; Canada first):")
    for r in report["registry_recommendations"][:15]:
        print(f"    - {r['company']} [{r['ats']}:{r['identifier']}] verified={r['verified_postings']} canada={r['canadian_postings']}")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump({"report": report, "candidates": [c.to_dict() for c in candidates]}, fh, indent=1, default=str)
        print(f"\nWrote {len(candidates)} candidate(s) to {args.output}")
    return 0


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description="RoleRadar ATS & Broad Job Ingestion Pipeline CLI",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--company",
        type=str,
        help="Sync a specific company by name or identifier (e.g. 'Figma' or 'figma')",
    )
    group.add_argument(
        "--source",
        type=str,
        help="Sync a broad job source / aggregator (e.g. 'jobicy', 'remotive', 'arbeitnow')",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Sync all verified companies configured in config/target_companies.json",
    )
    group.add_argument(
        "--discover-sources",
        action="store_true",
        help="Discover ATS platforms and tokens for companies in config/company_watchlist.json",
    )
    group.add_argument(
        "--simplify-discovery",
        action="store_true",
        help="Discover early-career candidates from SimplifyJobs repositories and verify them against official sources",
    )
    parser.add_argument(
        "--max-boards",
        type=int,
        default=250,
        help="Maximum number of employer boards to verify per Simplify discovery run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and parse postings without writing to the database",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum pages to fetch for paginated sources (e.g. arbeitnow)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path for newly discovered ATS candidates (used with --discover-sources)",
    )

    args = parser.parse_args(argv)

    # Path 0: Company Watchlist ATS Discovery (--discover-sources)
    if args.discover_sources:
        print("\n" + "=" * 80)
        print(" ROLERADAR ATS SOURCE DISCOVERY")
        print("=" * 80)

        def on_discovery_progress(res):
            comp = res.company[:16]
            st = res.status.value
            if res.status in (DiscoveryStatus.FOUND_EXISTING, DiscoveryStatus.FOUND_NEW):
                prov = res.provider or ""
                tok = res.token or ""
                print(f"{comp:<18} {st:<15} {prov} {tok}")
            elif res.status == DiscoveryStatus.UNSUPPORTED:
                print(f"{comp:<18} {st:<15}")
            else:  # FAILED
                detail = res.details or "Unknown error"
                print(f"{comp:<18} {st:<15} {detail}")

        try:
            report = run_discovery(on_progress=on_discovery_progress)
        except Exception as err:
            logger.error("Discovery failed: %s", err)
            print(f"Error during source discovery: {err}", file=sys.stderr)
            return 1

        print("\n" + "=" * 60)
        print(" ROLERADAR ATS DISCOVERY SUMMARY")
        print("=" * 60)
        print(f"Companies checked:    {report.companies_checked}")
        print(f"Supported ATS found:  {report.supported_ats_found}")
        print(f"Already configured:   {report.already_configured}")
        print(f"New candidates:       {report.new_candidates}")
        print(f"Unsupported:          {report.unsupported}")
        print(f"Failed:               {report.failed}")
        print("=" * 60 + "\n")

        if args.output:
            try:
                num_saved = export_new_candidates(report, args.output)
                print(f"Exported {num_saved} new candidate(s) to: {args.output}\n")
            except Exception as err:
                print(f"Error exporting candidates to {args.output}: {err}", file=sys.stderr)
                return 1

        return 0

    if args.simplify_discovery:
        return run_simplify_cli(args)

    results: List[Dict[str, Any]] = []
    has_failures = False

    # Path 1: Broad aggregator feed (e.g. --source jobicy, remotive, arbeitnow)
    if args.source:
        source_key = args.source.strip().lower()
        if source_key not in BROAD_SOURCES:
            supported = ", ".join(sorted(BROAD_SOURCES))
            print(
                f"Error: Unsupported broad source '{args.source}'. Supported sources: {supported}",
                file=sys.stderr,
            )
            return 1

        try:
            res = sync_broad_source(
                source_name=source_key,
                dry_run=args.dry_run,
                max_pages=args.max_pages,
            )
            results.append(res)
            if res.get("status") == "failed":
                has_failures = True
        except Exception as err:
            logger.error("Unexpected failure executing sync for source %s: %s", source_key, err)
            results.append({
                "company": f"{source_key.title()} Feed",
                "ats": source_key,
                "status": "failed",
                "jobs_fetched": 0,
                "swe_jobs_accepted": 0,
                "jobs_upserted": 0,
                "jobs_deactivated": 0,
                "error_message": str(err),
            })
            has_failures = True

        print_summary_table(results, dry_run=args.dry_run)

        # In dry run mode, print rich smoke-test analytics
        if args.dry_run and results and results[0].get("sample_jobs"):
            r0 = results[0]
            print("ROLE TYPE DISTRIBUTION:")
            for rt, cnt in sorted(r0.get("role_type_counts", {}).items()):
                print(f"  {rt:<15}: {cnt}")
            print("\nWORKPLACE TYPE DISTRIBUTION:")
            for wt, cnt in sorted(r0.get("workplace_counts", {}).items()):
                print(f"  {wt:<15}: {cnt}")
            if r0.get("country_counts"):
                print("\nCOUNTRY DISTRIBUTION:")
                for c_name, cnt in sorted(r0.get("country_counts", {}).items(), key=lambda x: -x[1]):
                    print(f"  {c_name:<20}: {cnt}")
            print(f"\nOLDEST ACCEPTED POSTED_AT : {r0.get('oldest_posted_at')}")
            print(f"NEWEST ACCEPTED POSTED_AT : {r0.get('newest_posted_at')}")
            print(f"OLDER (>45d) POSTINGS OBSERVED: {r0.get('stale_rejected_count')}")
            print("\nREPRESENTATIVE ACCEPTED ROLES (First 10):")
            for idx, sj in enumerate(r0.get("sample_jobs", []), 1):
                p_date = sj.get("posted_at") or "Unknown"
                print(f"  {idx:2d}. [{sj.get('company')}] {sj.get('title')} ({sj.get('role_type')}, {sj.get('workplace')}) | Posted: {p_date}")
            print()

        if has_failures:
            return 1
        return 0

    # Path 2: Direct ATS company sync (--company or --all)
    try:
        companies = load_target_companies()
    except Exception as err:
        print(f"Error loading company configuration: {err}", file=sys.stderr)
        return 1

    targets_to_run: List[Dict[str, Any]] = []

    if args.company:
        search_query = args.company.strip().lower()
        matched = [
            c for c in companies
            if c["name"].lower() == search_query or c["identifier"].lower() == search_query
        ]
        if not matched:
            print(
                f"Error: Company '{args.company}' not found in {CONFIG_FILE}.\n"
                f"Available companies: {', '.join([c['name'] for c in companies])}",
                file=sys.stderr,
            )
            return 1
        targets_to_run = matched
    elif args.all:
        targets_to_run = companies

    for target in targets_to_run:
        try:
            res = sync_company(target, dry_run=args.dry_run)
            results.append(res)
            if res.get("status") == "failed":
                has_failures = True
        except Exception as err:
            logger.error("Unexpected failure executing sync for %s: %s", target.get("name"), err)
            results.append({
                "company": target.get("name"),
                "ats": target.get("ats"),
                "status": "failed",
                "jobs_fetched": 0,
                "swe_jobs_accepted": 0,
                "jobs_upserted": 0,
                "jobs_deactivated": 0,
                "error_message": str(err),
            })
            has_failures = True

    print_summary_table(results, dry_run=args.dry_run)

    if has_failures:
        failed = [r.get("company") for r in results if r.get("status") == "failed"]
        print(f"Note: {len(failed)} company sync(s) failed outright: {', '.join(map(str, failed))}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
