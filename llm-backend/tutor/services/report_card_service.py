"""Report card aggregation service — builds student progress report from session data.

Returns only deterministic metrics:
- Coverage completion % (teach_me sessions only)
- Exam score (latest X/Y from exam sessions; legacy — dropped in Step 13)
- Practice score (latest fractional score + attempt count from practice_attempts)
"""

import json
import logging
from collections import defaultdict

from sqlalchemy.orm import Session as DBSession

from shared.models.entities import (
    PracticeAttempt,
    Session as SessionModel,
    TeachingGuideline,
)

logger = logging.getLogger("tutor.report_card_service")


class ReportCardService:
    """Aggregates session data into a deterministic student report card."""

    def __init__(self, db: DBSession):
        self.db = db

    # ── Public API ──────────────────────────────────────────────

    def get_report_card(self, user_id: str) -> dict:
        """
        Build the complete report card for a student.

        Returns only deterministic data:
        - total_sessions, total_chapters_studied
        - Per topic: coverage % (teach_me only) + latest exam score
        - No aggregate scores, no strengths/weaknesses, no trends
        """
        sessions = self._load_user_sessions(user_id)
        practice_attempts = self._load_user_practice_attempts(user_id)
        if not sessions and not practice_attempts:
            return self._empty_report_card()

        guideline_lookup = self._build_guideline_lookup(sessions, practice_attempts)
        grouped = self._group_sessions(sessions, guideline_lookup)
        self._merge_practice_attempts_into_grouped(grouped, guideline_lookup, practice_attempts)
        subjects_data = self._build_report(grouped)

        total_sessions = len(sessions)
        total_chapters = sum(len(s["chapters"]) for s in subjects_data)

        return {
            "total_sessions": total_sessions,
            "total_chapters_studied": total_chapters,
            "subjects": subjects_data,
        }

    def get_topic_progress(self, user_id: str) -> dict:
        """
        Returns {guideline_id: {coverage, session_count, status, last_practiced}}
        for the curriculum picker coverage indicators.

        Coverage numerator = concepts covered across teach_me + practice sessions.
        Coverage denominator = canonical concept list from most recent teach_me
        session's plan (never from a practice plan, to prevent denominator shrinkage).
        Practice sessions contribute only if they have >=3 questions answered (FR-30).
        """
        sessions = self._load_user_sessions(user_id)
        progress: dict[str, dict] = {}

        for session_row in sessions:
            try:
                state = json.loads(session_row.state_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(state, dict):
                continue
            topic_data = state.get("topic")
            if not isinstance(topic_data, dict):
                continue
            topic_id = topic_data.get("topic_id")
            if not topic_id:
                continue

            mode = state.get("mode", "teach_me")
            if mode not in ("teach_me", "practice"):
                continue

            # Practice 3-question gate
            if mode == "practice" and state.get("practice_questions_answered", 0) < 3:
                continue

            session_date = session_row.created_at.isoformat() if session_row.created_at else None

            existing = progress.get(topic_id, {
                "covered_set": set(),
                "plan_concepts": set(),
                "session_count": 0,
                "last_practiced": None,
            })

            # Accumulate concepts covered (from both teach_me and practice)
            concepts_covered = state.get("concepts_covered_set", [])
            if isinstance(concepts_covered, list):
                existing["covered_set"].update(concepts_covered)

            # Canonical denominator comes from teach_me sessions ONLY.
            # Practice plans are struggle-weighted subsets — using them would
            # shrink the denominator and falsely inflate combined coverage.
            if mode == "teach_me":
                mastery_estimates = state.get("mastery_estimates", {})
                if isinstance(mastery_estimates, dict) and mastery_estimates:
                    existing["plan_concepts"] = set(mastery_estimates.keys())

            # Track last_practiced from practice sessions (3+ questions gate already applied)
            if mode == "practice" and session_date:
                last_p = existing.get("last_practiced")
                if not last_p or session_date > last_p:
                    existing["last_practiced"] = session_date

            existing["session_count"] += 1
            progress[topic_id] = existing

        # Convert to output format
        result = {}
        for topic_id, data in progress.items():
            plan = data["plan_concepts"]
            covered = data["covered_set"]
            coverage = 0.0
            if plan:
                coverage = round(len(covered & plan) / len(plan) * 100, 1)

            result[topic_id] = {
                "coverage": coverage,
                "session_count": data["session_count"],
                "status": "studied" if data["session_count"] > 0 else "not_started",
                "last_practiced": data.get("last_practiced"),
            }

        return {"user_progress": result}

    # ── Private helpers ─────────────────────────────────────────

    def _load_user_sessions(self, user_id: str) -> list:
        """Load all sessions for the user, ordered by created_at ascending."""
        return (
            self.db.query(
                SessionModel.id,
                SessionModel.state_json,
                SessionModel.subject,
                SessionModel.mastery,
                SessionModel.created_at,
            )
            .filter(SessionModel.user_id == user_id)
            .order_by(SessionModel.created_at.asc(), SessionModel.id.asc())
            .all()
        )

    def _load_user_practice_attempts(self, user_id: str) -> list:
        """Load graded practice attempts for the user, ordered by guideline_id + graded_at DESC.

        Filters to status='graded' with non-null graded_at + total_score so the
        grouping in `_merge_practice_attempts_into_grouped` can take attempts[0]
        as the latest graded attempt per guideline.
        """
        return (
            self.db.query(
                PracticeAttempt.guideline_id,
                PracticeAttempt.total_score,
                PracticeAttempt.total_possible,
                PracticeAttempt.graded_at,
            )
            .filter(
                PracticeAttempt.user_id == user_id,
                PracticeAttempt.status == "graded",
                PracticeAttempt.graded_at.isnot(None),
                PracticeAttempt.total_score.isnot(None),
            )
            .order_by(
                PracticeAttempt.guideline_id.asc(),
                PracticeAttempt.graded_at.desc(),
            )
            .all()
        )

    def _build_guideline_lookup(self, sessions, practice_attempts=None) -> dict:
        """
        Build guideline_id → hierarchy info by collecting all topic_ids from sessions
        and practice attempts, then batch-querying teaching_guidelines.
        """
        guideline_ids = set()
        for s in sessions:
            try:
                state = json.loads(s.state_json)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(state, dict):
                continue
            topic = state.get("topic")
            if not isinstance(topic, dict):
                continue
            topic_id = topic.get("topic_id")
            if topic_id:
                guideline_ids.add(topic_id)

        for a in practice_attempts or []:
            if a.guideline_id:
                guideline_ids.add(a.guideline_id)

        if not guideline_ids:
            return {}

        guidelines = (
            self.db.query(
                TeachingGuideline.id,
                TeachingGuideline.subject,
                TeachingGuideline.chapter,
                TeachingGuideline.topic,
                TeachingGuideline.chapter_title,
                TeachingGuideline.topic_title,
                TeachingGuideline.chapter_key,
                TeachingGuideline.topic_key,
            )
            .filter(TeachingGuideline.id.in_(guideline_ids))
            .all()
        )

        return {
            g.id: {
                "subject": g.subject,
                "chapter": g.chapter_title or g.chapter,
                "topic": g.topic_title or g.topic,
                "chapter_key": g.chapter_key or (g.chapter_title or g.chapter).lower().replace(" ", "-"),
                "topic_key": g.topic_key or (g.topic_title or g.topic).lower().replace(" ", "-"),
            }
            for g in guidelines
        }

    def _group_sessions(self, sessions, guideline_lookup) -> dict:
        """
        Group sessions into subject → chapter → topic hierarchy.
        Only accumulates coverage from teach_me sessions.
        Tracks latest exam score from exam sessions.
        """
        grouped = defaultdict(lambda: defaultdict(lambda: {"chapter_name": "", "topics": {}}))

        for session_row in sessions:
            try:
                state = json.loads(session_row.state_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Skipping session %s: malformed state_json", session_row.id)
                continue

            if not isinstance(state, dict):
                logger.warning("Skipping session %s: state_json is not a dict", session_row.id)
                continue

            topic_data = state.get("topic")
            if not isinstance(topic_data, dict) or not topic_data:
                continue

            subject = topic_data.get("subject", session_row.subject or "Unknown")
            topic_id = topic_data.get("topic_id")
            topic_name_raw = topic_data.get("topic_name", "")
            mode = state.get("mode", "teach_me")

            # Resolve hierarchy
            if topic_id and topic_id in guideline_lookup:
                gl = guideline_lookup[topic_id]
                chapter_name = gl["chapter"]
                topic_name = gl["topic"]
                chapter_key = gl["chapter_key"]
                topic_key = gl["topic_key"]
            elif " - " in topic_name_raw:
                parts = topic_name_raw.split(" - ", 1)
                chapter_name = parts[0].strip()
                topic_name = parts[1].strip()
                chapter_key = chapter_name.lower().replace(" ", "-")
                topic_key = topic_name.lower().replace(" ", "-")
            else:
                chapter_name = topic_name_raw or "Unknown"
                topic_name = topic_name_raw or "Unknown"
                chapter_key = chapter_name.lower().replace(" ", "-")
                topic_key = topic_name.lower().replace(" ", "-")

            session_date = session_row.created_at.isoformat() if session_row.created_at else None

            # Get or initialize topic accumulator
            existing = grouped[subject][chapter_key]["topics"].get(topic_key, {})
            existing_covered = set(existing.get("concepts_covered", []))
            existing_plan = set(existing.get("plan_concepts", []))
            existing_last_studied = existing.get("last_studied")
            existing_last_practiced = existing.get("last_practiced")
            existing_exam_score = existing.get("latest_exam_score")
            existing_exam_total = existing.get("latest_exam_total")

            # Coverage contribution: teach_me always, practice gated on 3+ questions (FR-30)
            contributes_to_coverage = False
            if mode == "teach_me":
                contributes_to_coverage = True
            elif mode == "practice":
                if state.get("practice_questions_answered", 0) >= 3:
                    contributes_to_coverage = True

            if contributes_to_coverage:
                concepts_covered = state.get("concepts_covered_set", [])
                if isinstance(concepts_covered, list):
                    existing_covered.update(concepts_covered)

                existing_last_studied = session_date

                # Canonical denominator comes from teach_me sessions ONLY.
                # Practice plans are struggle-weighted subsets — using them would
                # shrink the denominator and falsely inflate combined coverage.
                if mode == "teach_me":
                    mastery_estimates = state.get("mastery_estimates", {})
                    if isinstance(mastery_estimates, dict) and mastery_estimates:
                        existing_plan = set(mastery_estimates.keys())

            # Track last_practiced from practice sessions (with 3-question gate)
            if mode == "practice" and state.get("practice_questions_answered", 0) >= 3:
                if not existing_last_practiced or (session_date and session_date > existing_last_practiced):
                    existing_last_practiced = session_date

            # Track latest exam score (with type guards for legacy data)
            if mode == "exam" and state.get("exam_finished", False):
                raw_score = state.get("exam_total_correct", 0)
                exam_score = int(raw_score) if isinstance(raw_score, (int, float)) else 0
                raw_questions = state.get("exam_questions", [])
                exam_total = len(raw_questions) if isinstance(raw_questions, list) else 0
                if exam_total > 0:
                    existing_exam_score = exam_score
                    existing_exam_total = exam_total
                    existing_last_studied = session_date

            grouped[subject][chapter_key]["chapter_name"] = chapter_name
            grouped[subject][chapter_key]["topics"][topic_key] = {
                "topic_name": topic_name,
                "guideline_id": topic_id,
                "concepts_covered": list(existing_covered),
                "plan_concepts": list(existing_plan),
                "last_studied": existing_last_studied,
                "last_practiced": existing_last_practiced,
                "latest_exam_score": existing_exam_score,
                "latest_exam_total": existing_exam_total,
            }

        return grouped

    def _merge_practice_attempts_into_grouped(
        self,
        grouped,
        guideline_lookup: dict,
        practice_attempts: list,
    ) -> None:
        """Merge graded practice attempts (v2 practice_attempts table) into the
        grouped structure. Latest-graded score + attempt count per guideline.

        Additive — does NOT touch legacy exam fields (dropped in Step 13).
        Creates a topic row if a guideline has practice data but no
        teach_me/clarify/exam sessions yet. Attempts are expected to already be
        sorted guideline_id ASC, graded_at DESC.
        """
        by_guideline: dict[str, list] = defaultdict(list)
        for attempt in practice_attempts:
            if attempt.guideline_id:
                by_guideline[attempt.guideline_id].append(attempt)

        for guideline_id, attempts in by_guideline.items():
            if not attempts or guideline_id not in guideline_lookup:
                continue
            gl = guideline_lookup[guideline_id]
            subject = gl.get("subject") or "Unknown"
            chapter_name = gl["chapter"]
            topic_name = gl["topic"]
            chapter_key = gl["chapter_key"]
            topic_key = gl["topic_key"]

            latest = attempts[0]
            chapter_entry = grouped[subject][chapter_key]
            if not chapter_entry.get("chapter_name"):
                chapter_entry["chapter_name"] = chapter_name
            topic_entry = chapter_entry["topics"].get(topic_key, {
                "topic_name": topic_name,
                "guideline_id": guideline_id,
                "concepts_covered": [],
                "plan_concepts": [],
                "last_studied": None,
                "last_practiced": None,
                "latest_exam_score": None,
                "latest_exam_total": None,
            })
            topic_entry["latest_practice_score"] = latest.total_score
            topic_entry["latest_practice_total"] = latest.total_possible
            topic_entry["practice_attempt_count"] = len(attempts)
            chapter_entry["topics"][topic_key] = topic_entry

    def _build_report(self, grouped) -> list:
        """Build flat report from grouped data. No aggregate scores."""
        subjects_data = []
        for subject, chapters in sorted(grouped.items()):
            chapters_data = []
            for chapter_key, chapter_info in sorted(chapters.items()):
                topics_data = []
                for topic_key, topic_info in sorted(chapter_info["topics"].items()):
                    plan_concepts = set(topic_info.get("plan_concepts", []))
                    covered = set(topic_info.get("concepts_covered", []))
                    coverage = 0.0
                    if plan_concepts:
                        coverage = round(len(covered & plan_concepts) / len(plan_concepts) * 100, 1)

                    topics_data.append({
                        "topic": topic_info["topic_name"],
                        "topic_key": topic_key,
                        "guideline_id": topic_info.get("guideline_id"),
                        "coverage": coverage,
                        "latest_exam_score": topic_info.get("latest_exam_score"),
                        "latest_exam_total": topic_info.get("latest_exam_total"),
                        "latest_practice_score": topic_info.get("latest_practice_score"),
                        "latest_practice_total": topic_info.get("latest_practice_total"),
                        "practice_attempt_count": topic_info.get("practice_attempt_count"),
                        "last_studied": topic_info.get("last_studied"),
                        "last_practiced": topic_info.get("last_practiced"),
                    })

                chapters_data.append({
                    "chapter": chapter_info["chapter_name"],
                    "chapter_key": chapter_key,
                    "topics": topics_data,
                })

            subjects_data.append({
                "subject": subject,
                "chapters": chapters_data,
            })

        return subjects_data

    def _empty_report_card(self) -> dict:
        """Return empty report card for users with no sessions."""
        return {
            "total_sessions": 0,
            "total_chapters_studied": 0,
            "subjects": [],
        }
