"""
Test Scenarios API - Serves scenario definitions from scenarios.json and results from Playwright's native JSON report.

Endpoints:
  GET /api/test-scenarios                              - List functionalities with latest results
  GET /api/test-scenarios/{slug}                       - Scenario detail + results for a functionality
  GET /api/test-scenarios/{slug}/screenshots/{scenario_id} - Presigned S3 URLs for screenshots
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from botocore.exceptions import ClientError

from book_ingestion.utils.s3_client import get_s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/test-scenarios", tags=["test-scenarios"])

S3_RESULTS_KEY = "e2e-results/latest-results.json"
S3_SCREENSHOTS_PREFIX = "e2e-results/screenshots"


def _resolve_scenarios_json() -> Path:
    """Find e2e/scenarios.json - works both locally and in Docker."""
    # In Docker: /app/e2e/scenarios.json (copied during build)
    docker_path = Path(__file__).parent.parent / "e2e" / "scenarios.json"
    if docker_path.exists():
        return docker_path
    # Local dev: repo_root/e2e/scenarios.json
    local_path = Path(__file__).parent.parent.parent / "e2e" / "scenarios.json"
    if local_path.exists():
        return local_path
    raise FileNotFoundError("e2e/scenarios.json not found")


def _slugify(name: str) -> str:
    """Convert suite name to slug: 'Admin — Books Dashboard' → 'admin-books-dashboard'."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _step_to_human(step: dict) -> str:
    """Convert a scenario step dict to a human-readable string."""
    action = step.get("action", "")
    if action == "navigate":
        url = step.get("url", "/")
        if url == "/":
            return "Open the app home page"
        return f"Go to {url}"
    elif action == "click":
        sel = step.get("selector", "")
        desc = sel.replace("[data-testid='", "").replace("']", "").replace(":first-child", " (first item)")
        desc = desc.replace("-", " ")
        return f"Click on {desc}"
    elif action == "waitForSelector":
        sel = step.get("selector", "")
        desc = sel.replace("[data-testid='", "").replace("']", "").replace(":first-child", "")
        desc = desc.replace("-", " ")
        return f"Wait for {desc} to appear"
    elif action == "type":
        value = step.get("value", "")
        sel = step.get("selector", "")
        desc = sel.replace("[data-testid='", "").replace("']", "").replace("-", " ")
        return f"Type '{value}' into {desc}"
    elif action == "screenshot":
        label = step.get("label", "screen")
        return f"Take a screenshot ({label.replace('-', ' ')})"
    elif action == "waitForResponse":
        return "Wait for the response to arrive"
    else:
        return f"{action}: {json.dumps(step)}"


def _assertions_to_expected(assertions: list) -> str:
    """Convert assertions list to a human-readable expected result string."""
    parts = []
    for a in assertions:
        atype = a.get("type", "")
        sel = a.get("selector", "")
        desc = sel.replace("[data-testid='", "").replace("']", "").replace("-", " ")
        if atype == "visible":
            parts.append(f"The {desc} is visible on the page.")
        elif atype == "countAtLeast":
            count = a.get("count", 1)
            parts.append(f"At least {count} {desc} elements are shown.")
        else:
            parts.append(f"{atype}: {sel}")
    return " ".join(parts) if parts else "Page loads without errors."


