"""Scorecard aggregation service — builds student progress report from session data.

Returns only deterministic metrics:
- Coverage completion % (teach_me sessions only)
- Exam score (latest X/Y from exam sessions)
"""

import json
import logging
from collections import defaultdict

from sqlalchemy.orm import Session as DBSession

from shared.models.entities import Session as SessionModel, TeachingGuideline

logger = logging.getLogger("tutor.scorecard_service")


class ScorecardService:
    """Aggregates session data into a deterministic student report card."""

    def __init__(self, db: DBSession):
        self.db = db

    # ── Public API ──────────────────────────────────────────────

    def get_scorecard(self, user_id: str) -> dict:
        """
        Build the complete report card for a student.

        Returns only deterministic data:
        - total_sessions, total_topics_studied
        - Per subtopic: coverage % (teach_me only) + latest exam score
        - No aggregate scores, no strengths/weaknesses, no trends
        """
        sessions = self._load_user_sessions(user_id)
        if not sessions:
            return self._empty_scorecard()

        guideline_lookup = self._build_guideline_lookup(sessions)
        grouped = self._group_sessions(sessions, guideline_lookup)
        subjects_data = self._build_report(grouped)

        total_sessions = len(sessions)
        total_topics = sum(len(s["topics"]) for s in subjects_data)

        return {
            "total_sessions": total_sessions,
            "total_topics_studied": total_topics,
            "subjects": subjects_data,
        }

    def get_subtopic_progress(self, user_id: str) -> dict:
        """
        Returns {guideline_id: {coverage, session_count, status}} for the
        curriculum picker coverage indicators.

        Only counts teach_me sessions for coverage.
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
            if mode != "teach_me":
                continue

            existing = progress.get(topic_id, {
                "covered_set": set(),
                "plan_concepts": set(),
                "session_count": 0,
            })

            # Accumulate concepts covered
            concepts_covered = state.get("concepts_covered_set", [])
            if isinstance(concepts_covered, list):
                existing["covered_set"].update(concepts_covered)

            # Plan concepts from latest session's mastery_estimates keys
            mastery_estimates = state.get("mastery_estimates", {})
            if isinstance(mastery_estimates, dict) and mastery_estimates:
                existing["plan_concepts"] = set(mastery_estimates.keys())

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

    def _build_guideline_lookup(self, sessions) -> dict:
        """
        Build guideline_id → hierarchy info by collecting all topic_ids from sessions
        and batch-querying teaching_guidelines.
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

        if not guideline_ids:
            return {}

        guidelines = (
            self.db.query(
                TeachingGuideline.id,
                TeachingGuideline.topic,
                TeachingGuideline.subtopic,
                TeachingGuideline.topic_title,
                TeachingGuideline.subtopic_title,
                TeachingGuideline.topic_key,
                TeachingGuideline.subtopic_key,
            )
            .filter(TeachingGuideline.id.in_(guideline_ids))
            .all()
        )

        return {
            g.id: {
                "topic": g.topic_title or g.topic,
                "subtopic": g.subtopic_title or g.subtopic,
                "topic_key": g.topic_key or (g.topic_title or g.topic).lower().replace(" ", "-"),
                "subtopic_key": g.subtopic_key or (g.subtopic_title or g.subtopic).lower().replace(" ", "-"),
            }
            for g in guidelines
        }

    def _group_sessions(self, sessions, guideline_lookup) -> dict:
        """
        Group sessions into subject → topic → subtopic hierarchy.
        Only accumulates coverage from teach_me sessions.
        Tracks latest exam score from exam sessions.
        """
        grouped = defaultdict(lambda: defaultdict(lambda: {"topic_name": "", "subtopics": {}}))

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
                topic_name = gl["topic"]
                subtopic_name = gl["subtopic"]
                topic_key = gl["topic_key"]
                subtopic_key = gl["subtopic_key"]
            elif " - " in topic_name_raw:
                parts = topic_name_raw.split(" - ", 1)
                topic_name = parts[0].strip()
                subtopic_name = parts[1].strip()
                topic_key = topic_name.lower().replace(" ", "-")
                subtopic_key = subtopic_name.lower().replace(" ", "-")
            else:
                topic_name = topic_name_raw or "Unknown"
                subtopic_name = topic_name_raw or "Unknown"
                topic_key = topic_name.lower().replace(" ", "-")
                subtopic_key = subtopic_name.lower().replace(" ", "-")

            session_date = session_row.created_at.isoformat() if session_row.created_at else None

            # Get or initialize subtopic accumulator
            existing = grouped[subject][topic_key]["subtopics"].get(subtopic_key, {})
            existing_covered = set(existing.get("concepts_covered", []))
            existing_plan = set(existing.get("plan_concepts", []))
            existing_last_studied = existing.get("last_studied")
            existing_exam_score = existing.get("latest_exam_score")
            existing_exam_total = existing.get("latest_exam_total")

            # Only accumulate coverage from teach_me sessions
            if mode == "teach_me":
                concepts_covered = state.get("concepts_covered_set", [])
                if isinstance(concepts_covered, list):
                    existing_covered.update(concepts_covered)

                # Use latest session's plan concepts (not union) to avoid denominator drift
                mastery_estimates = state.get("mastery_estimates", {})
                if isinstance(mastery_estimates, dict) and mastery_estimates:
                    existing_plan = set(mastery_estimates.keys())

                existing_last_studied = session_date

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

            grouped[subject][topic_key]["topic_name"] = topic_name
            grouped[subject][topic_key]["subtopics"][subtopic_key] = {
                "subtopic_name": subtopic_name,
                "guideline_id": topic_id,
                "concepts_covered": list(existing_covered),
                "plan_concepts": list(existing_plan),
                "last_studied": existing_last_studied,
                "latest_exam_score": existing_exam_score,
                "latest_exam_total": existing_exam_total,
            }

        return grouped

    def _build_report(self, grouped) -> list:
        """Build flat report from grouped data. No aggregate scores."""
        subjects_data = []
        for subject, topics in sorted(grouped.items()):
            topics_data = []
            for topic_key, topic_info in sorted(topics.items()):
                subtopics_data = []
                for subtopic_key, sub_info in sorted(topic_info["subtopics"].items()):
                    plan_concepts = set(sub_info.get("plan_concepts", []))
                    covered = set(sub_info.get("concepts_covered", []))
                    coverage = 0.0
                    if plan_concepts:
                        coverage = round(len(covered & plan_concepts) / len(plan_concepts) * 100, 1)

                    subtopics_data.append({
                        "subtopic": sub_info["subtopic_name"],
                        "subtopic_key": subtopic_key,
                        "guideline_id": sub_info.get("guideline_id"),
                        "coverage": coverage,
                        "latest_exam_score": sub_info.get("latest_exam_score"),
                        "latest_exam_total": sub_info.get("latest_exam_total"),
                        "last_studied": sub_info.get("last_studied"),
                    })

                topics_data.append({
                    "topic": topic_info["topic_name"],
                    "topic_key": topic_key,
                    "subtopics": subtopics_data,
                })

            subjects_data.append({
                "subject": subject,
                "topics": topics_data,
            })

        return subjects_data

    def _empty_scorecard(self) -> dict:
        """Return empty report card for users with no sessions."""
        return {
            "total_sessions": 0,
            "total_topics_studied": 0,
            "subjects": [],
        }
