#!/usr/bin/env python3
"""
GPT-5.2 Tutor Workflow Agents Test Script

This script tests all 3 tutor workflow agents with GPT-5.2 structured outputs:
- PLANNER (high reasoning) - Strategic planning with strict schema
- EXECUTOR (none reasoning) - Fast message generation with strict schema
- EVALUATOR (medium reasoning) - Balanced evaluation with strict schema

Usage:
    # Run all agent tests:
    python scripts/test_gpt_5_2_agents.py

    # Test specific agent:
    python scripts/test_gpt_5_2_agents.py --agent planner
    python scripts/test_gpt_5_2_agents.py --agent executor
    python scripts/test_gpt_5_2_agents.py --agent evaluator

    # Test the full workflow (create session -> answer -> evaluate):
    python scripts/test_gpt_5_2_agents.py --workflow
"""

import os
import sys
import json
import time
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from shared.services.llm_service import LLMService
from tutor.agents.schemas import (
    PlannerLLMOutput, PLANNER_STRICT_SCHEMA,
    ExecutorLLMOutput, EXECUTOR_STRICT_SCHEMA,
    EvaluatorLLMOutput, EVALUATOR_STRICT_SCHEMA,
)


# =============================================================================
# Test Configuration
# =============================================================================

TEST_GUIDELINES = """
# Comparing Fractions (Grade 3)

## Learning Objectives
Students will learn to compare fractions with the same denominator by comparing numerators.

## Key Concepts
1. When fractions have the same denominator, the one with the bigger numerator is bigger
2. The denominator tells us the size of each piece
3. The numerator tells us how many pieces we have

## Teaching Approach
- Use visual models (pizza, pie, chocolate bar)
- Start with concrete examples before moving to abstract
- Encourage students to draw their own fraction models

## Common Misconceptions
- Students may think "bigger number = bigger fraction" without considering denominators
- Students may confuse numerator and denominator roles

## Success Criteria
Student correctly compares 3 pairs of fractions with like denominators and explains their reasoning.
"""

STUDENT_PROFILE = {
    "id": "test_student_1",
    "name": "Alex",
    "grade": 3,
    "interests": ["Sports", "Cricket", "Video Games"],
    "learning_style": "Visual",
    "strengths": ["Creative thinking", "Loves challenges"],
    "challenges": ["Reading long texts", "Staying focused on abstract concepts"],
}

TOPIC_INFO = {
    "topic": "Fractions",
    "subtopic": "Comparing Fractions with Like Denominators",
    "grade": 3,
}

SESSION_CONTEXT = {
    "estimated_duration_minutes": 20,
}


# =============================================================================
# Test Functions
# =============================================================================

def test_planner_agent(llm_service: LLMService):
    """Test PLANNER agent with GPT-5.2 high reasoning."""
    print("\n" + "=" * 70)
    print("TEST: PLANNER Agent (GPT-5.2, reasoning=high)")
    print("=" * 70)

    # Build the prompt (simplified version of what planner_initial.txt produces)
    prompt = f"""
You are a creative educational planner creating a personalized study plan.

# CONTEXT

## Teaching Guidelines
{TEST_GUIDELINES}

## Student Profile
- Interests: {", ".join(STUDENT_PROFILE["interests"])}
- Learning Style: {STUDENT_PROFILE["learning_style"]}
- Grade: {STUDENT_PROFILE["grade"]}
- Strengths: {", ".join(STUDENT_PROFILE["strengths"])}
- Challenges: {", ".join(STUDENT_PROFILE["challenges"])}

## Topic
- Topic: {TOPIC_INFO["topic"]}
- Subtopic: {TOPIC_INFO["subtopic"]}
- Grade Level: {TOPIC_INFO["grade"]}

## Session
- Estimated Duration: {SESSION_CONTEXT["estimated_duration_minutes"]} minutes

# YOUR TASK
Create a 3-4 step study plan that uses the student's interests to make learning engaging.
Be creative - use analogies, games, and fun scenarios!
"""

    print(f"\nCalling GPT-5.2 with reasoning=high...")
    print(f"Schema: PlannerLLMOutput (strict)")

    start_time = time.time()
    response = llm_service.call_gpt_5_2(
        prompt=prompt,
        reasoning_effort="high",
        json_schema=PLANNER_STRICT_SCHEMA,
        schema_name="PlannerOutput",
    )
    elapsed = time.time() - start_time

    print(f"\n✓ Response received in {elapsed:.2f}s")

    # Parse and validate
    output_text = response["output_text"]
    output_data = json.loads(output_text)
    parsed = PlannerLLMOutput.model_validate(output_data)

    print(f"\n📋 Study Plan Created:")
    print(f"   Reasoning: {parsed.reasoning[:150]}...")
    print(f"   Steps: {len(parsed.todo_list)}")
    for i, step in enumerate(parsed.todo_list, 1):
        print(f"\n   Step {i}: {step.title}")
        print(f"   └─ Approach: {step.teaching_approach[:80]}...")
        print(f"   └─ Success: {step.success_criteria[:60]}...")

    print(f"\n   Metadata:")
    print(f"   └─ Estimated Questions: {parsed.metadata.estimated_total_questions}")
    print(f"   └─ Duration: {parsed.metadata.estimated_duration_minutes} min")

    return parsed