def _fetch_local_playwright_results() -> Optional[dict]:
    """Read Playwright's test-results.json from local reports directory."""
    # Docker: /app/reports/e2e-runner/test-results.json
    docker_path = Path(__file__).parent.parent / "reports" / "e2e-runner" / "test-results.json"
    if docker_path.is_file():
        try:
            return json.loads(docker_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to read local Playwright results at {docker_path}: {e}")
    # Local dev: repo_root/reports/e2e-runner/test-results.json
    local_path = Path(__file__).parent.parent.parent / "reports" / "e2e-runner" / "test-results.json"
    if local_path.is_file():
        try:
            return json.loads(local_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to read local Playwright results at {local_path}: {e}")
    return None


def _fetch_latest_results() -> Optional[dict]:
    """Fetch latest Playwright results: try S3 first, fall back to local file."""
    try:
        s3 = get_s3_client()
        result = s3.download_json(S3_RESULTS_KEY)
        if result is not None:
            return result
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
            logger.warning(f"Failed to fetch latest results from S3: {e}")
    except Exception as e:
        logger.warning(f"Failed to fetch latest results from S3: {e}")

    # Fallback: local results file
    return _fetch_local_playwright_results()


def _load_playwright_results(pw_data: Optional[dict]) -> tuple[dict[tuple[str, str], dict], Optional[str], Optional[str]]:
    """Parse Playwright's JSON report into a flat lookup.

    Returns:
        (results_by_key, run_slug, timestamp)
        results_by_key: dict keyed by (suite_title, spec_title) → {status, duration, error}
        run_slug: extracted from metadata or None
        timestamp: from stats.startTime or None
    """
    results: dict[tuple[str, str], dict] = {}
    run_slug = None
    timestamp = None

    if not pw_data:
        return results, run_slug, timestamp

    # Extract metadata
    config = pw_data.get("config", {})
    metadata = config.get("metadata", {})
    run_slug = metadata.get("runSlug")

    # Timestamp from stats
    stats = pw_data.get("stats", {})
    timestamp = stats.get("startTime")

    # Walk the nested suites structure
    # Playwright JSON: suites[0].suites[0].title = describe block
    #                  suites[0].suites[0].specs[0].title = test name
    def walk_suites(suite_list: list, parent_title: str = ""):
        for suite in suite_list:
            title = suite.get("title", "")
            # Use the innermost describe block title as the suite name
            current_title = title if title else parent_title

            for spec in suite.get("specs", []):
                spec_title = spec.get("title", "")
                tests = spec.get("tests", [])
                if tests:
                    # Take the last test (last project run), last result (last retry)
                    last_test = tests[-1]
                    test_results = last_test.get("results", [])
                    if test_results:
                        last_result = test_results[-1]
                        status = last_result.get("status", "unknown")
                        # Map Playwright statuses to our simple statuses
                        if status == "passed":
                            mapped_status = "passed"
                        elif status in ("failed", "timedOut"):
                            mapped_status = "failed"
                        else:
                            mapped_status = status

                        error_msg = None
                        errors = last_result.get("errors", [])
                        if errors:
                            error_msg = errors[0].get("message", "")

                        results[(current_title, spec_title)] = {
                            "status": mapped_status,
                            "duration": last_result.get("duration", 0),
                            "error": error_msg,
                        }

            # Recurse into nested suites
            if suite.get("suites"):
                walk_suites(suite["suites"], current_title)

    walk_suites(pw_data.get("suites", []))

    return results, run_slug, timestamp


@router.get("")
def list_test_scenarios():
    """List all test case functionalities with latest results."""
    try:
        scenarios_path = _resolve_scenarios_json()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="scenarios.json not found")

    scenarios_data = json.loads(scenarios_path.read_text())
    suites = scenarios_data.get("suites", [])

    # Fetch and parse Playwright results
    pw_data = _fetch_latest_results()
    pw_results, _run_slug, results_timestamp = _load_playwright_results(pw_data)

    functionalities = []
    for suite in suites:
        suite_name = suite.get("name", "")
        slug = _slugify(suite_name)
        scenarios = suite.get("scenarios", [])
        scenario_count = len(scenarios)

        # Count pass/fail from Playwright results
        passed = 0
        failed = 0
        has_results = False
        for sc in scenarios:
            key = (suite_name, sc.get("name", ""))
            result = pw_results.get(key)
            if result:
                has_results = True
                if result["status"] == "passed":
                    passed += 1
                elif result["status"] == "failed":
                    failed += 1

        if has_results:
            status = "failed" if failed > 0 else "passed"
        else:
            status = "not_run"

        functionalities.append({
            "slug": slug,
            "name": suite_name,
            "filename": f"{slug}.md",
            "scenario_count": scenario_count,
            "last_tested": results_timestamp if has_results else None,
            "status": status,
            "passed": passed,
            "failed": failed,
        })

    return {"functionalities": functionalities}


@router.get("/{slug}")
def get_test_scenario_detail(slug: str):
    """Return structured scenario data + test results for a specific functionality."""
    if ".." in slug or "/" in slug:
        raise HTTPException(status_code=404, detail="Invalid slug")

    try:
        scenarios_path = _resolve_scenarios_json()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="scenarios.json not found")

    scenarios_data = json.loads(scenarios_path.read_text())

    # Find the matching suite
    target_suite = None
    for suite in scenarios_data.get("suites", []):
        if _slugify(suite.get("name", "")) == slug:
            target_suite = suite
            break

    if target_suite is None:
        raise HTTPException(status_code=404, detail="Test suite not found")

    suite_name = target_suite.get("name", "")

    # Fetch and parse Playwright results
    pw_data = _fetch_latest_results()
    pw_results, _run_slug, last_tested = _load_playwright_results(pw_data)

    # Build scenarios response
    scenarios = []
    has_results = False
    any_failed = False

    for sc in target_suite.get("scenarios", []):
        sc_id = sc.get("id", "")
        sc_name = sc.get("name", "")

        # Convert steps to human-readable
        steps = [_step_to_human(step) for step in sc.get("steps", [])]
        expected_result = _assertions_to_expected(sc.get("assertions", []))

        # Derive screenshot filenames from scenario steps
        screenshots = []
        for step in sc.get("steps", []):
            if step.get("action") == "screenshot":
                screenshots.append(f"{sc_id}-{step['label']}.png")

        # Merge Playwright result
        key = (suite_name, sc_name)
        result = pw_results.get(key)
        if result:
            has_results = True
            sc_status = result["status"]
            if sc_status == "failed":
                any_failed = True
                # Add failure screenshot
                screenshots.append(f"{sc_id}-FAILURE.png")
        else:
            sc_status = "not_run"

        scenarios.append({
            "id": sc_id,
            "name": sc_name,
            "status": sc_status,
            "steps": steps,
            "expected_result": expected_result,
            "screenshots": screenshots,
        })

    if has_results:
        suite_status = "failed" if any_failed else "passed"
    else:
        suite_status = "not_run"

    return {
        "slug": slug,
        "name": suite_name,
        "last_tested": last_tested if has_results else None,
        "status": suite_status,
        "scenarios": scenarios,
    }


