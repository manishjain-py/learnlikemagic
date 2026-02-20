"""
Documentation API - Serves project docs as rendered content in the admin UI.

Endpoints:
  GET /api/docs           - List all docs grouped by category
  GET /api/docs/{cat}/{f} - Return raw markdown content for a specific doc
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/docs", tags=["docs"])

ALLOWED_CATEGORIES = {"functional", "technical", "root"}


def _resolve_docs_dir() -> Path:
    """Find the docs directory - works both locally and in Docker."""
    # In Docker: /app/docs/ (copied during build)
    docker_path = Path(__file__).parent.parent / "docs"
    if docker_path.exists():
        return docker_path
    # Local dev: repo_root/docs/
    local_path = Path(__file__).parent.parent.parent / "docs"
    if local_path.exists():
        return local_path
    raise FileNotFoundError("docs directory not found")


def _humanize(filename: str) -> str:
    """Convert filename like 'app-overview.md' to 'App Overview'."""
    return filename.replace(".md", "").replace("-", " ").replace("_", " ").title()


@router.get("")
def list_docs():
    """List all documentation files grouped by category."""
    try:
        docs_dir = _resolve_docs_dir()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Documentation directory not found")

    result: dict[str, list[dict]] = {}

    # Scan functional/ and technical/ subdirectories
    for category in ("functional", "technical"):
        cat_dir = docs_dir / category
        if not cat_dir.is_dir():
            continue
        files = sorted(f.name for f in cat_dir.iterdir() if f.suffix == ".md")
        result[category] = [
            {"filename": f, "title": _humanize(f)} for f in files
        ]

    # Root-level markdown files
    root_files = sorted(f.name for f in docs_dir.iterdir() if f.is_file() and f.suffix == ".md")
    if root_files:
        result["root"] = [
            {"filename": f, "title": _humanize(f)} for f in root_files
        ]

    return result


@router.get("/{category}/{filename}")
def get_doc_content(category: str, filename: str):
    """Return raw markdown content for a specific doc."""
    # Validate category
    if category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=404, detail="Invalid category")

    # Validate filename: must end with .md, no path traversal
    if not filename.endswith(".md") or ".." in filename or "/" in filename:
        raise HTTPException(status_code=404, detail="Invalid filename")

    try:
        docs_dir = _resolve_docs_dir()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Documentation directory not found")

    if category == "root":
        file_path = docs_dir / filename
    else:
        file_path = docs_dir / category / filename

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    content = file_path.read_text(encoding="utf-8")
    return {"filename": filename, "category": category, "content": content}
