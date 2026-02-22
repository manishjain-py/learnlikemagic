"""
Test Scenarios API - Serves test case docs, scenario data, and test results.

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


def _resolve_docs_dir() -> Path:
    """Find the docs directory - works both locally and in Docker."""
    docker_path = Path(__file__).parent.parent / "docs"
    if docker_path.exists():
        return docker_path
    local_path = Path(__file__).parent.parent.parent / "docs"
    if local_path.exists():
        return local_path
    raise FileNotFoundError("docs directory not found")


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


def _fetch_local_results() -> Optional[dict]:
    """Read scenario-results.json from the local reports directory (for local dev)."""
    # Docker: /app/reports/e2e-runner/scenario-results.json
    docker_path = Path(__file__).parent.parent / "reports" / "e2e-runner" / "scenario-results.json"
    if docker_path.is_file():
        try:
            return json.loads(docker_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to read local results at {docker_path}: {e}")
    # Local dev: repo_root/reports/e2e-runner/scenario-results.json
    local_path = Path(__file__).parent.parent.parent / "reports" / "e2e-runner" / "scenario-results.json"
    if local_path.is_file():
        try:
            return json.loads(local_path.read_text())
        except Exception as e:
            logger.warning(f"Failed to read local results at {local_path}: {e}")
    return None


def _fetch_latest_results() -> Optional[dict]:
    """Fetch latest results: try S3 first, fall back to local file."""
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
    return _fetch_local_results()


def _slugify(name: str) -> str:
    """Convert suite name to slug: 'Admin — Books Dashboard' → 'admin-books-dashboard'."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _parse_test_case_md(content: str) -> list[dict]:
    """Parse a test-cases markdown file into structured scenario data."""
    scenarios = []
    current: Optional[dict] = None
    in_steps = False

    for line in content.split("\n"):
        line_stripped = line.strip()

        # Match scenario header: ## Test Scenario N: Name
        m = re.match(r"^## Test Scenario \d+:\s*(.+)$", line_stripped)
        if m:
            if current:
                scenarios.append(current)
            current = {"name": m.group(1), "id": "", "steps": [], "expected_result": ""}
            in_steps = False
            continue

        if current is None:
            continue

        # Match ID line
        if line_stripped.startswith("**ID:**"):
            current["id"] = line_stripped.replace("**ID:**", "").strip()
            continue

        # Match steps header
        if line_stripped == "**Steps:**":
            in_steps = True
            continue

        # Match step line: a) ...
        if in_steps and re.match(r"^[a-z]\)\s", line_stripped):
            step_text = re.sub(r"^[a-z]\)\s*", "", line_stripped)
            current["steps"].append(step_text)
            continue

        # Match expected result
        if line_stripped.startswith("**Expected Result:**"):
            current["expected_result"] = line_stripped.replace("**Expected Result:**", "").strip()
            in_steps = False
            continue

    if current:
        scenarios.append(current)

    return scenarios


@router.get("")
def list_test_scenarios():
    """List all test case functionalities with latest results."""
    try:
        docs_dir = _resolve_docs_dir()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Documentation directory not found")

    test_cases_dir = docs_dir / "test-cases"
    if not test_cases_dir.is_dir():
        return {"functionalities": []}

    # Fetch latest results from S3
    results = _fetch_latest_results()
    results_by_suite: dict[str, dict] = {}
    results_timestamp = None
    if results:
        results_timestamp = results.get("timestamp")
        for suite in results.get("suites", []):
            slug = _slugify(suite.get("name", ""))
            results_by_suite[slug] = suite

    functionalities = []
    for md_file in sorted(test_cases_dir.iterdir()):
        if not md_file.suffix == ".md":
            continue

        slug = md_file.stem  # e.g. "tutor-flow"
        content = md_file.read_text(encoding="utf-8")

        # Extract title from first heading
        name = slug.replace("-", " ").title()
        first_line = content.split("\n")[0] if content else ""
        m = re.match(r"^#\s+(.+?)(?:\s*—\s*Test Cases)?$", first_line)
        if m:
            name = m.group(1)

        # Count scenarios
        scenario_count = len(re.findall(r"^## Test Scenario \d+:", content, re.MULTILINE))

        # Merge with S3 results
        suite_result = results_by_suite.get(slug, {})
        scenarios_results = suite_result.get("scenarios", [])
        passed = sum(1 for s in scenarios_results if s.get("status") == "passed")
        failed = sum(1 for s in scenarios_results if s.get("status") == "failed")

        if suite_result:
            status = suite_result.get("status", "not_run")
        else:
            status = "not_run"

        functionalities.append({
            "slug": slug,
            "name": name,
            "filename": md_file.name,
            "scenario_count": scenario_count,
            "last_tested": results_timestamp if suite_result else None,
            "status": status,
            "passed": passed,
            "failed": failed,
        })

    return {"functionalities": functionalities}


