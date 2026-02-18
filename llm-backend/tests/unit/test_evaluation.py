"""Unit tests for evaluation module — Evaluator, StudentSimulator, SessionRunner, ReportGenerator, Config."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime

from evaluation.config import EvalConfig, RUNS_DIR, PERSONAS_DIR
from evaluation.evaluator import ConversationEvaluator, EVALUATION_DIMENSIONS, ROOT_CAUSE_CATEGORIES
from evaluation.student_simulator import StudentSimulator
from evaluation.session_runner import SessionRunner
from evaluation.report_generator import ReportGenerator, _score_bar, _root_cause_suggestion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> EvalConfig:
    defaults = dict(
        openai_api_key="test-key-fake",
        anthropic_api_key="test-key-fake",
        topic_id="guideline-1",
        max_turns=5,
        eval_llm_provider="openai",
    )
    defaults.update(overrides)
    return EvalConfig(**defaults)


def _make_persona() -> dict:
    return {
        "persona_id": "average_student",
        "name": "Priya",
        "age": 8,
        "grade": 3,
        "personality_traits": ["Curious", "Sometimes distracted"],
        "common_mistakes": ["Forgets to carry", "Reverses numerator and denominator"],
        "response_style": {
            "max_words": 30,
            "language": "simple English",
            "examples": ["Umm... is it 5?", "Oh wait, I know this!"],
        },
        "behavioral_notes": ["Gets excited about correct answers", "Needs encouragement"],
        "correct_answer_probability": 0.6,
    }


def _make_conversation() -> list[dict]:
    return [
        {"role": "tutor", "content": "Hi! Let's learn about fractions.", "turn": 0},
        {"role": "student", "content": "Ok!", "turn": 1},
        {"role": "tutor", "content": "A fraction is a part of a whole. Like 1/2 of a pizza.", "turn": 1},
        {"role": "student", "content": "So 1/2 means one out of two pieces?", "turn": 2},
        {"role": "tutor", "content": "Exactly! Great thinking.", "turn": 2},
    ]


def _make_evaluation() -> dict:
    return {
        "scores": {
            "responsiveness": 8,
            "explanation_quality": 7,
            "emotional_attunement": 6,
            "pacing": 9,
            "authenticity": 7,
        },
        "dimension_analysis": {
            "responsiveness": "Good adaptation to student signals.",
            "explanation_quality": "Clear explanations with examples.",
            "emotional_attunement": "Warm but could be more varied.",
            "pacing": "Excellent pace calibration.",
            "authenticity": "Natural conversational style.",
        },
        "problems": [
            {
                "title": "Generic praise",
                "turns": [2],
                "description": "Tutor used generic praise",
                "quote": "Exactly! Great thinking.",
                "severity": "minor",
                "root_cause": "prompt_quality",
            },
        ],
        "summary": "Good session overall with minor issues.",
    }


# ---------------------------------------------------------------------------
# Tests — EvalConfig
# ---------------------------------------------------------------------------

class TestEvalConfig:
    def test_defaults(self):
        config = _make_config()
        assert config.server_host == "localhost"
        assert config.server_port == 8000
        assert config.max_turns == 5
        assert config.simulator_model == "gpt-4o"

    def test_base_url(self):
        config = _make_config(server_host="myhost", server_port=9000)
        assert config.base_url == "http://myhost:9000"

    def test_ws_url(self):
        config = _make_config()
        assert config.ws_url == "ws://localhost:8000"

    def test_health_url(self):
        config = _make_config()
        assert config.health_url == "http://localhost:8000/health/db"

    def test_tutor_model_label(self):
        config = _make_config(tutor_llm_provider="openai")
        assert config.tutor_model_label == "GPT-5.2"

        config2 = _make_config(tutor_llm_provider="anthropic")
        assert config2.tutor_model_label == "Claude Opus 4.6"

    def test_evaluator_model_label(self):
        config = _make_config(eval_llm_provider="openai")
        assert "gpt" in config.evaluator_model_label.lower() or "5.2" in config.evaluator_model_label

        config2 = _make_config(eval_llm_provider="anthropic")
        assert "Claude" in config2.evaluator_model_label

    def test_to_dict_excludes_keys(self):
        config = _make_config()
        d = config.to_dict()
        assert "openai_api_key" not in d
        assert "anthropic_api_key" not in d
        assert "topic_id" in d

    def test_load_persona(self):
        config = _make_config(persona_file="test.json")
        persona_data = {"persona_id": "test", "name": "Test"}
        with patch("builtins.open", mock_open(read_data=json.dumps(persona_data))):
            result = config.load_persona()
        assert result["persona_id"] == "test"


# ---------------------------------------------------------------------------
# Tests — ConversationEvaluator
# ---------------------------------------------------------------------------

class TestConversationEvaluator:
    def test_evaluation_dimensions_defined(self):
        assert len(EVALUATION_DIMENSIONS) == 5
        assert "responsiveness" in EVALUATION_DIMENSIONS
        assert "pacing" in EVALUATION_DIMENSIONS

    def test_root_cause_categories_defined(self):
        assert "missed_student_signal" in ROOT_CAUSE_CATEGORIES
        assert "prompt_quality" in ROOT_CAUSE_CATEGORIES

    @patch("evaluation.evaluator.OpenAI")
    def test_format_transcript(self, mock_openai_cls):
        config = _make_config()
        evaluator = ConversationEvaluator(config)

        conversation = _make_conversation()
        transcript = evaluator._format_transcript(conversation)

        assert "TUTOR" in transcript
        assert "STUDENT" in transcript
        assert "[Turn 0]" in transcript

    @patch("evaluation.evaluator.OpenAI")
    def test_build_user_message_basic(self, mock_openai_cls):
        config = _make_config()
        evaluator = ConversationEvaluator(config)

        msg = evaluator._build_user_message(_make_conversation())
        assert "CONVERSATION TRANSCRIPT" in msg
        assert "evaluate this tutoring conversation" in msg.lower()

    @patch("evaluation.evaluator.OpenAI")
    def test_build_user_message_with_persona(self, mock_openai_cls):
        config = _make_config()
        evaluator = ConversationEvaluator(config)

        persona = _make_persona()
        msg = evaluator._build_user_message(_make_conversation(), persona=persona)
        assert "STUDENT PERSONA" in msg
        assert "Priya" in msg
        assert "Curious" in msg

    @patch("evaluation.evaluator.OpenAI")
    def test_build_user_message_with_topic(self, mock_openai_cls):
        config = _make_config()
        evaluator = ConversationEvaluator(config)

        topic_info = {
            "topic_name": "Fractions",
            "grade_level": 3,
            "guidelines": {
                "learning_objectives": ["Understand fractions"],
                "common_misconceptions": ["Bigger denominator = bigger fraction"],
            },
        }
        msg = evaluator._build_user_message(_make_conversation(), topic_info=topic_info)
        assert "TOPIC CONTEXT" in msg
        assert "Fractions" in msg

    @patch("evaluation.evaluator.OpenAI")
    def test_build_user_message_with_persona_specific_behaviors(self, mock_openai_cls):
        config = _make_config()
        evaluator = ConversationEvaluator(config)

        persona = _make_persona()
        persona["persona_specific_behaviors"] = {
            "off_topic_probability": 0.3,
            "question_probability": 0.5,
        }
        msg = evaluator._build_user_message(_make_conversation(), persona=persona)
        assert "Behavioral tendencies" in msg

    @patch("evaluation.evaluator.OpenAI")
    def test_evaluate_openai(self, mock_openai_cls):
        config = _make_config()
        evaluator = ConversationEvaluator(config)

        mock_response = MagicMock()
        mock_response.output_text = json.dumps(_make_evaluation())
        evaluator.client.responses.create.return_value = mock_response

        result = evaluator.evaluate(_make_conversation())
        assert "scores" in result
        assert result["scores"]["responsiveness"] == 8


# ---------------------------------------------------------------------------
# Tests — StudentSimulator
# ---------------------------------------------------------------------------

class TestStudentSimulator:
    @patch("evaluation.student_simulator.OpenAI")
    def test_init(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        sim = StudentSimulator(config, persona)

        assert sim.correct_prob == 0.6
        assert sim.turn_count == 0
        assert "Priya" in sim.system_prompt

    @patch("evaluation.student_simulator.OpenAI")
    def test_build_system_prompt(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        sim = StudentSimulator(config, persona)

        prompt = sim.system_prompt
        assert "Priya" in prompt
        assert "Curious" in prompt
        assert "CRITICAL RULES" in prompt
        assert "TURN DIRECTIVE" in prompt

    @patch("evaluation.student_simulator.OpenAI")
    def test_build_system_prompt_with_persona_behaviors(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        persona["persona_specific_behaviors"] = {"off_topic_probability": 0.2}
        sim = StudentSimulator(config, persona)

        assert "PERSONA-SPECIFIC" in sim.system_prompt

    @patch("evaluation.student_simulator.OpenAI")
    def test_should_answer_correctly_uses_probability(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        persona["correct_answer_probability"] = 1.0
        sim = StudentSimulator(config, persona)

        assert sim._should_answer_correctly() is True

    @patch("evaluation.student_simulator.OpenAI")
    def test_should_answer_correctly_zero_probability(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        persona["correct_answer_probability"] = 0.0
        sim = StudentSimulator(config, persona)

        assert sim._should_answer_correctly() is False

    @patch("evaluation.student_simulator.OpenAI")
    def test_get_turn_directive_correct(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        sim = StudentSimulator(config, persona)

        directive = sim._get_turn_directive(should_be_correct=True)
        assert "ANSWER CORRECTLY" in directive

    @patch("evaluation.student_simulator.OpenAI")
    def test_get_turn_directive_incorrect(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        sim = StudentSimulator(config, persona)

        directive = sim._get_turn_directive(should_be_correct=False)
        assert "ANSWER INCORRECTLY" in directive

    @patch("evaluation.student_simulator.OpenAI")
    def test_generate_response_openai(self, mock_openai_cls):
        config = _make_config()
        persona = _make_persona()
        sim = StudentSimulator(config, persona)

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "I think it's 3!"
        sim.client.chat.completions.create.return_value = mock_resp

        conversation = [{"role": "tutor", "content": "What is 1+2?"}]
        result = sim.generate_response(conversation)

        assert result == "I think it's 3!"
        assert sim.turn_count == 1
        assert len(sim.turn_decisions) == 1


# ---------------------------------------------------------------------------
# Tests — SessionRunner
# ---------------------------------------------------------------------------

class TestSessionRunner:
    def test_init(self, tmp_path):
        config = _make_config()
        sim = MagicMock()
        runner = SessionRunner(config, sim, tmp_path)

        assert runner.conversation == []
        assert runner.session_id is None

    def test_log(self, tmp_path):
        config = _make_config()
        sim = MagicMock()
        runner = SessionRunner(config, sim, tmp_path)

        runner._log("test message")
        runner._log_file.flush()

        log_content = (tmp_path / "run.log").read_text()
        assert "test message" in log_content

    def test_stop_server_skips_in_skip_mode(self, tmp_path):
        config = _make_config()
        sim = MagicMock()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        runner.stop_server()  # should not raise

    def test_cleanup(self, tmp_path):
        config = _make_config()
        sim = MagicMock()
        runner = SessionRunner(config, sim, tmp_path)
        runner.cleanup()

        assert runner._log_file.closed

    @patch("evaluation.session_runner.httpx.Client")
    def test_start_server_skipped_healthy(self, mock_httpx_cls, tmp_path):
        config = _make_config()
        sim = MagicMock()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get.return_value = mock_resp

        runner.start_server()  # should not raise

    @patch("evaluation.session_runner.httpx.Client")
    def test_start_server_skipped_unhealthy(self, mock_httpx_cls, tmp_path):
        import httpx

        config = _make_config()
        sim = MagicMock()
        runner = SessionRunner(config, sim, tmp_path, skip_server_management=True)

        mock_client = MagicMock()
        mock_httpx_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_httpx_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("nope")

        with pytest.raises(RuntimeError, match="not reachable"):
            runner.start_server()


# ---------------------------------------------------------------------------
# Tests — ReportGenerator
# ---------------------------------------------------------------------------

class TestReportGenerator:
    def test_save_config(self, tmp_path):
        config = _make_config()
        gen = ReportGenerator(tmp_path, config)

        gen.save_config()
        data = json.loads((tmp_path / "config.json").read_text())
        assert "topic_id" in data
        assert "started_at" in data

    def test_save_evaluation_json(self, tmp_path):
        config = _make_config()
        gen = ReportGenerator(tmp_path, config)

        gen.save_evaluation_json(_make_evaluation())
        data = json.loads((tmp_path / "evaluation.json").read_text())
        assert "avg_score" in data
        assert data["avg_score"] == 7.4

    def test_save_conversation_md(self, tmp_path):
        config = _make_config()
        gen = ReportGenerator(tmp_path, config)

        gen.save_conversation_md(_make_conversation())
        text = (tmp_path / "conversation.md").read_text()
        assert "Conversation Transcript" in text
        assert "TUTOR" in text
        assert "STUDENT" in text

    def test_save_conversation_md_with_persona(self, tmp_path):
        config = _make_config()
        persona = _make_persona()
        gen = ReportGenerator(tmp_path, config, persona=persona)

        gen.save_conversation_md(_make_conversation())
        text = (tmp_path / "conversation.md").read_text()
        assert "Priya" in text

    def test_save_conversation_json(self, tmp_path):
        config = _make_config()
        gen = ReportGenerator(tmp_path, config)

        gen.save_conversation_json(_make_conversation(), metadata={"session_id": "s1"})
        data = json.loads((tmp_path / "conversation.json").read_text())
        assert data["message_count"] == 5
        assert data["session_metadata"]["session_id"] == "s1"

    def test_save_review(self, tmp_path):
        config = _make_config()
        gen = ReportGenerator(tmp_path, config)

        gen.save_review(_make_evaluation())
        text = (tmp_path / "review.md").read_text()
        assert "Evaluation Review" in text
        assert "Responsiveness" in text
        assert "7.4" in text

    def test_save_problems(self, tmp_path):
        config = _make_config()
        gen = ReportGenerator(tmp_path, config)

        gen.save_problems(_make_evaluation())
        text = (tmp_path / "problems.md").read_text()
        assert "Identified Problems" in text
        assert "Generic praise" in text
        assert "prompt_quality" in text

    def test_save_problems_empty(self, tmp_path):
        config = _make_config()
        gen = ReportGenerator(tmp_path, config)

        gen.save_problems({"problems": []})
        text = (tmp_path / "problems.md").read_text()
        assert "No problems identified" in text


class TestReportHelpers:
    def test_score_bar(self):
        assert _score_bar(7) == "#######..."
        assert _score_bar(10) == "##########"
        assert _score_bar(0) == ".........."

    def test_root_cause_suggestion_known(self):
        result = _root_cause_suggestion("prompt_quality")
        assert "prompts" in result.lower()

    def test_root_cause_suggestion_unknown(self):
        result = _root_cause_suggestion("unknown_cause")
        assert result == ""
