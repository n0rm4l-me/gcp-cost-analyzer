"""Entry point — orchestrates billing fetch, resource analysis, AI recommendations, and report generation."""

from __future__ import annotations

import argparse
import os
import sys

from src.billing import fetch_costs
from src.resources import analyze_resources
from src.ai import get_recommendations
from src.report import generate_markdown, save_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GCP Cost Analyzer — autonomous cost analysis powered by Gemini"
    )
    parser.add_argument(
        "--billing-account",
        default=os.environ.get("GCP_BILLING_ACCOUNT_ID"),
        help="GCP Billing Account ID (e.g. XXXXXX-XXXXXX-XXXXXX)",
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT_ID"),
        help="GCP Project ID for resource analysis (optional)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to analyze (default: 30)",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Directory to save Markdown reports (default: reports/)",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip Gemini AI recommendations",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.billing_account:
        print("Error: GCP_BILLING_ACCOUNT_ID not set. Use --billing-account or set env var.")
        sys.exit(1)

    print(f"Fetching billing data for account {args.billing_account} ({args.days}d)...")
    billing = fetch_costs(
        billing_account_id=args.billing_account,
        days=args.days,
        project_id=args.project,
    )
    print(f"Total spend: ${billing.total_cost:,.2f} {billing.currency} ({billing.total_delta})")

    resources = None
    if args.project:
        print(f"Analyzing resources in project {args.project}...")
        resources = analyze_resources(args.project)
        if resources.has_findings:
            print(
                f"Found: {len(resources.idle_disks)} idle disks, "
                f"{len(resources.idle_snapshots)} old snapshots, "
                f"{len(resources.underutilized_node_pools)} underutilized node pools"
            )
            print(f"Estimated monthly waste: ${resources.total_waste_estimate:,.0f}")
        else:
            print("No idle resources detected.")

    ai_recs = None
    if not args.no_ai:
        print("Generating AI recommendations...")
        ai_recs = get_recommendations(billing, resources)
        if ai_recs:
            print("AI recommendations generated.")
        else:
            print("Skipping AI recommendations (GEMINI_API_KEY not set).")

    print("Generating report...")
    content = generate_markdown(billing, resources, ai_recs)
    report_path = save_report(content, args.output_dir)
    print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
