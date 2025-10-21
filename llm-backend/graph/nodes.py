"""
LangGraph node implementations for the adaptive tutor agent.
"""
import json
from typing import Dict, Any
from graph.state import (
    GraphState,
    PRESENT_SYSTEM_PROMPT,
    CHECK_SYSTEM_PROMPT,
    REMEDIATE_SYSTEM_PROMPT
)
from llm import get_llm_provider
from db import SessionLocal


# Shared LLM provider instance
llm_provider = get_llm_provider()


def present_node(state: GraphState) -> GraphState:
    """
    Present node: Compose teaching turn or pose a question using teaching guidelines.

    This node:
    1. Retrieves teaching guideline for the topic
    2. Uses LLM to compose an appropriate teaching message based on guideline
    3. Adds the message to conversation history
    """
    print(f"[Present] Step {state['step_idx']}/10")

    # Get guideline repository
    db = SessionLocal()
    try:
        from guideline_repository import TeachingGuidelineRepository
        guideline_repo = TeachingGuidelineRepository(db)

        # Get teaching guideline if not already in state
        if not state.get("teaching_guideline"):
            guideline_id = state["goal"].get("guideline_id")
            if guideline_id:
                guideline_obj = guideline_repo.get_guideline_by_id(guideline_id)
                if guideline_obj:
                    state["teaching_guideline"] = guideline_obj.guideline
                else:
                    print(f"[Present] WARNING: Guideline {guideline_id} not found")
                    state["teaching_guideline"] = "Teach this topic step by step using grade-appropriate language."
            else:
                print(f"[Present] WARNING: No guideline_id in goal")
                state["teaching_guideline"] = "Teach this topic step by step using grade-appropriate language."

        prefs = state["student"].get("prefs", {})

        # Format conversation history for context
        history_text = ""
        for entry in state["history"]:
            role = "Teacher" if entry["role"] == "teacher" else "Student"
            history_text += f"{role}: {entry['msg']}\n"

        system_prompt = PRESENT_SYSTEM_PROMPT.format(
            grade=state["student"]["grade"],
            topic=state["goal"]["topic"],
            prefs=json.dumps(prefs),
            step_idx=state["step_idx"]
        )

        user_prompt = json.dumps({
            "topic": state["goal"]["topic"],
            "grade": state["student"]["grade"],
            "prefs": prefs,
            "step_idx": state["step_idx"],
            "teaching_guideline": state["teaching_guideline"],
            "conversation_history": history_text if history_text else "(First turn - no history yet)",
            "last_grading": state.get("last_grading", {})
        })

        # Generate response
        response = llm_provider.generate(system_prompt, user_prompt)

        # Add to history
        state["history"].append({
            "role": "teacher",
            "msg": response["message"],
            "meta": {
                "hints": response.get("hints", [])
            }
        })

        print(f"[Present] Generated message: {response['message'][:60]}...")

    finally:
        db.close()

    return state


def check_node(state: GraphState) -> GraphState:
    """
    Check node: Grade the student's response.

    This node:
    1. Takes the last student reply
    2. Uses LLM to grade it
    3. Stores grading result in state
    """
    print("[Check] Grading student response...")

    # Get last student reply
    student_reply = state.get("current_student_reply", "")

    if not student_reply:
        # If no reply, look in history for last student entry
        for entry in reversed(state["history"]):
            if entry["role"] == "student":
                student_reply = entry["msg"]
                break

    # Format conversation history for context
    history_text = ""
    for entry in state["history"]:
        role = "Teacher" if entry["role"] == "teacher" else "Student"
        history_text += f"{role}: {entry['msg']}\n"

    system_prompt = CHECK_SYSTEM_PROMPT.format(
        grade=state["student"]["grade"],
        topic=state["goal"]["topic"],
        reply=student_reply
    )

    user_prompt = json.dumps({
        "topic": state["goal"]["topic"],
        "reply": student_reply,
        "expected_concepts": state["goal"]["learning_objectives"],
        "conversation_history": history_text
    })

    # Generate grading
    grading = llm_provider.generate(system_prompt, user_prompt)

    state["last_grading"] = grading

    # Debug: Print grading structure
    if 'score' in grading:
        print(f"[Check] Score: {grading['score']:.2f}, Labels: {grading.get('labels', [])}")
    else:
        print(f"[Check] WARNING: No score in grading result: {grading}")

    return state