@router.get("/{slug}")
def get_test_scenario_detail(slug: str):
    """Return structured scenario data + test results for a specific functionality."""
    # Validate slug
    if ".." in slug or "/" in slug:
        raise HTTPException(status_code=404, detail="Invalid slug")

    try:
        docs_dir = _resolve_docs_dir()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Documentation directory not found")

    md_path = docs_dir / "test-cases" / f"{slug}.md"
    if not md_path.is_file():
        raise HTTPException(status_code=404, detail="Test case document not found")

    content = md_path.read_text(encoding="utf-8")
    parsed_scenarios = _parse_test_case_md(content)

    # Extract suite name from heading
    name = slug.replace("-", " ").title()
    first_line = content.split("\n")[0] if content else ""
    m = re.match(r"^#\s+(.+?)(?:\s*—\s*Test Cases)?$", first_line)
    if m:
        name = m.group(1)

    # Fetch results from S3
    results = _fetch_latest_results()
    results_by_id: dict[str, dict] = {}
    suite_status = "not_run"
    last_tested = None

    if results:
        last_tested = results.get("timestamp")
        for suite in results.get("suites", []):
            if _slugify(suite.get("name", "")) == slug:
                suite_status = suite.get("status", "not_run")
                for sc in suite.get("scenarios", []):
                    results_by_id[sc.get("id", "")] = sc
                break

    # Also try to get screenshots from scenarios.json
    screenshots_by_id: dict[str, list[str]] = {}
    try:
        scenarios_path = _resolve_scenarios_json()
        scenarios_data = json.loads(scenarios_path.read_text())
        for suite in scenarios_data.get("suites", []):
            if _slugify(suite.get("name", "")) == slug:
                for sc in suite.get("scenarios", []):
                    sc_id = sc.get("id", "")
                    sc_screenshots = []
                    for step in sc.get("steps", []):
                        if step.get("action") == "screenshot":
                            sc_screenshots.append(f"{sc_id}-{step['label']}.png")
                    screenshots_by_id[sc_id] = sc_screenshots
                break
    except FileNotFoundError:
        pass

    # Merge parsed docs with results
    scenarios = []
    for sc in parsed_scenarios:
        sc_id = sc["id"]
        result = results_by_id.get(sc_id, {})

        # Screenshots: prefer results from S3, fallback to scenarios.json derivation
        screenshots = result.get("screenshots", screenshots_by_id.get(sc_id, []))

        scenarios.append({
            "id": sc_id,
            "name": sc["name"],
            "status": result.get("status", "not_run"),
            "steps": sc["steps"],
            "expected_result": sc["expected_result"],
            "screenshots": screenshots,
        })

    if not results_by_id:
        suite_status = "not_run"

    return {
        "slug": slug,
        "name": name,
        "last_tested": last_tested if results_by_id else None,
        "status": suite_status,
        "scenarios": scenarios,
    }


@router.get("/{slug}/screenshots/{scenario_id}")
def get_scenario_screenshots(slug: str, scenario_id: str):
    """Return presigned S3 URLs for a scenario's screenshots."""
    if ".." in slug or "/" in slug or ".." in scenario_id or "/" in scenario_id:
        raise HTTPException(status_code=404, detail="Invalid parameters")

    # Get the screenshot filenames from results
    results = _fetch_latest_results()
    screenshot_filenames: list[str] = []

    if results:
        run_slug = results.get("runSlug", "")
        for suite in results.get("suites", []):
            if _slugify(suite.get("name", "")) == slug:
                for sc in suite.get("scenarios", []):
                    if sc.get("id") == scenario_id:
                        screenshot_filenames = sc.get("screenshots", [])
                        break
                break

    if not screenshot_filenames:
        return {"scenario_id": scenario_id, "screenshots": []}

    # Generate presigned URLs
    s3 = get_s3_client()
    run_slug = results.get("runSlug", "") if results else ""
    screenshots = []
    for filename in screenshot_filenames:
        s3_key = f"{S3_SCREENSHOTS_PREFIX}/{run_slug}/{filename}"
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
