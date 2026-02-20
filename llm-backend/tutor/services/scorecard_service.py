"""Scorecard aggregation service — builds student progress report from session data."""

import json
import logging
from collections import defaultdict

from sqlalchemy.orm import Session as DBSession

from shared.models.entities import Session as SessionModel, TeachingGuideline

logger = logging.getLogger("tutor.scorecard_service")


class ScorecardService:
    """Aggregates session data into a hierarchical student scorecard."""

    def __init__(self, db: DBSession):
        self.db = db

    # ── Public API ──────────────────────────────────────────────

    def get_scorecard(self, user_id: str) -> dict:
        """
        Build the complete scorecard for a student.

        Steps:
        1. Load all sessions for the user
        2. Build guideline_id → hierarchy lookup from teaching_guidelines
        3. Parse each session's state_json, extract topic hierarchy + mastery data
        4. Group by subject → topic → subtopic, keeping only latest session per subtopic
        5. Compute averages bottom-up (subtopic → topic → subject → overall)
        6. Build trend data (date + mastery per subject)
        7. Identify strengths and needs-practice subtopics
        """
        sessions = self._load_user_sessions(user_id)
        if not sessions:
            return self._empty_scorecard()

        guideline_lookup = self._build_guideline_lookup(sessions)
        grouped, trends_raw = self._group_sessions(sessions, guideline_lookup)
        subjects_data = self._compute_scores(grouped)
        self._attach_trends(subjects_data, trends_raw)

        all_subtopics = self._collect_all_subtopics(subjects_data)
        strengths = sorted(
            [s for s in all_subtopics if s["score"] >= 0.65],
            key=lambda x: x["score"], reverse=True,
        )[:5]
        needs_practice = sorted(
            [s for s in all_subtopics if s["score"] < 0.65],
            key=lambda x: x["score"],
        )[:5]

        subject_scores = [s["score"] for s in subjects_data if s["score"] > 0]
        overall_score = sum(subject_scores) / len(subject_scores) if subject_scores else 0.0

        total_sessions = len(sessions)
        total_topics = sum(len(s["topics"]) for s in subjects_data)

        return {
            "overall_score": round(overall_score, 2),
            "total_sessions": total_sessions,
            "total_topics_studied": total_topics,
            "subjects": subjects_data,
            "strengths": [
                {"subtopic": s["subtopic"], "subject": s["subject"], "score": s["score"]}
                for s in strengths
            ],
            "needs_practice": [
                {"subtopic": s["subtopic"], "subject": s["subject"], "score": s["score"]}
                for s in needs_practice
            ],
        }

    def get_subtopic_progress(self, user_id: str) -> dict:
        """
        Returns {guideline_id: {score, session_count, status}} for the
        curriculum picker coverage indicators.
        """
        sessions = self._load_user_sessions(user_id)
        progress = {}

        for session_row in sessions:
            try:
                state = json.loads(session_row.state_json)
            except (json.JSONDecodeError, TypeError):
                continue
            topic_data = state.get("topic") or {}
            topic_id = topic_data.get("topic_id")
            if not topic_id:
                continue

            mastery = session_row.mastery or 0.0
            existing = progress.get(topic_id)
            count = (existing["session_count"] + 1) if existing else 1

            # Latest session wins (sessions ordered ASC, so last write = latest)
            progress[topic_id] = {
                "score": round(mastery, 2),
                "session_count": count,
                "status": "mastered" if mastery >= 0.85 else "in_progress",
            }

        return {"user_progress": progress}

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
            topic = state.get("topic") or {}
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

    def _group_sessions(self, sessions, guideline_lookup) -> tuple:
        """
        Group sessions into subject → topic → subtopic hierarchy.
        For each subtopic, keep only the LATEST session's data.
        Also collect trend data points.

        Returns (grouped, trends_raw).
        """
        grouped = defaultdict(lambda: defaultdict(lambda: {"topic_name": "", "subtopics": {}}))
        trends_raw = defaultdict(list)

        # Determine if sessions span multiple years (for date_label format)
        years = {s.created_at.year for s in sessions if s.created_at}
        span_years = len(years) > 1

        for session_row in sessions:
            try:
                state = json.loads(session_row.state_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Skipping session %s: malformed state_json", session_row.id)
                continue

            topic_data = state.get("topic") or {}
            if not topic_data:
                continue

            subject = topic_data.get("subject", session_row.subject or "Unknown")
            topic_id = topic_data.get("topic_id")
            topic_name_raw = topic_data.get("topic_name", "")

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

            # Extract mastery data
            mastery_estimates = state.get("mastery_estimates", {})
            overall_mastery = session_row.mastery or 0.0
            if mastery_estimates and not overall_mastery:
                overall_mastery = sum(mastery_estimates.values()) / len(mastery_estimates)

            misconceptions = state.get("misconceptions", [])
            session_date = session_row.created_at.isoformat() if session_row.created_at else None
            date_label = (
                session_row.created_at.strftime("%b %d, %Y" if span_years else "%b %d")
                if session_row.created_at else None
            )

            # Group (latest session wins — sessions ordered by created_at ASC)
            existing_count = (
                grouped[subject][topic_key]["subtopics"]
                .get(subtopic_key, {})
                .get("session_count", 0)
            )
            grouped[subject][topic_key]["topic_name"] = topic_name
            grouped[subject][topic_key]["subtopics"][subtopic_key] = {
                "subtopic_name": subtopic_name,
                "guideline_id": topic_id,
                "score": round(overall_mastery, 2),
                "concepts": {k: round(v, 2) for k, v in mastery_estimates.items()},
                "misconceptions": [
                    {"description": m.get("description", ""), "resolved": m.get("resolved", False)}
                    for m in misconceptions
                ],
                "latest_session_date": session_date,
                "session_count": existing_count + 1,
            }

            # Trend data
            trends_raw[subject].append({
                "date": session_date,
                "date_label": date_label,
                "score": round(overall_mastery, 2),
            })

        return grouped, trends_raw

    def _compute_scores(self, grouped) -> list:
        """Compute topic and subject averages from bottom up."""
        subjects_data = []
        for subject, topics in sorted(grouped.items()):
            topics_data = []
            for topic_key, topic_info in sorted(topics.items()):
                subtopics_data = []
                for subtopic_key, sub_info in sorted(topic_info["subtopics"].items()):
                    subtopics_data.append({
                        "subtopic": sub_info["subtopic_name"],
                        "subtopic_key": subtopic_key,
                        "guideline_id": sub_info.get("guideline_id"),
                        "score": sub_info["score"],
                        "session_count": sub_info["session_count"],
                        "latest_session_date": sub_info["latest_session_date"],
                        "concepts": sub_info["concepts"],
                        "misconceptions": sub_info["misconceptions"],
                    })

                subtopic_scores = [s["score"] for s in subtopics_data if s["score"] > 0]
                topic_score = sum(subtopic_scores) / len(subtopic_scores) if subtopic_scores else 0.0

                topics_data.append({
                    "topic": topic_info["topic_name"],
                    "topic_key": topic_key,
                    "score": round(topic_score, 2),
                    "subtopics": subtopics_data,
                })

            topic_scores = [t["score"] for t in topics_data if t["score"] > 0]
            subject_score = sum(topic_scores) / len(topic_scores) if topic_scores else 0.0

            session_count = sum(
                s["session_count"]
                for t in topics_data
                for s in t["subtopics"]
            )

            subjects_data.append({
                "subject": subject,
                "score": round(subject_score, 2),
                "session_count": session_count,
                "topics": topics_data,
                "trend": [],
            })

        return subjects_data

    def _attach_trends(self, subjects_data, trends_raw):
        """Attach trend data to each subject."""
        for subject_entry in subjects_data:
            subject_name = subject_entry["subject"]
            if subject_name in trends_raw:
                subject_entry["trend"] = trends_raw[subject_name]

    def _collect_all_subtopics(self, subjects_data) -> list:
        """Flatten all subtopics for strengths/needs-practice ranking."""
        result = []
        for subject in subjects_data:
            for topic in subject["topics"]:
                for subtopic in topic["subtopics"]:
                    result.append({
                        "subtopic": subtopic["subtopic"],
                        "subject": subject["subject"],
                        "score": subtopic["score"],
                    })
        return result

    def _empty_scorecard(self) -> dict:
        """Return empty scorecard for users with no sessions."""
        return {
            "overall_score": 0,
            "total_sessions": 0,
            "total_topics_studied": 0,
            "subjects": [],
            "strengths": [],
            "needs_practice": [],
        }
