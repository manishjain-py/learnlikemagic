"""Baatcheet (Conversational Teach Me) unit tests.

Covers the minimum set called out in `docs/feature-development/baatcheet/
pr121-fix-plan.md` §"Tests to add" — the regressions any V1 ship should be
guarded against:

* F1 — `Session.teach_me_mode` ORM round-trip persists the submode; the
  paused-session unique index includes `teach_me_mode` so paused Baatcheet +
  paused Explain coexist for the same `(user, guideline)`.
* F4 — `count_dialogue_audio_items` counts dialogue clips alongside variant A
  so the audio_synthesis status tile doesn't read "done" with missing dialogue
  MP3s.
* F5 — `{topic_name}` outside the welcome card is rejected by the validator.
* F6 — banned audio patterns + `{student_name}` are caught inside check-in
  fields, not just `lines[].audio`.
* F7 — `BaatcheetAudioReviewService` mirrors `check_in.audio_text` to the
  top-level field so `_apply_revisions` can land `check_in_text` revisions on
  dialogue check-in cards.
* F8 — `_finalize_baatcheet_session` populates `concepts_covered_set` with
  concept TOKENS from the study plan, not display titles.
* F9 — emoji range covers Misc Technical (`⏰`, `▶`, `□`, etc.).
* Voice routing — `speaker == "peer"` → `PEER_VOICE`; otherwise → tutor.
* TTS allowlist — `voice_role` Pydantic field rejects arbitrary values.

The TTS / S3 / LLM clients are stubbed so these run offline.
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


# ─── F1: Session.teach_me_mode ORM round-trip ─────────────────────────────


class TestSessionTeachMeModeOrmRoundTrip:
    """The chooser endpoint queries `SessionModel.teach_me_mode` directly via
    SQLAlchemy. Without the ORM column it AttributeErrors at filter
    construction. This test fails immediately if the column is missing."""

    def test_teach_me_mode_column_is_queryable(self, db_session):
        """Real query through the ORM — fails if the column is missing or the
        type can't be bound. More durable than asserting on str(expr)'s bind
        naming, which depends on SQLAlchemy version."""
        from shared.models.entities import Session as SessionModel
        rows = (
            db_session.query(SessionModel)
            .filter(SessionModel.teach_me_mode == "baatcheet")
            .all()
        )
        assert rows == []

    def test_teach_me_mode_persists_baatcheet_value(self, db_session):
        from shared.models.entities import Session as SessionModel

        sid = "sess-baat-1"
        row = SessionModel(
            id=sid,
            student_json="{}",
            goal_json="{}",
            state_json="{}",
            user_id=None,
            mode="teach_me",
            teach_me_mode="baatcheet",
        )
        db_session.add(row)
        db_session.commit()

        fetched = (
            db_session.query(SessionModel)
            .filter(SessionModel.id == sid)
            .first()
        )
        assert fetched.teach_me_mode == "baatcheet"

    def test_teach_me_mode_default_explain(self, db_session):
        from shared.models.entities import Session as SessionModel

        sid = "sess-explain-default"
        row = SessionModel(
            id=sid,
            student_json="{}",
            goal_json="{}",
            state_json="{}",
            user_id=None,
            mode="teach_me",
            # teach_me_mode omitted — column default is 'explain'
        )
        db_session.add(row)
        db_session.commit()

        fetched = (
            db_session.query(SessionModel)
            .filter(SessionModel.id == sid)
            .first()
        )
        assert fetched.teach_me_mode == "explain"

    def test_paused_unique_index_allows_coexist_and_blocks_dupes(self, db_session):
        """PRD §FR-4: a paused Baatcheet and a paused Explain session for the
        same (user, guideline) must coexist; two paused rows with the SAME
        teach_me_mode must collide on the partial unique index.

        The migration that builds this index (db.py:_apply_sessions_teach_me_mode_column)
        runs against Postgres. The ORM `__table_args__` only declares the
        non-unique lookup index, so the SQLite test fixture would otherwise
        accept any combination. We materialize the production partial unique
        index here so this test fails if the migration's column list regresses.
        """
        from shared.models.entities import Session as SessionModel

        # Mirror the production partial unique index on the in-memory engine.
        # SQLite supports partial indexes; `is_paused` is stored as 0/1.
        db_session.execute(text(
            "CREATE UNIQUE INDEX idx_sessions_one_paused_per_user_guideline "
            "ON sessions(user_id, guideline_id, mode, teach_me_mode) "
            "WHERE is_paused = 1"
        ))
        db_session.commit()

        baatcheet = SessionModel(
            id="paused-baat",
            student_json="{}", goal_json="{}", state_json="{}",
            user_id="u1", guideline_id="g1", mode="teach_me",
            teach_me_mode="baatcheet", is_paused=True,
        )
        explain = SessionModel(
            id="paused-explain",
            student_json="{}", goal_json="{}", state_json="{}",
            user_id="u1", guideline_id="g1", mode="teach_me",
            teach_me_mode="explain", is_paused=True,
        )
        db_session.add_all([baatcheet, explain])
        db_session.commit()  # different teach_me_mode → both fit

        rows = (
            db_session.query(SessionModel)
            .filter(SessionModel.user_id == "u1", SessionModel.is_paused.is_(True))
            .all()
        )
        modes = {r.teach_me_mode for r in rows}
        assert modes == {"baatcheet", "explain"}

        # Negative case: two paused rows with the SAME teach_me_mode must
        # collide. If a future migration drops teach_me_mode from the index,
        # the first assert above would still pass — this one would not.
        dup = SessionModel(
            id="paused-baat-2",
            student_json="{}", goal_json="{}", state_json="{}",
            user_id="u1", guideline_id="g1", mode="teach_me",
            teach_me_mode="baatcheet", is_paused=True,
        )
        db_session.add(dup)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ─── F4: count_dialogue_audio_items ───────────────────────────────────────


class TestCountDialogueAudioItems:
    """The audio_synthesis status tile previously counted only variant A
    clips, so a topic with full variant A audio + missing dialogue audio read
    `done`. The static counter mirrors `generate_for_topic_dialogue`'s skip
    rules so the tile reflects reality."""

    def test_counts_lines_with_url_and_without(self):
        from book_ingestion_v2.services.audio_generation_service import (
            AudioGenerationService,
        )
        cards = [
            {
                "card_idx": 1, "card_type": "tutor_turn", "card_id": "t1",
                "speaker": "tutor",
                "lines": [
                    {"audio": "Hello there.", "audio_url": "https://s3/1.mp3", "display": "Hello there."},
                    {"audio": "Let's begin.", "display": "Let's begin."},
                ],
            },
        ]
        total, existing = AudioGenerationService.count_dialogue_audio_items(cards)
        assert total == 2
        assert existing == 1

    def test_skips_includes_student_name_cards(self):
        from book_ingestion_v2.services.audio_generation_service import (
            AudioGenerationService,
        )
        cards = [
            {
                "card_idx": 1, "card_type": "welcome", "card_id": "w1",
                "speaker": "tutor", "includes_student_name": True,
                "lines": [{"audio": "Hi {student_name}!", "display": "Hi {student_name}!"}],
            },
            {
                "card_idx": 2, "card_type": "tutor_turn", "card_id": "t2",
                "speaker": "tutor",
                "lines": [{"audio": "Standard line.", "display": "Standard line."}],
            },
        ]
        total, existing = AudioGenerationService.count_dialogue_audio_items(cards)
        # Welcome card skipped entirely; only the tutor_turn line counts.
        assert total == 1
        assert existing == 0

    def test_skips_lines_with_unsubstituted_placeholder(self):
        from book_ingestion_v2.services.audio_generation_service import (
            AudioGenerationService,
        )
        cards = [
            {
                "card_idx": 1, "card_type": "tutor_turn", "card_id": "t1",
                "speaker": "tutor",
                "lines": [
                    {"audio": "Hi {student_name}, ready?", "display": "Hi {student_name}, ready?"},
                    {"audio": "Plain line.", "display": "Plain line."},
                ],
            },
        ]
        total, _ = AudioGenerationService.count_dialogue_audio_items(cards)
        # Placeholder line not counted (frontend handles via runtime TTS).
        assert total == 1

    def test_counts_check_in_fields(self):
        from book_ingestion_v2.services.audio_generation_service import (
            AudioGenerationService,
        )
        cards = [
            {
                "card_idx": 5, "card_type": "check_in", "card_id": "ci-1",
                "check_in": {
                    "activity_type": "pick_one",
                    "audio_text": "Which one?",
                    "hint": "Think about it.",
                    "success_message": "Yes!",
                    "audio_text_url": "https://s3/at.mp3",
                },
            },
        ]
        total, existing = AudioGenerationService.count_dialogue_audio_items(cards)
        # 3 always-fields: audio_text + hint + success_message
        assert total == 3
        assert existing == 1


# ─── F5 + F6 + F9: validators ─────────────────────────────────────────────


class TestValidatorTopicNamePlaceholder:
    """{topic_name} is a runtime substitution that only the server-prepended
    welcome card resolves. Anywhere else it would TTS as the literal string."""

    def _build_minimal_deck(self) -> list:
        """A 25-card deck that's structurally valid: welcome + 23 tutor turns
        + summary. Caller mutates a single card to inject the rule under test."""
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            DialogueCardOutput, DialogueLineOutput,
        )
        cards = [DialogueCardOutput(
            card_idx=1, card_type="welcome", speaker="tutor",
            includes_student_name=True,
            lines=[DialogueLineOutput(
                display="Hi {student_name}! Today we learn {topic_name}.",
                audio="Hi {student_name}! Today we learn {topic_name}.",
            )],
        )]
        for i in range(2, 25):
            cards.append(DialogueCardOutput(
                card_idx=i, card_type="tutor_turn", speaker="tutor",
                lines=[DialogueLineOutput(
                    display=f"Filler line {i}.", audio=f"Filler line {i}.",
                )],
            ))
        cards.append(DialogueCardOutput(
            card_idx=25, card_type="summary", speaker="tutor",
            lines=[DialogueLineOutput(display="Wrap up.", audio="Wrap up.")],
        ))
        return cards

    def test_topic_name_in_non_welcome_card_fails(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            DialogueLineOutput, _validate_cards,
        )
        cards = self._build_minimal_deck()
        cards[5].lines = [DialogueLineOutput(
            display="Now look at {topic_name} again.",
            audio="Now look at {topic_name} again.",
        )]

        issues = _validate_cards(cards, raise_on_fail=False)
        assert any("{topic_name}" in i and "welcome" in i for i in issues), issues

    def test_topic_name_in_welcome_card_passes(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_cards,
        )
        cards = self._build_minimal_deck()
        # Welcome card itself contains {topic_name} — must not flag.
        issues = _validate_cards(cards, raise_on_fail=False)
        assert not any("{topic_name}" in i for i in issues), issues


class TestValidatorBannedPatternsInCheckIn:
    """F6: banned audio patterns + {student_name} must be caught inside the
    check-in fields, not only `lines[].audio`. V1 pre-renders check-in audio
    statically — a placeholder there would never get substituted."""

    def _build_deck_with_check_in(self) -> list:
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            DialogueCardOutput, DialogueLineOutput, CheckInActivityOutput,
        )
        cards = [DialogueCardOutput(
            card_idx=1, card_type="welcome", speaker="tutor",
            includes_student_name=True,
            lines=[DialogueLineOutput(
                display="Hi {student_name}!", audio="Hi {student_name}!",
            )],
        )]
        for i in range(2, 7):
            cards.append(DialogueCardOutput(
                card_idx=i, card_type="tutor_turn", speaker="tutor",
                lines=[DialogueLineOutput(
                    display=f"Line {i}.", audio=f"Line {i}.",
                )],
            ))
        # Card 7 = check-in
        cards.append(DialogueCardOutput(
            card_idx=7, card_type="check_in",
            check_in=CheckInActivityOutput(
                activity_type="pick_one",
                instruction="Pick one",
                hint="Think.",
                success_message="Nice.",
                audio_text="Choose now.",
                options=["a", "b"],
                correct_index=0,
            ),
        ))
        for i in range(8, 25):
            cards.append(DialogueCardOutput(
                card_idx=i, card_type="tutor_turn", speaker="tutor",
                lines=[DialogueLineOutput(
                    display=f"Line {i}.", audio=f"Line {i}.",
                )],
            ))
        cards.append(DialogueCardOutput(
            card_idx=25, card_type="summary", speaker="tutor",
            lines=[DialogueLineOutput(display="Wrap up.", audio="Wrap up.")],
        ))
        return cards

    def test_student_name_in_check_in_hint_fails(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_cards,
        )
        cards = self._build_deck_with_check_in()
        cards[6].check_in.hint = "Hi {student_name}, think about it."

        issues = _validate_cards(cards, raise_on_fail=False)
        assert any("{student_name}" in i and "check_in.hint" in i for i in issues), issues

    def test_markdown_bold_in_check_in_audio_text_fails(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_cards,
        )
        cards = self._build_deck_with_check_in()
        cards[6].check_in.audio_text = "Pick the **biggest** one."

        issues = _validate_cards(cards, raise_on_fail=False)
        assert any("banned pattern" in i and "check_in" in i for i in issues), issues

    def test_emoji_in_check_in_success_message_fails(self):
        """F9: emoji range now covers Misc Technical (▶, ⏰, □ in U+2300-U+25FF)."""
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_cards,
        )
        cards = self._build_deck_with_check_in()
        cards[6].check_in.success_message = "Right ▶"

        issues = _validate_cards(cards, raise_on_fail=False)
        assert any("banned pattern" in i and "check_in" in i for i in issues), issues

    def test_unsupported_activity_type_fails(self):
        """F6 nit: dialogue generator validates against the 11 supported
        CheckInDispatcher types so unsupported shapes never reach the frontend."""
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_cards,
        )
        cards = self._build_deck_with_check_in()
        cards[6].check_in.activity_type = "totally_made_up"

        issues = _validate_cards(cards, raise_on_fail=False)
        assert any("activity_type" in i and "supported" in i for i in issues), issues


class TestValidatorBannedEmojiRangeMiscTechnical:
    """F9: regex must hit U+2300-U+27BF (was U+2600 onwards) so symbols like
    ▶ (U+25B6) and ⏰ (U+23F0) are rejected in lines[].audio too. Without this
    they leak into pre-rendered MP3s."""

    def test_misc_technical_arrow_in_line_audio_fails(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            DialogueCardOutput, DialogueLineOutput, _validate_cards,
        )
        cards = [DialogueCardOutput(
            card_idx=1, card_type="welcome", speaker="tutor",
            includes_student_name=True,
            lines=[DialogueLineOutput(
                display="Hi {student_name}!", audio="Hi {student_name}!",
            )],
        )]
        for i in range(2, 25):
            cards.append(DialogueCardOutput(
                card_idx=i, card_type="tutor_turn", speaker="tutor",
                lines=[DialogueLineOutput(
                    display="OK.", audio="OK.",
                )],
            ))
        # Card 5 line carries ▶ (U+25B6) — must be caught by the widened range.
        cards[5].lines[0].audio = "Tap the ▶ symbol."
        cards.append(DialogueCardOutput(
            card_idx=25, card_type="summary", speaker="tutor",
            lines=[DialogueLineOutput(display="Done.", audio="Done.")],
        ))

        issues = _validate_cards(cards, raise_on_fail=False)
        assert any("banned pattern" in i and "audio" in i for i in issues), issues


# ─── F7: BaatcheetAudioReviewService applies check_in_text revisions ──────


class TestBaatcheetAudioReviewServiceCheckInTextRevisions:
    """Variant A check-in cards expose `audio_text` at the top level *and* on
    `check_in.audio_text`. Dialogue check-in cards only have the nested form.
    Before the fix, `_apply_revisions` for `kind == "check_in_text"` drift-
    checked against `card["audio_text"]` (top-level) and dropped every
    revision on a dialogue card. The fix lets `_apply_revisions` resolve
    against either shape."""

    def test_apply_revisions_handles_dialogue_check_in_shape(self):
        from book_ingestion_v2.services.audio_text_review_service import (
            AudioLineRevision, AudioTextReviewService,
        )

        svc = AudioTextReviewService.__new__(AudioTextReviewService)
        svc.db = MagicMock()
        svc.llm = MagicMock()
        svc.language = "en"

        # Dialogue check-in card: NO top-level audio_text. Only nested.
        card = {
            "card_idx": 7,
            "card_type": "check_in",
            "card_id": "ci-x",
            "check_in": {
                "activity_type": "pick_one",
                "instruction": "Pick one",
                "audio_text": "Which fraction is bigger??",
                "hint": "Compare numerators.",
                "success_message": "Right!",
            },
        }
        revisions = [AudioLineRevision(
            card_idx=7, line_idx=None, kind="check_in_text",
            original_audio="Which fraction is bigger??",
            revised_audio="Which fraction is bigger?",
            reason="double-question-mark cleanup",
        )]
        applied = svc._apply_revisions(card, revisions)
        assert applied == 1
        assert card["check_in"]["audio_text"] == "Which fraction is bigger?"
        assert card["check_in"]["audio_text_url"] is None

    def test_apply_revisions_drops_revision_on_real_drift(self):
        from book_ingestion_v2.services.audio_text_review_service import (
            AudioLineRevision, AudioTextReviewService,
        )
        svc = AudioTextReviewService.__new__(AudioTextReviewService)
        svc.db = MagicMock(); svc.llm = MagicMock(); svc.language = "en"

        card = {
            "card_idx": 7, "card_type": "check_in", "card_id": "ci-x",
            "check_in": {
                "audio_text": "ACTUAL TEXT",
                "activity_type": "pick_one",
            },
        }
        revisions = [AudioLineRevision(
            card_idx=7, line_idx=None, kind="check_in_text",
            original_audio="DIFFERENT ORIGINAL",
            revised_audio="WHATEVER",
            reason="testing drift guard",
        )]
        applied = svc._apply_revisions(card, revisions)
        assert applied == 0
        assert card["check_in"]["audio_text"] == "ACTUAL TEXT"


# ─── F8: _finalize_baatcheet_session uses concept tokens ──────────────────


class TestFinalizeBaatcheetSessionConceptTokens:
    """Critical: `coverage_percentage` intersects `concepts_covered_set` with
    `study_plan.get_concepts()`. Both must hold concept tokens, not display
    titles. The fix bulk-adds every study-plan concept on Baatcheet completion
    so coverage is identical between Explain and Baatcheet for the same topic."""

    def _make_session_with_dialogue_phase(self):
        from tutor.models.session_state import DialoguePhaseState, create_session
        from tutor.models.study_plan import (
            StudyPlan, StudyPlanStep, Topic, TopicGuidelines,
        )
        from tutor.models.messages import StudentContext

        topic = Topic(
            topic_id="math_fractions_basics",
            topic_name="Fractions",
            subject="Math", grade_level=3,
            guidelines=TopicGuidelines(
                learning_objectives=["Understand fractions"],
                common_misconceptions=[],
                scope_boundary="Single-digit denominators",
            ),
            study_plan=StudyPlan(steps=[
                StudyPlanStep(step_id=1, type="explain",
                              concept="numerator_vs_denominator",
                              content_hint="Pizza"),
                StudyPlanStep(step_id=2, type="explain",
                              concept="like_denominators_compare",
                              content_hint="Bigger numerator wins"),
                StudyPlanStep(step_id=3, type="check",
                              concept="like_denominators_compare",
                              question_type="conceptual"),
            ]),
        )
        ctx = StudentContext(grade=3, board="CBSE", language_level="simple")
        session = create_session(topic=topic, student_context=ctx)
        session.session_id = "test-session-fin"
        session.dialogue_phase = DialoguePhaseState(
            guideline_id="g1", active=True,
            current_card_idx=15, total_cards=25,
        )
        # Realistic precondition: the user paused mid-deck and is finishing now.
        session.is_paused = True
        return session

    def test_finalize_adds_concept_tokens_to_covered_set(self):
        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()

        session = self._make_session_with_dialogue_phase()
        # Pre-condition: nothing covered yet.
        assert session.concepts_covered_set == set()

        svc._finalize_baatcheet_session(session)

        # Two unique concept tokens (the third step shares the second's concept).
        assert "numerator_vs_denominator" in session.concepts_covered_set
        assert "like_denominators_compare" in session.concepts_covered_set
        # The mirror set master_tutor reads.
        assert "numerator_vs_denominator" in session.card_covered_concepts
        # Coverage = 100% because concepts_covered_set ∩ get_concepts() == get_concepts()
        assert session.coverage_percentage == 100.0
        assert session.dialogue_phase.completed is True
        assert session.dialogue_phase.active is False
        assert session.is_paused is False

    def test_finalize_idempotent(self):
        from tutor.services.session_service import SessionService

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()

        session = self._make_session_with_dialogue_phase()
        assert session.is_paused is True  # precondition seeded by helper
        svc._finalize_baatcheet_session(session)
        first = set(session.concepts_covered_set)
        assert session.is_paused is False  # transition happened on first call

        # Second call must not error, must not add stale duplicates, must not
        # flip is_paused back.
        svc._finalize_baatcheet_session(session)
        second = set(session.concepts_covered_set)
        assert first == second
        assert session.dialogue_phase.completed is True
        assert session.is_paused is False

    def test_finalize_without_dialogue_phase_is_noop(self):
        from tutor.models.session_state import create_session
        from tutor.models.study_plan import (
            StudyPlan, StudyPlanStep, Topic, TopicGuidelines,
        )
        from tutor.models.messages import StudentContext
        from tutor.services.session_service import SessionService

        topic = Topic(
            topic_id="t1", topic_name="X", subject="M", grade_level=3,
            guidelines=TopicGuidelines(
                learning_objectives=[], common_misconceptions=[],
                scope_boundary="",
            ),
            study_plan=StudyPlan(steps=[
                StudyPlanStep(step_id=1, type="explain",
                              concept="c1", content_hint=""),
            ]),
        )
        ctx = StudentContext(grade=3, board="CBSE", language_level="simple")
        session = create_session(topic=topic, student_context=ctx)
        session.dialogue_phase = None

        svc = SessionService.__new__(SessionService)
        svc.db = MagicMock()
        svc._finalize_baatcheet_session(session)

        assert session.concepts_covered_set == set()


# ─── Voice routing (per-speaker) ──────────────────────────────────────────


class TestVoiceRoutingForSpeaker:
    """Per-card voice routing: peer → PEER_VOICE; everything else → tutor.
    Variant A cards have no `speaker` field — they must continue to use the
    language-mapped tutor voice (backwards-compat)."""

    def test_peer_routes_to_peer_voice(self):
        from book_ingestion_v2.services.audio_generation_service import (
            PEER_VOICE, _voice_for_speaker,
        )
        assert _voice_for_speaker("peer", "hinglish") == PEER_VOICE

    def test_tutor_routes_to_language_voice(self):
        from book_ingestion_v2.services.audio_generation_service import (
            VOICE_MAP, _voice_for_speaker,
        )
        assert _voice_for_speaker("tutor", "hinglish") == VOICE_MAP["hinglish"]
        assert _voice_for_speaker("tutor", "en") == VOICE_MAP["en"]

    def test_absent_speaker_routes_to_language_voice(self):
        """Variant A cards have no speaker field — must keep working."""
        from book_ingestion_v2.services.audio_generation_service import (
            VOICE_MAP, _voice_for_speaker,
        )
        assert _voice_for_speaker(None, "en") == VOICE_MAP["en"]

    def test_unknown_speaker_falls_through_to_tutor(self):
        from book_ingestion_v2.services.audio_generation_service import (
            VOICE_MAP, _voice_for_speaker,
        )
        assert _voice_for_speaker("anchor", "en") == VOICE_MAP["en"]

    def test_peer_voice_is_distinct_from_tutor(self):
        """Sanity check on the Meera selection — must NOT be Kore (the tutor
        voice). PRD §FR-37."""
        from book_ingestion_v2.services.audio_generation_service import (
            PEER_VOICE, TUTOR_VOICE,
        )
        assert PEER_VOICE != TUTOR_VOICE
        assert "Kore" not in PEER_VOICE[1]


# ─── TTS endpoint allowlist ───────────────────────────────────────────────


class TestTTSVoiceRoleAllowlist:
    """Security boundary: frontend can pass only `voice_role: "tutor" | "peer"`.
    Pydantic Literal rejects everything else at request validation time, so
    arbitrary Google voice IDs can never reach the synthesis call."""

    def test_voice_role_accepts_tutor(self):
        from tutor.api.tts import TTSRequest
        req = TTSRequest(text="hello", voice_role="tutor")
        assert req.voice_role == "tutor"

    def test_voice_role_accepts_peer(self):
        from tutor.api.tts import TTSRequest
        req = TTSRequest(text="hello", voice_role="peer")
        assert req.voice_role == "peer"

    def test_voice_role_default_is_tutor(self):
        from tutor.api.tts import TTSRequest
        req = TTSRequest(text="hello")
        assert req.voice_role == "tutor"

    def test_voice_role_rejects_arbitrary_string(self):
        from tutor.api.tts import TTSRequest
        with pytest.raises(ValidationError):
            TTSRequest(text="hello", voice_role="hi-IN-Chirp3-HD-Kore")

    def test_voice_role_rejects_none(self):
        from tutor.api.tts import TTSRequest
        with pytest.raises(ValidationError):
            TTSRequest(text="hello", voice_role=None)


# ─── DialogueCard schema ──────────────────────────────────────────────────


class TestDialogueCardSchema:
    """Reuses ExplanationLine + CheckInActivity from explanation_repository.
    A regression here means dialogue cards stored with an unrecognised field
    silently round-trip wrong, breaking the carousel."""

    def test_round_trip_minimal_dialogue_card(self):
        from shared.repositories.dialogue_repository import (
            DialogueCard, DialogueRepository,
        )
        cards_json = [{
            "card_id": str(uuid4()),
            "card_idx": 1,
            "card_type": "welcome",
            "speaker": "tutor",
            "speaker_name": "Mr. Verma",
            "includes_student_name": True,
            "lines": [{"display": "Hi {student_name}!", "audio": "Hi {student_name}!"}],
        }]
        parsed = DialogueRepository.parse_cards(cards_json)
        assert len(parsed) == 1
        assert parsed[0].card_type == "welcome"
        assert parsed[0].speaker == "tutor"
        assert parsed[0].includes_student_name is True

    def test_invalid_speaker_value_rejected(self):
        from shared.repositories.dialogue_repository import DialogueCard
        with pytest.raises(ValidationError):
            DialogueCard(card_idx=1, card_type="welcome", speaker="narrator")

    def test_invalid_card_type_rejected(self):
        from shared.repositories.dialogue_repository import DialogueCard
        with pytest.raises(ValidationError):
            DialogueCard(card_idx=1, card_type="something_new")


# ─── V2 designed-lesson plan: persistence + validation ───────────────────


def _sample_plan():
    """Minimal plan that satisfies _validate_plan (2-3 misconceptions, 25-40
    card_plan entries, spine.situation present)."""
    return {
        "misconceptions": [
            {"id": "M1", "name": "evap-only-when-boiling", "description": "...", "evidence_note": "...", "concrete_disproof": "wet fingertip dries"},
            {"id": "M2", "name": "clouds-are-cotton", "description": "...", "evidence_note": "...", "concrete_disproof": "cold glass droplets"},
        ],
        "spine": {
            "situation": "wet school uniform on terrace clothesline",
            "particulars": ["Meera", "white uniform", "terrace"],
            "opening_hook": "where does the water go?",
            "midpoint_callbacks": ["mid-a", "mid-b"],
            "closing_resolution": "tomorrow's rain may be yesterday's uniform water",
        },
        "concrete_materials": [{"item": "fingertip with water", "use": "feel evaporation directly"}],
        "macro_structure": [
            {"phase": "hook", "card_count": 6, "purpose": "open with terrace"},
            {"phase": "cycle_M1", "card_count": 7, "purpose": "trap-fall-resolve"},
        ],
        "card_plan": [
            {"slot": i, "move": "hook", "speaker": "tutor", "card_type": "tutor_turn",
             "target": "spine", "intent": "open"}
            for i in range(2, 32)  # 30 slots → in 25-40 range
        ],
    }


class TestJSONPreambleTolerance:
    """The refine stage's dense plan-adherence prompt occasionally leads the
    model to narrate before/after the JSON despite explicit "JSON only"
    instructions. The extractor must handle preamble that itself contains
    curly-brace literals like `{student_name}` or `{topic_name}` — a naive
    first-`{` to last-`}` scan would slice through that and fail."""

    def test_clean_json_passes_through(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _parse_json_with_preamble_tolerance,
        )
        assert _parse_json_with_preamble_tolerance('{"a": 1}') == {"a": 1}

    def test_preamble_stripped(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _parse_json_with_preamble_tolerance,
        )
        text = "Looking at this dialogue, I need to fix several issues:\n\n" \
               '{"cards": [{"card_idx": 2}]}'
        assert _parse_json_with_preamble_tolerance(text) == {"cards": [{"card_idx": 2}]}

    def test_trailing_prose_stripped(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _parse_json_with_preamble_tolerance,
        )
        text = '{"a": 1}\n\nThat is my answer.'
        assert _parse_json_with_preamble_tolerance(text) == {"a": 1}

    def test_markdown_fence_unwrapped(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _parse_json_with_preamble_tolerance,
        )
        text = "Here:\n\n```json\n" + '{"a": 1}' + "\n```\n"
        assert _parse_json_with_preamble_tolerance(text) == {"a": 1}

    def test_preamble_with_curly_brace_literals(self):
        """Real failure mode: refine prompt's preamble references
        `{student_name}` and `{topic_name}` literally. Naive scan would
        slice into those — must skip past."""
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _parse_json_with_preamble_tolerance,
        )
        text = (
            "Looking at this dialogue, I need to fix:\n"
            "- Card 12 lacks `{student_name}`\n"
            "- Card 22 has issues with {topic_name}\n\n"
            '{"cards": [{"card_idx": 2, "card_type": "tutor_turn"}]}'
        )
        out = _parse_json_with_preamble_tolerance(text)
        assert out == {"cards": [{"card_idx": 2, "card_type": "tutor_turn"}]}

    def test_no_json_raises_llmserviceerror(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _parse_json_with_preamble_tolerance,
        )
        from shared.services.llm_service import LLMServiceError
        with pytest.raises(LLMServiceError, match="No JSON object found"):
            _parse_json_with_preamble_tolerance("No JSON anywhere here")


class TestLessonPlanValidator:
    """Lightweight plan-shape validator. Detailed schema lives in the prompt;
    this is a backstop against LLM drift that would corrupt the dialogue stage."""

    def test_valid_plan_passes(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import _validate_plan
        _validate_plan(_sample_plan())  # no raise

    def test_missing_top_level_keys_raises(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_plan, LessonPlanValidationError,
        )
        with pytest.raises(LessonPlanValidationError, match="missing keys"):
            _validate_plan({"misconceptions": [], "spine": {}, "card_plan": []})

    def test_card_plan_too_short_raises(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_plan, LessonPlanValidationError,
        )
        plan = _sample_plan()
        plan["card_plan"] = plan["card_plan"][:5]
        with pytest.raises(LessonPlanValidationError, match="card_plan must be 25-40"):
            _validate_plan(plan)

    def test_card_plan_too_long_raises(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_plan, LessonPlanValidationError,
        )
        plan = _sample_plan()
        plan["card_plan"] = plan["card_plan"] * 2  # 60 entries
        with pytest.raises(LessonPlanValidationError, match="card_plan must be 25-40"):
            _validate_plan(plan)

    def test_misconceptions_wrong_count_raises(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_plan, LessonPlanValidationError,
        )
        plan = _sample_plan()
        plan["misconceptions"] = []
        with pytest.raises(LessonPlanValidationError, match="2-3 entries"):
            _validate_plan(plan)

    def test_spine_missing_situation_raises(self):
        from book_ingestion_v2.services.baatcheet_dialogue_generator_service import (
            _validate_plan, LessonPlanValidationError,
        )
        plan = _sample_plan()
        plan["spine"] = {}
        with pytest.raises(LessonPlanValidationError, match="spine must have"):
            _validate_plan(plan)


class TestTopicDialoguePlanJsonRoundTrip:
    """V2 plan_json column on topic_dialogues. A regression here means the
    plan that drove generation is lost, breaking provenance + Phase 6
    autoresearch (which optimises against the plan)."""

    def test_plan_json_persists_via_orm(self, db_session):
        from shared.models.entities import TopicDialogue
        plan = _sample_plan()
        d = TopicDialogue(
            id="td-1",
            guideline_id="g-1",
            cards_json=[{"card_idx": 1, "card_type": "welcome"}],
            plan_json=plan,
            generator_model="claude-opus-4-7",
        )
        db_session.add(d)
        db_session.commit()

        fetched = db_session.query(TopicDialogue).filter(TopicDialogue.id == "td-1").first()
        assert fetched.plan_json is not None
        assert len(fetched.plan_json["misconceptions"]) == 2
        assert fetched.plan_json["spine"]["situation"].startswith("wet school uniform")
        assert len(fetched.plan_json["card_plan"]) == 30

    def test_plan_json_nullable_for_v1_rows(self, db_session):
        """Existing V1 rows pre-date the plan stage. Column must be nullable."""
        from shared.models.entities import TopicDialogue
        d = TopicDialogue(
            id="td-v1",
            guideline_id="g-v1",
            cards_json=[{"card_idx": 1, "card_type": "welcome"}],
            generator_model="claude-opus-4-7",
            # plan_json omitted
        )
        db_session.add(d)
        db_session.commit()
        fetched = db_session.query(TopicDialogue).filter(TopicDialogue.id == "td-v1").first()
        assert fetched.plan_json is None


class TestDialogueRepositoryUpsertWithPlan:
    """DialogueRepository.upsert is the only call site that writes
    topic_dialogues. The plan_json kwarg must flow through to the row."""

    def test_upsert_persists_plan_json(self, db_session):
        from shared.repositories.dialogue_repository import DialogueRepository
        from shared.models.entities import TopicDialogue

        repo = DialogueRepository(db_session)
        plan = _sample_plan()
        d = repo.upsert(
            guideline_id="g-up",
            cards_json=[{"card_idx": 1, "card_type": "welcome"}],
            generator_model="claude-opus-4-7",
            plan_json=plan,
        )
        assert d.plan_json is not None
        assert d.plan_json["spine"]["situation"].startswith("wet school uniform")

        # Re-fetch via the repo to confirm it survived round-trip
        refetched = repo.get_by_guideline_id("g-up")
        assert refetched is not None
        assert refetched.plan_json["spine"]["situation"].startswith("wet school uniform")

    def test_upsert_without_plan_works(self, db_session):
        """Backward compat: upsert without plan_json (e.g., legacy callers
        or partial-state recovery) must not crash."""
        from shared.repositories.dialogue_repository import DialogueRepository

        repo = DialogueRepository(db_session)
        d = repo.upsert(
            guideline_id="g-legacy",
            cards_json=[{"card_idx": 1, "card_type": "welcome"}],
            generator_model="claude-opus-4-7",
        )
        assert d.plan_json is None

    def test_upsert_replaces_plan_on_regenerate(self, db_session):
        """upsert is delete-then-insert — re-running generation with a fresh
        plan should overwrite the old plan, not stack two rows."""
        from shared.repositories.dialogue_repository import DialogueRepository
        from shared.models.entities import TopicDialogue

        repo = DialogueRepository(db_session)
        plan_v1 = _sample_plan()
        plan_v1["spine"]["situation"] = "first run"
        repo.upsert(
            guideline_id="g-regen",
            cards_json=[{"card_idx": 1, "card_type": "welcome"}],
            generator_model="claude-opus-4-7",
            plan_json=plan_v1,
        )

        plan_v2 = _sample_plan()
        plan_v2["spine"]["situation"] = "second run"
        repo.upsert(
            guideline_id="g-regen",
            cards_json=[{"card_idx": 1, "card_type": "welcome"}],
            generator_model="claude-opus-4-7",
            plan_json=plan_v2,
        )

        rows = db_session.query(TopicDialogue).filter(
            TopicDialogue.guideline_id == "g-regen"
        ).all()
        assert len(rows) == 1
        assert rows[0].plan_json["spine"]["situation"] == "second run"


# ─── Hash invariants ──────────────────────────────────────────────────────


class TestDialogueHashInvariants:
    """Audio enrichment mutates `audio_url` and `pixi_code` in place. The
    semantic hash MUST exclude those — otherwise every audio refresh would
    mark every dialogue stale. Conversely, line text edits must change the
    hash so the staleness signal works."""

    def _base_cards(self):
        return [{
            "card_type": "tutor_turn",
            "title": "Intro",
            "content": "Pizza",
            "audio_text": "Pizza fractions",
            "lines": [{"display": "Hello", "audio": "Hello"}],
        }]

    def test_audio_url_change_does_not_change_hash(self):
        from shared.utils.dialogue_hash import compute_explanation_content_hash
        a = self._base_cards()
        b = [dict(c) for c in a]
        b[0] = dict(b[0])
        b[0]["lines"] = [{"display": "Hello", "audio": "Hello", "audio_url": "https://s3/x.mp3"}]
        assert compute_explanation_content_hash(a, None) == compute_explanation_content_hash(b, None)

    def test_pixi_code_change_does_not_change_hash(self):
        from shared.utils.dialogue_hash import compute_explanation_content_hash
        a = self._base_cards()
        b = [dict(c) for c in a]
        b[0] = dict(b[0])
        b[0]["pixi_code"] = "console.log('x')"
        b[0]["visual_explanation"] = {"pixi_code": "..."}
        assert compute_explanation_content_hash(a, None) == compute_explanation_content_hash(b, None)

    def test_line_text_change_changes_hash(self):
        from shared.utils.dialogue_hash import compute_explanation_content_hash
        a = self._base_cards()
        b = [dict(c) for c in a]
        b[0] = dict(b[0])
        b[0]["lines"] = [{"display": "Hello", "audio": "Hi there"}]
        assert compute_explanation_content_hash(a, None) != compute_explanation_content_hash(b, None)
