"""
FastAPI main application for Adaptive Tutor Agent.
"""
import json
import uuid
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session as DBSession

from models import (
    CreateSessionRequest,
    CreateSessionResponse,
    StepRequest,
    StepResponse,
    SummaryResponse,
    TutorState,
    CurriculumResponse
)
from database import get_db, get_db_manager
from db import create_session_record, update_session_state, get_session_by_id, log_event, get_session_events
from graph.build_graph import get_graph
from graph.state import tutor_state_to_graph_state, graph_state_to_tutor_state
from guideline_repository import TeachingGuidelineRepository

# Create FastAPI app
app = FastAPI(
    title="Adaptive Tutor API",
    description="LangGraph-based adaptive tutoring system with RAG",
    version="0.1.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Adaptive Tutor API",
        "version": "0.1.0"
    }


@app.get("/health/db")
def database_health():
    """Database health check endpoint."""
    db_manager = get_db_manager()
    is_healthy = db_manager.health_check()

    if is_healthy:
        return {
            "status": "ok",
            "database": "connected"
        }
    else:
        raise HTTPException(status_code=503, detail="Database connection failed")


@app.get("/curriculum", response_model=CurriculumResponse)
def get_curriculum(
    country: str,
    board: str,
    grade: int,
    subject: str = None,
    topic: str = None,
    db: DBSession = Depends(get_db)
):
    """
    Discover available curriculum (subjects, topics, subtopics).

    Query Parameters:
    - country: Country name (e.g., "India")
    - board: Education board (e.g., "CBSE")
    - grade: Grade level (e.g., 3)
    - subject (optional): Filter by subject (returns topics)
    - topic (optional): Filter by topic (returns subtopics, requires subject)

    Returns:
    - If only country/board/grade provided: list of subjects
    - If subject provided: list of topics
    - If subject + topic provided: list of subtopics with guideline IDs
    """
    try:
        repo = TeachingGuidelineRepository(db)

        # Case 1: Get subtopics (subject + topic provided)
        if subject and topic:
            subtopics = repo.get_subtopics(country, board, grade, subject, topic)
            return CurriculumResponse(subtopics=subtopics)

        # Case 2: Get topics (only subject provided)
        elif subject:
            topics = repo.get_topics(country, board, grade, subject)
            return CurriculumResponse(topics=topics)

        # Case 3: Get subjects (only country/board/grade provided)
        else:
            subjects = repo.get_subjects(country, board, grade)
            return CurriculumResponse(subjects=subjects)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching curriculum: {str(e)}")


