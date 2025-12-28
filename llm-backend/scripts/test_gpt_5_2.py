#!/usr/bin/env python3
"""
GPT-5.2 Test Script

This script tests GPT-5.2 with structured outputs using the OpenAI Responses API.

Key differences from GPT-5.1:
- Default reasoning effort is "none" (GPT-5.1 defaults to "low")
- New "xhigh" reasoning effort level for maximum reasoning
- Improved structured output handling with json_schema
- Better token efficiency and cleaner formatting
- New compaction feature for long context management

Usage:
    python scripts/test_gpt_5_2.py

    # With reasoning effort:
    python scripts/test_gpt_5_2.py --reasoning medium

    # Test all reasoning levels:
    python scripts/test_gpt_5_2.py --test-all-reasoning
"""

import os
import sys
import json
import time
import argparse
from typing import Literal, Optional
from pydantic import BaseModel, Field

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI


# =============================================================================
# Pydantic Models for Structured Output
# =============================================================================

class MathStep(BaseModel):
    """A single step in a math solution."""
    explanation: str = Field(description="Explanation of this step")
    output: str = Field(description="The mathematical output of this step")


class MathSolution(BaseModel):
    """Complete math problem solution."""
    steps: list[MathStep] = Field(description="List of solution steps")
    final_answer: str = Field(description="The final answer")


class TeachingStep(BaseModel):
    """A single step in a teaching plan."""
    step_number: int = Field(description="Step number in sequence")
    title: str = Field(description="Title of this teaching step")
    description: str = Field(description="What to teach in this step")
    activity_type: str = Field(description="Type of activity: explain, demonstrate, practice, or discuss")


class TutorPlan(BaseModel):
    """A teaching plan for a topic."""
    topic: str = Field(description="The topic being taught")
    learning_objectives: list[str] = Field(description="What the student will learn")
    teaching_steps: list[TeachingStep] = Field(description="Steps to teach the topic")
    assessment_questions: list[str] = Field(description="Questions to check understanding")


class EvaluationResult(BaseModel):
    """Evaluation of a student's response."""
    score: float = Field(ge=0.0, le=1.0, description="Score from 0.0 to 1.0")
    feedback: str = Field(description="Feedback for the student")
    is_correct: bool = Field(description="Whether the answer is correct")
    misconceptions: list[str] = Field(default=[], description="Any misconceptions detected")
    next_action: Literal["continue", "retry", "replan"] = Field(description="What to do next")


# =============================================================================
# GPT-5.2 Client Wrapper
# =============================================================================

