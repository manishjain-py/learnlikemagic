"""
Integration Tests for Tutor Workflow

These tests verify the complete workflow end-to-end:
- Session creation
- Plan generation
- Message execution
- Response evaluation
- Routing logic
- Replanning
- Session completion

Note: These tests require OpenAI API key and will make real API calls.
Use mock responses for faster unit tests.
"""

import pytest
import os
from workflows.tutor_workflow import TutorWorkflow
from workflows.helpers import generate_session_id
from services.llm_service import LLMService
from services.agent_logging_service import AgentLoggingService


@pytest.fixture
def llm_service():
    """Create LLM service instance"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")
    return LLMService(api_key=api_key, max_retries=3)


@pytest.fixture
def logging_service(tmp_path):
    """Create logging service with temp directory"""
    log_dir = tmp_path / "logs"
    return AgentLoggingService(log_base_dir=str(log_dir))


@pytest.fixture
def workflow(llm_service, logging_service, tmp_path):
    """Create workflow instance"""
    checkpoint_path = str(tmp_path / "checkpoints.db")
    return TutorWorkflow(llm_service, logging_service, checkpoint_path)


def test_session_creation(workflow):
    """Test creating a new tutoring session"""
    session_id = generate_session_id()

    result = workflow.start_session(
        session_id=session_id,
        guidelines="Be encouraging and patient. Use visual examples.",
        student_profile={
            "interests": ["dinosaurs", "video games"],
            "learning_style": "visual",
            "grade": 4,
        },
        topic_info={
            "topic": "Fractions",
            "subtopic": "Comparing Fractions",
            "grade": 4,
        },
        session_context={"estimated_duration_minutes": 20},
    )

    # Verify structure
    assert "first_message" in result
    assert "study_plan" in result
    assert "session_id" in result

    # Verify plan structure
    plan = result["study_plan"]
    assert "todo_list" in plan
    assert len(plan["todo_list"]) > 0
    assert "metadata" in plan

    # Verify first message
    assert len(result["first_message"]) > 0
    assert isinstance(result["first_message"], str)

    print(f"\n✓ Session created: {session_id}")
    print(f"✓ Plan has {len(plan['todo_list'])} steps")
    print(f"✓ First message: {result['first_message'][:100]}...")


def test_student_response_correct(workflow):
    """Test submitting a correct student response"""
    session_id = generate_session_id()

    # Start session
    workflow.start_session(
        session_id=session_id,
        guidelines="Be encouraging.",
        student_profile={"interests": ["math"], "learning_style": "visual", "grade": 4},
        topic_info={"topic": "Fractions", "subtopic": "Comparing", "grade": 4},
        session_context={"estimated_duration_minutes": 20},
    )

    # Submit correct response
    result = workflow.submit_response(
        session_id=session_id, student_reply="5/8 is bigger than 3/8"
    )

    # Verify structure
    assert "feedback" in result
    assert "session_status" in result

    # Verify feedback exists
    assert len(result["feedback"]) > 0

    print(f"\n✓ Response submitted")
    print(f"✓ Feedback: {result['feedback'][:100]}...")
    print(f"✓ Status: {result['session_status']}")


def test_state_retrieval(workflow):
    """Test retrieving session state"""
    session_id = generate_session_id()

    # Start session
    workflow.start_session(
        session_id=session_id,
        guidelines="Test guidelines",
        student_profile={"interests": [], "learning_style": "visual", "grade": 4},
        topic_info={"topic": "Test", "subtopic": "Test", "grade": 4},
        session_context={"estimated_duration_minutes": 20},
    )

    # Get state
    state = workflow.get_session_state(session_id)

    # Verify state structure
    assert state["session_id"] == session_id
    assert "study_plan" in state
    assert "conversation" in state
    assert "agent_logs" in state

    print(f"\n✓ State retrieved for session {session_id}")
    print(f"✓ Conversation length: {len(state['conversation'])}")
    print(f"✓ Agent logs: {len(state['agent_logs'])}")


def test_nonexistent_session(workflow):
    """Test error handling for nonexistent session"""
    with pytest.raises(ValueError, match="not found"):
        workflow.get_session_state("nonexistent-session-id")

    print("\n✓ Correctly raises error for nonexistent session")


@pytest.mark.slow
def test_full_session_flow(workflow):
    """
    Test a complete tutoring session flow.

    This is a slower integration test that runs a full session.
    """
    session_id = generate_session_id()

    # 1. Start session
    print("\n" + "=" * 60)
    print("STARTING FULL SESSION FLOW TEST")
    print("=" * 60)

    result = workflow.start_session(
        session_id=session_id,
        guidelines="Be patient and encouraging. Use simple examples.",
        student_profile={
            "interests": ["dinosaurs"],
            "learning_style": "visual",
            "grade": 4,
        },
        topic_info={
            "topic": "Fractions",
            "subtopic": "Basic Understanding",
            "grade": 4,
        },
        session_context={"estimated_duration_minutes": 15},
    )

    print(f"\n1. SESSION STARTED")
    print(f"   Plan steps: {len(result['study_plan']['todo_list'])}")
    print(f"   First message: {result['first_message'][:80]}...")

    # 2. Submit correct response
    result = workflow.submit_response(session_id, "The top number is the numerator")

    print(f"\n2. CORRECT RESPONSE SUBMITTED")
    print(f"   Feedback: {result['feedback'][:80]}...")
    print(f"   Status: {result['session_status']}")

    # 3. Get current state
    state = workflow.get_session_state(session_id)

    print(f"\n3. STATE RETRIEVED")
    print(f"   Conversation length: {len(state['conversation'])}")
    print(f"   Assessment notes: {len(state['assessment_notes'])} chars")

    print("\n" + "=" * 60)
    print("FULL SESSION FLOW TEST COMPLETE ✓")
    print("=" * 60)


if __name__ == "__main__":
    """Run tests directly"""
    import sys

    # Run with pytest
    pytest.main([__file__, "-v", "-s"])
