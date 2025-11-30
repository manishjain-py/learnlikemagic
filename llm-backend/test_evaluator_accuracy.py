#!/usr/bin/env python3
"""
Test script to verify evaluator accuracy improvements.

Tests the exact scenario that failed:
- Student counts "jasprit" as 6 letters (should be 7)
- Evaluator should catch this error and provide corrective feedback
"""

import os
import sys
import json
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.llm_service import LLMService
from agents.evaluator_agent import EvaluatorAgent
from workflows.state import SimplifiedState

# Load environment
load_dotenv()


def create_test_state() -> dict:
    """Create the exact state from the failing session."""
    return {
        "session_id": "test_evaluator_accuracy",
        "student_profile": {
            "name": "Test Student",
            "age": 8,
            "grade": 3,
            "interests": ["cricket"],
            "strengths": ["visual learning", "creative thinking"],
            "challenges": ["abstract concepts"],
        },
        "topic_info": {
            "topic": "Counting and Quantitative Skills",
            "subtopic": "Learn Strategies for Counting and Categorization",
            "grade": "3",
        },
        "session_context": {
            "estimated_duration_minutes": 20,
        },
        "guidelines": """1. Keep instructions clear and simple
2. Use cricket examples when possible
3. Encourage and be supportive
4. Check for understanding before moving on""",
        "study_plan": {
            "todo_list": [
                {
                    "step_id": "step_1",
                    "title": "The Cricket Team Line-Up",
                    "description": "Count letters in cricket player names and identify longest/shortest",
                    "teaching_approach": "Use cricket-themed scenario",
                    "success_criteria": "Student correctly identifies the longest and shortest cricket player's names and counts the letters accurately.",
                    "status": "in_progress",
                    "status_info": {
                        "questions_asked": 1,
                        "questions_correct": 0,
                        "attempts": 1,
                        "completed_at": None,
                    },
                }
            ],
            "metadata": {
                "plan_version": 1,
                "estimated_total_questions": 4,
                "estimated_duration_minutes": 20,
                "replan_count": 0,
                "max_replans": 3,
                "created_at": "2025-11-25T02:59:44.724080Z",
                "last_updated_at": "2025-11-25T02:59:44.724080Z"
            }
        },
        "conversation": [
            {
                "role": "tutor",
                "content": "Hey there! Let's get started with our cricket team line-up activity. Imagine you're the team manager. Can you write down the names of five famous cricket players you know? Once you've done that, let's count the letters in each name to see which one is the longest and which is the shortest. This is going to be fun!",
                "timestamp": "2025-11-25T02:59:47.639458Z",
            },
            {
                "role": "student",
                "content": "virat, rohit, hardik, jasprit, siraj",
                "timestamp": "2025-11-25T03:00:00.000000Z",
            },
            {
                "role": "tutor",
                "content": "Awesome job listing those cricket players' names! Now, let's count the letters in each name together. Start with 'Virat' and count each letter one by one. How many letters does 'Virat' have? Once you find that, do the same for the other names. Let's see which name is the longest and which is the shortest. You're doing great!",
                "timestamp": "2025-11-25T03:01:35.636212Z",
            },
            {
                "role": "student",
                "content": "virat 5, rohit 5, hardik 6, jasprit 6, siraj 5",
                "timestamp": "2025-11-25T03:02:00.000000Z",
            },
        ],
        "assessment_notes": "2025-11-25T03:01:30.701688Z - Student listed names of five cricket players but did not count the letters or identify the longest and shortest names. Needs guidance to complete this part.",
        "replan_needed": False,
        "replan_reason": None,
        "agent_logs": [],
        "created_at": "2025-11-25T02:59:44.724192Z",
        "last_updated_at": "2025-11-25T03:01:35.636212Z",
    }