class GPT52Client:
    """
    Client for GPT-5.2 with structured output support.

    This client uses the Responses API which is required for GPT-5.x models.
    It supports structured outputs via json_schema in the text.format parameter.
    """

    MODEL = "gpt-5.2"
    MODEL_SNAPSHOT = "gpt-5.2-2025-12-11"  # Latest stable snapshot

    REASONING_LEVELS = ["none", "low", "medium", "high", "xhigh"]

    def __init__(self, api_key: Optional[str] = None, timeout: int = 120):
        """
        Initialize the GPT-5.2 client.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            timeout: Request timeout in seconds
        """
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.timeout = timeout

    def call(
        self,
        prompt: str,
        reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "none",
        schema: Optional[dict] = None,
        schema_name: str = "response",
        strict: bool = True,
    ) -> dict:
        """
        Call GPT-5.2 with optional structured output.

        Args:
            prompt: The input prompt
            reasoning_effort: How much thinking effort to use
                - "none": Fastest, no chain-of-thought (default in 5.2)
                - "low": Light reasoning
                - "medium": Moderate reasoning
                - "high": Heavy reasoning
                - "xhigh": Maximum reasoning (new in 5.2)
            schema: JSON schema for structured output (optional)
            schema_name: Name for the schema (for logging)
            strict: Whether to enforce strict schema adherence

        Returns:
            Dict with:
                - output_text: The response text (JSON if schema provided)
                - reasoning: The reasoning process (if available)
                - usage: Token usage information
                - model: Model used
        """
        kwargs = {
            "model": self.MODEL,
            "input": prompt,
            "timeout": self.timeout,
        }

        # Add reasoning if not "none"
        if reasoning_effort != "none":
            kwargs["reasoning"] = {"effort": reasoning_effort}

        # Add structured output format if schema provided
        if schema:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": strict,
                }
            }

        start_time = time.time()
        response = self.client.responses.create(**kwargs)
        elapsed = time.time() - start_time

        result = {
            "output_text": response.output_text,
            "reasoning": getattr(response, "reasoning", None),
            "model": self.MODEL,
            "elapsed_seconds": round(elapsed, 2),
        }

        # Add usage if available
        if hasattr(response, "usage"):
            result["usage"] = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }

        return result

    @staticmethod
    def _make_schema_strict(schema: dict) -> dict:
        """
        Transform a JSON schema to meet OpenAI's strict mode requirements.

        OpenAI's structured output with strict=true requires:
        1. All objects must have additionalProperties: false
        2. All properties must be in the required array
        3. $defs references must also be transformed
        4. $ref cannot have sibling keywords (like description)

        Args:
            schema: Original JSON schema from Pydantic

        Returns:
            Transformed schema meeting strict requirements
        """
        def transform(obj: dict) -> dict:
            if not isinstance(obj, dict):
                return obj

            # If this object has a $ref, remove sibling keywords
            # OpenAI requires $ref to be alone (no description, title, etc.)
            if "$ref" in obj:
                return {"$ref": obj["$ref"]}

            result = {}
            for key, value in obj.items():
                if key == "$defs":
                    # Transform all definitions
                    result[key] = {k: transform(v) for k, v in value.items()}
                elif isinstance(value, dict):
                    result[key] = transform(value)
                elif isinstance(value, list):
                    result[key] = [transform(item) if isinstance(item, dict) else item for item in value]
                else:
                    result[key] = value

            # If this is an object type, add strict requirements
            if result.get("type") == "object" and "properties" in result:
                result["additionalProperties"] = False
                # All properties must be required in strict mode
                result["required"] = list(result["properties"].keys())

            return result

        return transform(schema)

    def call_with_pydantic(
        self,
        prompt: str,
        response_model: type[BaseModel],
        reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"] = "none",
    ) -> tuple[BaseModel, dict]:
        """
        Call GPT-5.2 with a Pydantic model for structured output.

        Args:
            prompt: The input prompt
            response_model: Pydantic model class defining the output schema
            reasoning_effort: Reasoning effort level

        Returns:
            Tuple of (parsed Pydantic model instance, raw response dict)
        """
        # Generate JSON schema from Pydantic model
        schema = response_model.model_json_schema()

        # Transform schema to meet OpenAI's strict mode requirements
        schema = self._make_schema_strict(schema)

        # Call the API
        response = self.call(
            prompt=prompt,
            reasoning_effort=reasoning_effort,
            schema=schema,
            schema_name=response_model.__name__,
        )

        # Parse the output into the Pydantic model
        output_data = json.loads(response["output_text"])
        parsed = response_model.model_validate(output_data)

        return parsed, response


# =============================================================================
# Test Functions
# =============================================================================