def diagnose_node(state: GraphState) -> GraphState:
    """
    Diagnose node: Update evidence and adjust mastery score.

    This node:
    1. Extracts misconceptions from grading
    2. Updates evidence list
    3. Computes new mastery score using EMA
    """
    print("[Diagnose] Updating evidence and mastery...")

    if not state.get("last_grading"):
        return state

    grading = state["last_grading"]

    # Update evidence with new labels
    labels = grading.get("labels", [])
    state["evidence"].extend(labels)

    # Keep evidence list manageable (last 10 items)
    state["evidence"] = state["evidence"][-10:]

    # Update mastery score using EMA (α = 0.4)
    score = grading["score"]
    alpha = 0.4
    state["mastery_score"] = (1 - alpha) * state["mastery_score"] + alpha * score

    print(f"[Diagnose] Mastery: {state['mastery_score']:.2f}, Evidence: {state['evidence']}")

    return state


def remediate_node(state: GraphState) -> GraphState:
    """
    Remediate node: Provide scaffolding when student struggles.

    This node:
    1. Generates a clarifying explanation
    2. Poses a follow-up question
    3. Adds to conversation history
    """
    print("[Remediate] Providing scaffolding...")

    labels = state.get("last_grading", {}).get("labels", [])

    system_prompt = REMEDIATE_SYSTEM_PROMPT.format(
        grade=state["student"]["grade"],
        labels=json.dumps(labels)
    )

    user_prompt = json.dumps({
        "labels": labels,
        "last_score": state.get("last_grading", {}).get("score", 0),
        "topic": state["goal"]["topic"]
    })

    # Generate remediation
    response = llm_provider.generate(system_prompt, user_prompt)

    # Add explanation to history
    full_message = response["message"]
    if response.get("followup"):
        full_message += " " + response["followup"]

    state["history"].append({
        "role": "teacher",
        "msg": full_message,
        "meta": {"type": "remediation"}
    })

    print(f"[Remediate] Provided scaffolding: {response['message'][:60]}...")

    return state


def advance_node(state: GraphState) -> GraphState:
    """
    Advance node: Move to next step when student shows understanding.

    This node:
    1. Increments step index
    2. May adjust difficulty (future enhancement)
    """
    print("[Advance] Moving to next step...")

    state["step_idx"] += 1

    print(f"[Advance] Now at step {state['step_idx']}/10")

    return state


# Routing functions for conditional edges

def route_after_check(state: GraphState) -> str:
    """
    Route after Check node: decide whether to Advance or Remediate.

    Returns:
        "advance" or "remediate"
    """
    if not state.get("last_grading"):
        return "advance"

    score = state["last_grading"]["score"]
    confidence = state["last_grading"]["confidence"]

    # Advance if score >= 0.8 AND confidence >= 0.6
    if score >= 0.8 and confidence >= 0.6:
        return "advance"
    else:
        return "remediate"


def route_after_advance(state: GraphState) -> str:
    """
    Route after Advance node: decide whether to continue or END.

    Returns:
        "present" to continue, "end" to finish session
    """
    # End if step_idx >= 10 OR mastery >= 0.85
    if state["step_idx"] >= 10 or state["mastery_score"] >= 0.85:
        return "end"
    else:
        return "present"


def route_after_remediate(state: GraphState) -> str:
    """
    Route after Remediate: always go to Diagnose then Present.

    Returns:
        "diagnose"
    """
    return "diagnose"