def test_executor_agent(llm_service: LLMService, plan_step: dict = None):
    """Test EXECUTOR agent with GPT-5.2 no reasoning (fast)."""
    print("\n" + "=" * 70)
    print("TEST: EXECUTOR Agent (GPT-5.2, reasoning=none)")
    print("=" * 70)

    # Use provided step or default
    if plan_step is None:
        plan_step = {
            "step_id": "step_1",
            "title": "Pizza Fraction Adventure",
            "description": "Introduce fractions using pizza slices. Start with a fun story about sharing pizza.",
            "teaching_approach": "Use a cricket team sharing pizzas - if 8 players share a pizza cut into 8 slices...",
            "success_criteria": "Student correctly identifies which player has more pizza in 2 scenarios",
            "status": "in_progress",
        }

    prompt = f"""
You are a friendly tutor generating the next teaching message.

# CURRENT STEP
- Title: {plan_step["title"]}
- Description: {plan_step["description"]}
- Approach: {plan_step["teaching_approach"]}
- Success Criteria: {plan_step["success_criteria"]}

# STUDENT PROFILE
- Grade: {STUDENT_PROFILE["grade"]}
- Interests: {", ".join(STUDENT_PROFILE["interests"])}
- Learning Style: {STUDENT_PROFILE["learning_style"]}

# CONVERSATION SO FAR
(This is the first message)

# YOUR TASK
Generate an engaging opening question or explanation for this step.
Make it fun and use the student's interests!
"""

    print(f"\nCalling GPT-5.2 with reasoning=none (fast mode)...")
    print(f"Schema: ExecutorLLMOutput (strict)")

    start_time = time.time()
    response = llm_service.call_gpt_5_2(
        prompt=prompt,
        reasoning_effort="none",
        json_schema=EXECUTOR_STRICT_SCHEMA,
        schema_name="ExecutorOutput",
    )
    elapsed = time.time() - start_time

    print(f"\n✓ Response received in {elapsed:.2f}s")

    # Parse and validate
    output_text = response["output_text"]
    output_data = json.loads(output_text)
    parsed = ExecutorLLMOutput.model_validate(output_data)

    print(f"\n💬 Teaching Message Generated:")
    print(f"   Type: {parsed.meta.message_type}")
    print(f"   Difficulty: {parsed.meta.difficulty}")
    print(f"   Question #{parsed.question_number}")
    print(f"\n   Message:")
    print(f"   {parsed.message}")
    print(f"\n   Reasoning: {parsed.reasoning[:100]}...")

    return parsed


def test_evaluator_agent(llm_service: LLMService, question: str = None, answer: str = None):
    """Test EVALUATOR agent with GPT-5.2 medium reasoning."""
    print("\n" + "=" * 70)
    print("TEST: EVALUATOR Agent (GPT-5.2, reasoning=medium)")
    print("=" * 70)

    # Use provided Q&A or defaults
    if question is None:
        question = "If you have 3/8 of a pizza and I have 5/8 of the same pizza, who has more?"
    if answer is None:
        answer = "You have more because 5 is bigger than 3 and the pizzas are the same size pieces!"

    current_step = {
        "step_id": "step_1",
        "title": "Pizza Fraction Adventure",
        "status": "in_progress",
        "success_criteria": "Student correctly identifies which player has more pizza in 2 scenarios",
    }

    prompt = f"""
You are evaluating a student's response in a tutoring session.

# QUESTION ASKED
{question}

# STUDENT'S RESPONSE
{answer}

# CURRENT STEP
- Title: {current_step["title"]}
- Step ID: {current_step["step_id"]}
- Status: {current_step["status"]}
- Success Criteria: {current_step["success_criteria"]}

# STATUS INFO
- Questions asked so far: 1
- Questions correct: 0
- Total attempts: 1

# YOUR TASK
Evaluate the student's response. Determine:
1. Is it correct? Score from 0.0 to 1.0
2. Provide encouraging feedback
3. Should we update step status?
4. Is replanning needed?
5. Was it off-topic?
"""

    print(f"\nCalling GPT-5.2 with reasoning=medium...")
    print(f"Schema: EvaluatorLLMOutput (strict)")

    start_time = time.time()
    response = llm_service.call_gpt_5_2(
        prompt=prompt,
        reasoning_effort="medium",
        json_schema=EVALUATOR_STRICT_SCHEMA,
        schema_name="EvaluatorOutput",
    )
    elapsed = time.time() - start_time

    print(f"\n✓ Response received in {elapsed:.2f}s")

    # Parse and validate
    output_text = response["output_text"]
    output_data = json.loads(output_text)
    parsed = EvaluatorLLMOutput.model_validate(output_data)

    print(f"\n📊 Evaluation Result:")
    print(f"   Score: {parsed.score:.2f}")
    print(f"   Was Off-Topic: {parsed.was_off_topic}")
    print(f"   Replan Needed: {parsed.replan_needed}")
    print(f"\n   Feedback:")
    print(f"   {parsed.feedback}")
    print(f"\n   Status Updates:")
    for step_id, status in parsed.updated_step_statuses.items():
        print(f"   └─ {step_id}: {status}")
    print(f"\n   Assessment Note:")
    print(f"   {parsed.assessment_note[:100]}...")
    print(f"\n   Reasoning: {parsed.reasoning[:100]}...")

    return parsed


