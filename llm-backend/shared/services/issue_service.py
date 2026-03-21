"""Service for issue reporting — LLM interpretation + CRUD."""
import json
import logging
from uuid import uuid4
from typing import Optional, List

from sqlalchemy.orm import Session as DBSession

from config import get_settings
from shared.models.entities import Issue, User
from shared.repositories.issue_repository import IssueRepository
from shared.services.llm_config_service import LLMConfigService
from shared.services.llm_service import LLMService
from shared.utils.s3_client import get_s3_client

logger = logging.getLogger(__name__)

# Compact app context for the LLM to understand what the user might be reporting about.
_APP_CONTEXT = """
LearnLikeMagic is an AI tutoring app for K-12 students. Key features the user may reference:

STUDENT FLOW:
- Login/Signup: phone, email, or Google sign-in → onboarding (name, age, grade, board)
- Subject selection → Chapter selection → Topic selection → Mode selection
- Learning modes: "Teach Me" (step-by-step lesson), "Clarify Doubts" (Q&A), "Exam" (quiz)
- Voice input: students can speak answers via mic button (uses speech-to-text)
- Voice output: tutor can read responses aloud (text-to-speech toggle, virtual teacher mode)
- Session pause & resume: can pause a Teach Me session and continue later
- Exam review: after exam, see question-by-question breakdown with answers
- Report card: shows coverage % and exam scores per subject/chapter/topic
- Session history: past sessions with mastery scores
- Profile page: edit name, grade, board, school, language preferences
- Enrichment profile: parents describe child's interests/learning style for personalisation

CHAT SESSION UI:
- Messages appear as conversation bubbles (tutor and student)
- Interactive question formats: fill-in-the-blank, multiple-choice, matching exercises
- Explanation cards: step-by-step visual cards the tutor presents during lessons
- Mic button for voice input, speaker button for voice output
- Feedback button to give mid-session feedback

ADMIN FEATURES:
- Book ingestion: upload textbook pages, extract TOC, process chapters, sync topics
- Evaluation: test tutor quality with simulated students
- LLM config: choose AI model per component
- Feature flags: toggle features on/off
- Test scenarios: view E2E test results
- Docs viewer: browse project docs
""".strip()

_INTERPRET_PROMPT = """You are an issue interpreter for the LearnLikeMagic app. A user/tester is reporting a problem or suggestion.

APP CONTEXT:
{app_context}

USER INPUT:
{user_input}

{screenshot_note}

{refinement_note}

Interpret the user's issue in the context of this app. Produce a JSON response:
{{
  "title": "Short issue title (under 80 chars)",
  "description": "Clear, structured description of the issue. Include: what the user experienced, where in the app it happened (if identifiable), and what they expected. Write in third person. Be concise but complete."
}}

Rules:
- Map vague descriptions to specific app features when possible
- If the user mentions screens/pages, identify which app page they mean
- Keep the description factual and actionable
- Do NOT suggest solutions — just describe the issue clearly
"""


class IssueService:
    def __init__(self, db: DBSession):
        self.db = db
        self.repo = IssueRepository(db)

    def interpret(
        self,
        user_input: str,
        has_screenshots: bool = False,
        previous_interpretation: Optional[str] = None,
        refinement_input: Optional[str] = None,
    ) -> dict:
        """Use LLM to interpret the user's issue report. Returns {title, description}."""
        settings = get_settings()
        config_service = LLMConfigService(self.db)
        config = config_service.get_config("issue_interpreter")
        fast_config = config_service.get_config("fast_model")

        llm = LLMService(
            api_key=settings.openai_api_key,
            provider=config["provider"],
            model_id=config["model_id"],
            fast_model_id=fast_config["model_id"],
            gemini_api_key=settings.gemini_api_key if settings.gemini_api_key else None,
            anthropic_api_key=settings.anthropic_api_key if settings.anthropic_api_key else None,
        )

        screenshot_note = (
            "The user also attached screenshots showing the issue."
            if has_screenshots else ""
        )

        refinement_note = ""
        if previous_interpretation and refinement_input:
            refinement_note = (
                f"PREVIOUS INTERPRETATION (user was NOT satisfied):\n{previous_interpretation}\n\n"
                f"USER'S REFINEMENT:\n{refinement_input}\n\n"
                "Revise the interpretation based on the user's feedback."
            )

        prompt = _INTERPRET_PROMPT.format(
            app_context=_APP_CONTEXT,
            user_input=user_input,
            screenshot_note=screenshot_note,
            refinement_note=refinement_note,
        )

        result = llm.call(prompt, json_mode=True)
        parsed = json.loads(result["output_text"])
        return {"title": parsed["title"], "description": parsed["description"]}

    def upload_screenshot(self, issue_id: str, file_bytes: bytes, filename: str, content_type: str) -> str:
        """Upload a screenshot to S3. Returns the S3 key."""
        s3 = get_s3_client()
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "png"
        s3_key = f"issues/{issue_id}/{filename}"
        s3.upload_bytes(file_bytes, s3_key, content_type=content_type)
        return s3_key

    def create_issue(
        self,
        title: str,
        description: str,
        original_input: str,
        screenshot_s3_keys: Optional[List[str]],
        user_id: Optional[str] = None,
    ) -> Issue:
        """Create a confirmed issue in the database."""
        # Look up reporter name
        reporter_name = None
        if user_id:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user:
                reporter_name = user.preferred_name or user.name

        issue = Issue(
            id=str(uuid4()),
            user_id=user_id,
            reporter_name=reporter_name,
            title=title,
            description=description,
            original_input=original_input,
            screenshot_s3_keys=screenshot_s3_keys or [],
            status="open",
        )
        return self.repo.create(issue)

    def list_issues(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> dict:
        """List issues with optional status filter."""
        issues = self.repo.get_all(status=status, limit=limit, offset=offset)
        total = self.repo.count(status=status)
        return {"issues": issues, "total": total}

    def get_issue(self, issue_id: str) -> Optional[Issue]:
        return self.repo.get_by_id(issue_id)

    def update_status(self, issue_id: str, status: str) -> Optional[Issue]:
        if status not in ("open", "in_progress", "closed"):
            raise ValueError(f"Invalid status: {status}")
        return self.repo.update_status(issue_id, status)

    def get_screenshot_url(self, s3_key: str) -> str:
        """Get a presigned URL for a screenshot."""
        s3 = get_s3_client()
        return s3.get_presigned_url(s3_key)
