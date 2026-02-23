#!/usr/bin/env python3
"""Upload E2E test results and screenshots to S3.

Usage:
    cd llm-backend && source venv/bin/activate
    python scripts/upload_e2e_results.py --results-dir ../reports/e2e-runner

Reads Playwright's test-results.json from the results directory, uploads:
  - All screenshots to s3://bucket/e2e-results/screenshots/<run-slug>/
  - latest-results.json to s3://bucket/e2e-results/latest-results.json
  - Timestamped copy to s3://bucket/e2e-results/runs/<run-slug>/results.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from book_ingestion.utils.s3_client import get_s3_client


def upload_results(results_dir: str) -> None:
    results_path = Path(results_dir) / "test-results.json"
    screenshots_dir = Path(results_dir) / "screenshots"

    if not results_path.exists():
        print(f"ERROR: {results_path} not found", file=sys.stderr)
        sys.exit(1)

    results = json.loads(results_path.read_text())

    # Extract runSlug from Playwright config metadata, or generate one
    config = results.get("config", {})
    metadata = config.get("metadata", {})
    run_slug = metadata.get("runSlug")
    if not run_slug:
        now = datetime.now(timezone.utc)
        run_slug = f"e2e-runner-{now.strftime('%Y%m%d-%H%M%S')}"
        # Inject runSlug into metadata so consumers can find it
        if "config" not in results:
            results["config"] = {}
        if "metadata" not in results["config"]:
            results["config"]["metadata"] = {}
        results["config"]["metadata"]["runSlug"] = run_slug

    s3 = get_s3_client()
    uploaded_screenshots = 0

    # Upload screenshots
    if screenshots_dir.is_dir():
        for png in sorted(screenshots_dir.glob("*.png")):
            s3_key = f"e2e-results/screenshots/{run_slug}/{png.name}"
            s3.upload_file(str(png), s3_key)
            uploaded_screenshots += 1
            print(f"  Uploaded screenshot: {png.name}")

    # Upload latest-results.json
    s3.upload_json(results, "e2e-results/latest-results.json")
    print(f"  Uploaded latest-results.json")

    # Upload timestamped copy for history
    s3.upload_json(results, f"e2e-results/runs/{run_slug}/results.json")
    print(f"  Uploaded history: e2e-results/runs/{run_slug}/results.json")

    print(f"\nDone: {uploaded_screenshots} screenshots + results uploaded for run {run_slug}")


def main():
    parser = argparse.ArgumentParser(description="Upload E2E results to S3")
    parser.add_argument(
        "--results-dir",
        default="../reports/e2e-runner",
        help="Path to e2e-runner results directory (default: ../reports/e2e-runner)",
    )
    args = parser.parse_args()
    upload_results(args.results_dir)


if __name__ == "__main__":
    main()