def test_full_workflow(llm_service: LLMService):
    """Test a complete workflow: Plan -> Execute -> Evaluate."""
    print("\n" + "=" * 70)
    print("TEST: Full Workflow (PLANNER -> EXECUTOR -> EVALUATOR)")
    print("=" * 70)

    # Step 1: Create a plan
    print("\n📝 Step 1: Creating study plan with PLANNER...")
    plan = test_planner_agent(llm_service)

    # Step 2: Generate first question using first step
    print("\n📝 Step 2: Generating first question with EXECUTOR...")
    if plan.todo_list:
        first_step = plan.todo_list[0]
        step_dict = {
            "step_id": first_step.step_id,
            "title": first_step.title,
            "description": first_step.description,
            "teaching_approach": first_step.teaching_approach,
            "success_criteria": first_step.success_criteria,
            "status": "in_progress",
        }
        message = test_executor_agent(llm_service, step_dict)
    else:
        message = test_executor_agent(llm_service)

    # Step 3: Simulate student answer and evaluate
    print("\n📝 Step 3: Evaluating student response with EVALUATOR...")
    student_answer = "I think 5/8 is more because 5 is more pieces than 3!"
    evaluation = test_evaluator_agent(
        llm_service,
        question=message.message,
        answer=student_answer,
    )

    print("\n" + "=" * 70)
    print("✅ Full workflow completed successfully!")
    print("=" * 70)
    print(f"\nSummary:")
    print(f"  Plan Steps: {len(plan.todo_list)}")
    print(f"  First Message Type: {message.meta.message_type}")
    print(f"  Evaluation Score: {evaluation.score:.2f}")
    print(f"  Replan Needed: {evaluation.replan_needed}")


def compare_speed(llm_service: LLMService):
    """Compare speed between reasoning levels."""
    print("\n" + "=" * 70)
    print("TEST: Speed Comparison (none vs medium vs high)")
    print("=" * 70)

    prompt = """
Create a simple 2-step study plan for teaching addition to a 2nd grader.
Keep it brief.
"""

    results = {}
    for level in ["none", "low", "medium", "high"]:
        print(f"\n  Testing reasoning='{level}'...")
        start = time.time()
        response = llm_service.call_gpt_5_2(
            prompt=prompt,
            reasoning_effort=level,
            json_schema=PLANNER_STRICT_SCHEMA,
            schema_name="PlannerOutput",
        )
        elapsed = time.time() - start
        results[level] = elapsed
        print(f"    ✓ {elapsed:.2f}s")

    print("\n  Summary:")
    print(f"    {'Level':<10} {'Time (s)':<10} {'Relative':<10}")
    print(f"    {'-' * 30}")
    baseline = results["none"]
    for level, elapsed in results.items():
        relative = f"{elapsed / baseline:.1f}x" if baseline > 0 else "N/A"
        print(f"    {level:<10} {elapsed:<10.2f} {relative:<10}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Test GPT-5.2 tutor workflow agents"
    )
    parser.add_argument(
        "--agent",
        choices=["planner", "executor", "evaluator"],
        help="Test specific agent only",
    )
    parser.add_argument(
        "--workflow",
        action="store_true",
        help="Test the full workflow (planner -> executor -> evaluator)",
    )
    parser.add_argument(
        "--speed",
        action="store_true",
        help="Compare speed between reasoning levels",
    )
    args = parser.parse_args()

    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Please set it or add it to your .env file")
        sys.exit(1)

    print("=" * 70)
    print("GPT-5.2 Tutor Workflow Agents Test Suite")
    print("=" * 70)
    print(f"\nInitializing LLMService...")

    llm_service = LLMService(api_key=api_key)

    print(f"\nAgent Configuration:")
    print(f"  PLANNER:   GPT-5.2, reasoning=high,   strict json_schema")
    print(f"  EXECUTOR:  GPT-5.2, reasoning=none,   strict json_schema")
    print(f"  EVALUATOR: GPT-5.2, reasoning=medium, strict json_schema")

    try:
        if args.agent == "planner":
            test_planner_agent(llm_service)
        elif args.agent == "executor":
            test_executor_agent(llm_service)
        elif args.agent == "evaluator":
            test_evaluator_agent(llm_service)
        elif args.workflow:
            test_full_workflow(llm_service)
        elif args.speed:
            compare_speed(llm_service)
        else:
            # Run all individual tests
            test_planner_agent(llm_service)
            test_executor_agent(llm_service)
            test_evaluator_agent(llm_service)

        print("\n" + "=" * 70)
        print("✅ All tests completed successfully!")
        print("=" * 70)

    except Exception as e:
        print(f"\n\n❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