def test_basic_call(client: GPT52Client):
    """Test a basic GPT-5.2 call without structured output."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic Call (no structured output)")
    print("=" * 60)

    prompt = "Explain the concept of photosynthesis in 2-3 sentences."

    result = client.call(prompt, reasoning_effort="none")

    print(f"\nPrompt: {prompt}")
    print(f"\nResponse: {result['output_text']}")
    print(f"\nElapsed: {result['elapsed_seconds']}s")
    if "usage" in result:
        print(f"Tokens: {result['usage']}")


def test_structured_output_raw_schema(client: GPT52Client):
    """Test structured output with a raw JSON schema."""
    print("\n" + "=" * 60)
    print("TEST 2: Structured Output (raw JSON schema)")
    print("=" * 60)

    prompt = "Solve the equation: 3x + 5 = 20. Show your work step by step."

    schema = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "explanation": {"type": "string"},
                        "output": {"type": "string"}
                    },
                    "required": ["explanation", "output"],
                    "additionalProperties": False
                }
            },
            "final_answer": {"type": "string"}
        },
        "required": ["steps", "final_answer"],
        "additionalProperties": False
    }

    result = client.call(
        prompt=prompt,
        reasoning_effort="low",
        schema=schema,
        schema_name="math_solution",
    )

    print(f"\nPrompt: {prompt}")
    print(f"\nRaw Response: {result['output_text']}")

    # Parse and display nicely
    data = json.loads(result["output_text"])
    print("\nParsed Solution:")
    for i, step in enumerate(data["steps"], 1):
        print(f"  Step {i}: {step['explanation']}")
        print(f"          → {step['output']}")
    print(f"  Final Answer: {data['final_answer']}")

    print(f"\nElapsed: {result['elapsed_seconds']}s")


def test_structured_output_pydantic(client: GPT52Client):
    """Test structured output with Pydantic model."""
    print("\n" + "=" * 60)
    print("TEST 3: Structured Output (Pydantic model)")
    print("=" * 60)

    prompt = """
    Create a brief teaching plan for teaching fractions to a 4th grade student.
    Include 2-3 learning objectives, 3-4 teaching steps, and 2 assessment questions.
    """

    plan, response = client.call_with_pydantic(
        prompt=prompt,
        response_model=TutorPlan,
        reasoning_effort="medium",
    )

    print(f"\nPrompt: {prompt.strip()}")
    print(f"\nParsed TutorPlan:")
    print(f"  Topic: {plan.topic}")
    print(f"  Learning Objectives:")
    for obj in plan.learning_objectives:
        print(f"    - {obj}")
    print(f"  Teaching Steps:")
    for step in plan.teaching_steps:
        print(f"    {step.step_number}. [{step.activity_type}] {step.title}")
        print(f"       {step.description}")
    print(f"  Assessment Questions:")
    for q in plan.assessment_questions:
        print(f"    - {q}")

    print(f"\nElapsed: {response['elapsed_seconds']}s")


def test_evaluation_structured_output(client: GPT52Client):
    """Test evaluation-style structured output similar to your evaluator agent."""
    print("\n" + "=" * 60)
    print("TEST 4: Evaluation Structured Output")
    print("=" * 60)

    prompt = """
    You are evaluating a student's answer in a tutoring session.

    Question: What is 3/4 + 1/4?
    Student's answer: "I think it's 4/8 because you add the tops and bottoms"
    Correct answer: 4/4 or 1 (you add the numerators, keep the denominator)

    Evaluate the student's response and provide feedback.
    """

    result, response = client.call_with_pydantic(
        prompt=prompt,
        response_model=EvaluationResult,
        reasoning_effort="high",
    )

    print(f"\nEvaluation Result:")
    print(f"  Score: {result.score}")
    print(f"  Is Correct: {result.is_correct}")
    print(f"  Feedback: {result.feedback}")
    if result.misconceptions:
        print(f"  Misconceptions:")
        for m in result.misconceptions:
            print(f"    - {m}")
    print(f"  Next Action: {result.next_action}")

    print(f"\nElapsed: {response['elapsed_seconds']}s")
    if response.get("reasoning"):
        print(f"\nReasoning summary available: {bool(response['reasoning'])}")


def test_reasoning_levels(client: GPT52Client):
    """Compare different reasoning effort levels."""
    print("\n" + "=" * 60)
    print("TEST 5: Comparing Reasoning Levels")
    print("=" * 60)

    prompt = """
    A student is learning about equivalent fractions. They said:
    "1/2 is the same as 2/4 because you multiply by 2"

    Is this explanation correct? If not, what's the misconception?
    Respond with: {"is_correct": bool, "explanation": str}
    """

    schema = {
        "type": "object",
        "properties": {
            "is_correct": {"type": "boolean"},
            "explanation": {"type": "string"}
        },
        "required": ["is_correct", "explanation"],
        "additionalProperties": False
    }

    results = {}
    for level in ["none", "low", "medium", "high"]:
        print(f"\n  Testing reasoning_effort='{level}'...")
        result = client.call(
            prompt=prompt,
            reasoning_effort=level,
            schema=schema,
            schema_name="fraction_check",
        )
        results[level] = result

        data = json.loads(result["output_text"])
        print(f"    Time: {result['elapsed_seconds']}s")
        print(f"    Is Correct: {data['is_correct']}")
        print(f"    Explanation: {data['explanation'][:100]}...")

    print("\n  Summary:")
    print(f"    {'Level':<8} {'Time (s)':<10} {'Correct?'}")
    print(f"    {'-'*30}")
    for level, result in results.items():
        data = json.loads(result["output_text"])
        print(f"    {level:<8} {result['elapsed_seconds']:<10} {data['is_correct']}")


def test_comparison_with_current_implementation(client: GPT52Client):
    """
    Test that mimics how your current LLMService uses GPT-5.1.
    This helps understand the migration path from GPT-5.1 to GPT-5.2.
    """
    print("\n" + "=" * 60)
    print("TEST 6: Comparison with Current Implementation Pattern")
    print("=" * 60)

    # This mimics the pattern in your call_gpt_5_1 method
    prompt = """
    You are an executor agent generating a teaching message.

    Topic: Adding fractions with like denominators
    Current step: Introduction
    Student profile: 4th grade, visual learner

    Generate a teaching question to start the lesson.

    Respond in JSON:
    {
        "message": "The teaching message to show the student",
        "interaction_type": "question" | "explanation" | "example",
        "expected_understanding_level": "basic" | "intermediate" | "advanced"
    }
    """

    schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "interaction_type": {
                "type": "string",
                "enum": ["question", "explanation", "example"]
            },
            "expected_understanding_level": {
                "type": "string",
                "enum": ["basic", "intermediate", "advanced"]
            }
        },
        "required": ["message", "interaction_type", "expected_understanding_level"],
        "additionalProperties": False
    }

    # GPT-5.2 equivalent of your current GPT-5.1 call
    # Note: In GPT-5.2, you might want to start with reasoning="none" for speed
    # and only increase if quality isn't sufficient

    print("\n  Current pattern (GPT-5.1 with low reasoning):")
    result_low = client.call(
        prompt=prompt,
        reasoning_effort="low",
        schema=schema,
        schema_name="executor_output",
    )
    data_low = json.loads(result_low["output_text"])
    print(f"    Time: {result_low['elapsed_seconds']}s")
    print(f"    Message: {data_low['message'][:80]}...")

    print("\n  New pattern (GPT-5.2 with no reasoning - faster):")
    result_none = client.call(
        prompt=prompt,
        reasoning_effort="none",
        schema=schema,
        schema_name="executor_output",
    )
    data_none = json.loads(result_none["output_text"])
    print(f"    Time: {result_none['elapsed_seconds']}s")
    print(f"    Message: {data_none['message'][:80]}...")

    speedup = result_low["elapsed_seconds"] / result_none["elapsed_seconds"] if result_none["elapsed_seconds"] > 0 else 0
    print(f"\n  Speedup with 'none' reasoning: {speedup:.1f}x faster")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Test GPT-5.2 with structured outputs")
    parser.add_argument("--reasoning", choices=["none", "low", "medium", "high", "xhigh"],
                        default="low", help="Default reasoning effort level")
    parser.add_argument("--test-all-reasoning", action="store_true",
                        help="Run test comparing all reasoning levels")
    parser.add_argument("--test", type=int, choices=[1, 2, 3, 4, 5, 6],
                        help="Run specific test only (1-6)")
    args = parser.parse_args()

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Please set it or add it to your .env file")
        sys.exit(1)

    print("=" * 60)
    print("GPT-5.2 Structured Output Test Suite")
    print("=" * 60)
    print(f"\nInitializing GPT-5.2 client...")
    print(f"Model: gpt-5.2")
    print(f"Default reasoning: {args.reasoning}")

    client = GPT52Client()

    tests = [
        (1, test_basic_call),
        (2, test_structured_output_raw_schema),
        (3, test_structured_output_pydantic),
        (4, test_evaluation_structured_output),
        (5, test_reasoning_levels),
        (6, test_comparison_with_current_implementation),
    ]

    try:
        if args.test:
            # Run specific test
            for num, func in tests:
                if num == args.test:
                    func(client)
                    break
        elif args.test_all_reasoning:
            test_reasoning_levels(client)
        else:
            # Run all tests
            for num, func in tests:
                func(client)

        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n\nError during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