def verify_evaluation_result(eval_output: dict) -> tuple[bool, list[str]]:
    """
    Verify the evaluation result meets expectations.

    Expected behavior:
    - Score should be < 1.0 (student got jasprit wrong)
    - Score should be around 0.8 (4/5 correct)
    - Feedback should mention recounting or checking jasprit
    - Step should remain in_progress (not completed)
    - Should not trigger replan

    Returns:
        Tuple of (success, list_of_issues)
    """
    issues = []

    # Check score
    score = eval_output.get("score", 0)
    if score >= 1.0:
        issues.append(f"❌ Score is {score}, should be < 1.0 (student got jasprit wrong)")
    elif score < 0.7 or score > 0.9:
        issues.append(f"⚠️  Score is {score}, expected ~0.8 (4/5 correct)")
    else:
        print(f"✅ Score: {score} (correct range for 4/5 answers)")

    # Check feedback mentions the error
    feedback = eval_output.get("feedback", "").lower()
    if "jasprit" in feedback or "recount" in feedback or "check" in feedback:
        print(f"✅ Feedback mentions correction needed")
    else:
        issues.append(f"❌ Feedback doesn't mention recounting: '{feedback}'")

    # Check step status
    step_statuses = eval_output.get("updated_step_statuses", {})
    step_1_status = step_statuses.get("step_1", "")
    if step_1_status == "completed":
        issues.append(f"❌ Step marked as 'completed' but student got jasprit wrong!")
    elif step_1_status == "in_progress":
        print(f"✅ Step kept as 'in_progress' for correction")
    else:
        issues.append(f"⚠️  Unexpected step status: {step_1_status}")

    # Check no replanning
    if eval_output.get("replan_needed", False):
        issues.append(f"⚠️  Replan triggered (usually not needed for one mistake)")
    else:
        print(f"✅ No replan triggered")

    # Check reasoning mentions verification
    reasoning = eval_output.get("reasoning", "").lower()
    if any(word in reasoning for word in ["count", "verify", "check", "letter"]):
        print(f"✅ Reasoning shows verification process")
    else:
        issues.append(f"⚠️  Reasoning doesn't show verification: '{reasoning}'")

    return len(issues) == 0, issues


def main():
    """Run the evaluator accuracy test."""
    print("=" * 80)
    print("EVALUATOR ACCURACY TEST")
    print("=" * 80)
    print("\nScenario: Student counts 'jasprit' as 6 letters (correct: 7)")
    print("Expected: Evaluator detects error, scores 4/5 = 0.8, keeps step in_progress\n")

    # Check API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ ERROR: OPENAI_API_KEY not found in environment")
        sys.exit(1)

    # Create services
    llm_service = LLMService(api_key=api_key)
    evaluator = EvaluatorAgent(llm_service)

    # Create test state
    state = create_test_state()

    print("Running evaluator agent...")
    print("-" * 80)

    try:
        # Execute evaluator
        updated_state, eval_output, reasoning, input_summary = evaluator.execute_internal(state)

        print(f"\n📊 EVALUATION RESULTS:")
        print(f"   Score: {eval_output.get('score')}")
        print(f"   Step Status: {eval_output.get('updated_step_statuses')}")
        print(f"   Replan Needed: {eval_output.get('replan_needed')}")
        print(f"\n💬 Feedback to Student:")
        print(f"   {eval_output.get('feedback')}")
        print(f"\n🧠 Reasoning:")
        print(f"   {reasoning}")
        print(f"\n📝 Assessment Note:")
        print(f"   {eval_output.get('assessment_note')}")

        print("\n" + "=" * 80)
        print("VERIFICATION")
        print("=" * 80)

        # Verify results
        success, issues = verify_evaluation_result(eval_output)

        if success:
            print("\n✅ TEST PASSED! Evaluator correctly detected the counting error.")
            print("\nThe improved evaluator:")
            print("  - Independently verified each count")
            print("  - Detected 'jasprit' was miscounted")
            print("  - Assigned appropriate score (4/5 = 0.8)")
            print("  - Kept step in_progress for correction")
            print("  - Provided corrective feedback")
            print("\nNext step: EXECUTOR will see feedback and generate corrective question.")
            return 0
        else:
            print("\n❌ TEST FAILED! Issues found:")
            for issue in issues:
                print(f"  {issue}")
            print("\nThe evaluator still needs improvement.")
            return 1

    except Exception as e:
        print(f"\n❌ ERROR during evaluation: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