@router.get("/{slug}/screenshots/{scenario_id}")
def get_scenario_screenshots(slug: str, scenario_id: str):
    """Return presigned S3 URLs for a scenario's screenshots."""
    if ".." in slug or "/" in slug or ".." in scenario_id or "/" in scenario_id:
        raise HTTPException(status_code=404, detail="Invalid parameters")

    # Load scenarios.json to derive screenshot filenames
    try:
        scenarios_path = _resolve_scenarios_json()
    except FileNotFoundError:
        return {"scenario_id": scenario_id, "screenshots": []}

    scenarios_data = json.loads(scenarios_path.read_text())

    # Find the scenario and derive screenshot filenames from steps
    screenshot_filenames: list[str] = []
    suite_name = ""
    sc_name = ""
    for suite in scenarios_data.get("suites", []):
        if _slugify(suite.get("name", "")) == slug:
            suite_name = suite.get("name", "")
            for sc in suite.get("scenarios", []):
                if sc.get("id") == scenario_id:
                    sc_name = sc.get("name", "")
                    for step in sc.get("steps", []):
                        if step.get("action") == "screenshot":
                            screenshot_filenames.append(f"{scenario_id}-{step['label']}.png")
                    break
            break

    # Check Playwright results to see if this scenario failed (add FAILURE screenshot)
    pw_data = _fetch_latest_results()
    pw_results, run_slug, _ = _load_playwright_results(pw_data)

    key = (suite_name, sc_name)
    result = pw_results.get(key)
    if result and result["status"] == "failed":
        screenshot_filenames.append(f"{scenario_id}-FAILURE.png")

    if not run_slug:
        # Try to get run_slug from Playwright metadata
        if pw_data:
            config = pw_data.get("config", {})
            metadata = config.get("metadata", {})
            run_slug = metadata.get("runSlug", "")

    if not screenshot_filenames:
        return {"scenario_id": scenario_id, "screenshots": []}

    # Generate presigned URLs
    s3 = get_s3_client()
    screenshots = []
    for filename in screenshot_filenames:
        s3_key = f"{S3_SCREENSHOTS_PREFIX}/{run_slug}/{filename}" if run_slug else f"{S3_SCREENSHOTS_PREFIX}/{filename}"
        label = filename.replace(f"{scenario_id}-", "").replace(".png", "").replace("-", " ")
        try:
            url = s3.get_presigned_url(s3_key, expiration=3600)
            screenshots.append({
                "label": label,
                "url": url,
                "filename": filename,
            })
        except ClientError:
            logger.warning(f"Failed to generate presigned URL for {s3_key}")

    return {"scenario_id": scenario_id, "screenshots": screenshots}