@app.post("/sessions", response_model=CreateSessionResponse)
def create_session(request: CreateSessionRequest, db: DBSession = Depends(get_db)):
    """
    Create a new learning session.

    This endpoint:
    1. Validates that guideline_id exists
    2. Creates a new session ID
    3. Initializes TutorState
    4. Runs the Present node to generate first turn
    5. Persists state to database
    6. Returns session ID and first turn
    """
    try:
        # Validate guideline_id
        if not request.goal.guideline_id:
            raise HTTPException(status_code=400, detail="guideline_id is required in goal")

        repo = TeachingGuidelineRepository(db)
        guideline = repo.get_guideline_by_id(request.goal.guideline_id)
        if not guideline:
            raise HTTPException(status_code=404, detail=f"Guideline {request.goal.guideline_id} not found")

        # Generate session ID
        session_id = str(uuid.uuid4())

        # Initialize TutorState
        tutor_state = TutorState(
            session_id=session_id,
            student=request.student,
            goal=request.goal,
            step_idx=0,
            history=[],
            evidence=[],
            mastery_score=0.0
        )

        # Convert to GraphState
        graph_state = tutor_state_to_graph_state(tutor_state)

        # Get graph and run Present node only
        graph = get_graph()

        # Execute just the present node to get first turn
        from graph.nodes import present_node
        updated_state = present_node(graph_state)

        # Convert back to TutorState
        tutor_state = graph_state_to_tutor_state(updated_state)

        # Persist to database
        create_session_record(
            db=db,
            session_id=session_id,
            state_json=tutor_state.model_dump_json(),
            student_json=request.student.model_dump_json(),
            goal_json=request.goal.model_dump_json()
        )

        # Log event
        log_event(
            db=db,
            session_id=session_id,
            node="present",
            step_idx=0,
            payload={"action": "session_created"}
        )

        # Extract first turn
        if tutor_state.history:
            last_msg = tutor_state.history[-1]
            message = last_msg.msg
            hints = last_msg.meta.get("hints", []) if last_msg.meta else []
        else:
            message = "Hello!"
            hints = []

        first_turn = {
            "message": message,
            "hints": hints,
            "step_idx": tutor_state.step_idx,
            "mastery_score": tutor_state.mastery_score
        }

        return CreateSessionResponse(
            session_id=session_id,
            first_turn=first_turn
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating session: {str(e)}")


@app.post("/sessions/{session_id}/step", response_model=StepResponse)
def submit_step(session_id: str, request: StepRequest, db: DBSession = Depends(get_db)):
    """
    Submit a student answer and get next turn.

    This endpoint:
    1. Loads session state
    2. Adds student reply to history
    3. Runs graph: Check → (Advance | Remediate) → ...
    4. Updates and persists state
    5. Returns next turn and routing info
    """
    try:
        # Load session
        session = get_session_by_id(db, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Parse state
        tutor_state = TutorState.model_validate_json(session.state_json)

        # Add student reply to history
        from models import HistoryEntry
        tutor_state.history.append(HistoryEntry(
            role="student",
            msg=request.student_reply,
            meta=None
        ))

        # Convert to GraphState
        graph_state = tutor_state_to_graph_state(tutor_state)
        graph_state["current_student_reply"] = request.student_reply

        # Run graph nodes: Check → routing → ...
        from graph.nodes import check_node, diagnose_node, route_after_check

        # 1. Check (grade the response)
        graph_state = check_node(graph_state)

        # 2. Route based on score
        routing = route_after_check(graph_state)

        # 3. Execute path
        if routing == "advance":
            from graph.nodes import advance_node, route_after_advance
            graph_state = advance_node(graph_state)

            # Check if we should continue or end
            next_step = route_after_advance(graph_state)

            if next_step == "present":
                # Continue with next question
                from graph.nodes import present_node
                graph_state = present_node(graph_state)
            # else: session ends

        else:  # remediate
            from graph.nodes import remediate_node, diagnose_node, present_node
            graph_state = remediate_node(graph_state)
            graph_state = diagnose_node(graph_state)
            # Note: In remediation, we don't immediately present next question
            # The remediation message itself is the response

        # Convert back to TutorState
        tutor_state = graph_state_to_tutor_state(graph_state)

        # Update database
        update_session_state(
            db=db,
            session_id=session_id,
            state_json=tutor_state.model_dump_json(),
            mastery=tutor_state.mastery_score,
            step_idx=tutor_state.step_idx
        )

        # Log events
        log_event(
            db=db,
            session_id=session_id,
            node="check",
            step_idx=tutor_state.step_idx,
            payload={"grading": tutor_state.last_grading.model_dump() if tutor_state.last_grading else {}}
        )

        log_event(
            db=db,
            session_id=session_id,
            node=routing,
            step_idx=tutor_state.step_idx,
            payload={"routing": routing}
        )

        # Build response
        if tutor_state.history:
            last_msg = tutor_state.history[-1]
            message = last_msg.msg
            hints = last_msg.meta.get("hints", []) if last_msg.meta else []
        else:
            message = ""
            hints = []

        next_turn = {
            "message": message,
            "hints": hints,
            "step_idx": tutor_state.step_idx,
            "mastery_score": tutor_state.mastery_score,
            "is_complete": tutor_state.step_idx >= 10 or tutor_state.mastery_score >= 0.85
        }

        return StepResponse(
            next_turn=next_turn,
            routing=routing.capitalize(),
            last_grading=tutor_state.last_grading
        )

    except Exception as e:
        import traceback
        error_details = f"Error processing step: {str(e)}\n{traceback.format_exc()}"
        print(error_details)
        raise HTTPException(status_code=500, detail=f"Error processing step: {str(e)}")


@app.get("/sessions/{session_id}/summary", response_model=SummaryResponse)
def get_summary(session_id: str, db: DBSession = Depends(get_db)):
    """
    Get session summary.

    Returns:
    - Steps completed
    - Final mastery score
    - Misconceptions encountered
    - Suggestions for next steps
    """
    try:
        # Load session
        session = get_session_by_id(db, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Parse state
        tutor_state = TutorState.model_validate_json(session.state_json)

        # Get events to analyze
        events = get_session_events(db, session_id)

        # Extract misconceptions from events
        misconceptions_seen = list(set(tutor_state.evidence))

        # Generate suggestions based on performance
        suggestions = []
        if tutor_state.mastery_score >= 0.85:
            suggestions.append(f"Excellent work on {tutor_state.goal.topic}!")
            suggestions.append("You're ready to move to more advanced topics.")
        elif tutor_state.mastery_score >= 0.7:
            suggestions.append("Good progress! Try 3-5 more practice problems.")
            suggestions.append(f"Focus on: {tutor_state.goal.learning_objectives[0]}")
        else:
            suggestions.append("Keep practicing! Review the examples.")
            suggestions.append(f"Revisit the concepts around {tutor_state.goal.topic}")

        if misconceptions_seen:
            suggestions.append(f"Work on understanding: {', '.join(misconceptions_seen[:2])}")

        return SummaryResponse(
            steps_completed=tutor_state.step_idx,
            mastery_score=tutor_state.mastery_score,
            misconceptions_seen=misconceptions_seen,
            suggestions=suggestions
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting summary: {str(e)}")


@app.get("/sessions/{session_id}")
def get_session_state(session_id: str, db: DBSession = Depends(get_db)):
    """
    Get full session state (for debugging).
    """
    session = get_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    tutor_state = TutorState.model_validate_json(session.state_json)

    return {
        "session_id": session_id,
        "step_idx": tutor_state.step_idx,
        "mastery_score": tutor_state.mastery_score,
        "history": tutor_state.history,
        "evidence": tutor_state.evidence,
        "student": tutor_state.student.model_dump(),
        "goal": tutor_state.goal.model_dump()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
