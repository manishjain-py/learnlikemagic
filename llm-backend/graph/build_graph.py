"""
Build and compile the LangGraph agent.
"""
from langgraph.graph import StateGraph, END
from graph.state import GraphState
from graph.nodes import (
    present_node,
    check_node,
    diagnose_node,
    remediate_node,
    advance_node,
    route_after_check,
    route_after_advance,
    route_after_remediate
)


def build_tutor_graph():
    """
    Build the adaptive tutor LangGraph.

    Flow:
    START → Present → Check → (Advance | Remediate)
         ↑                        ↓           ↓
         |                     (END|Present)  Diagnose
         └──────────────────────────────────────┘

    Returns:
        Compiled StateGraph
    """
    # Create graph
    graph = StateGraph(GraphState)

    # Add nodes
    graph.add_node("present", present_node)
    graph.add_node("check", check_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("remediate", remediate_node)
    graph.add_node("advance", advance_node)

    # Set entry point
    graph.set_entry_point("present")

    # Add edges
    # Present → Check (always)
    graph.add_edge("present", "check")

    # Check → (Advance | Remediate) - conditional
    graph.add_conditional_edges(
        "check",
        route_after_check,
        {
            "advance": "advance",
            "remediate": "remediate"
        }
    )

    # Advance → (Present | END) - conditional
    graph.add_conditional_edges(
        "advance",
        route_after_advance,
        {
            "present": "present",
            "end": END
        }
    )

    # Remediate → Diagnose
    graph.add_edge("remediate", "diagnose")

    # Diagnose → Present (loop back)
    graph.add_edge("diagnose", "present")

    # Compile graph
    compiled_graph = graph.compile()

    print("✓ Tutor graph compiled successfully")
    print("  Nodes: present, check, diagnose, remediate, advance")
    print("  Entry: present")

    return compiled_graph


def get_graph():
    """Get the compiled tutor graph (singleton pattern)."""
    global _graph_instance
    if "_graph_instance" not in globals():
        _graph_instance = build_tutor_graph()
    return _graph_instance


# For debugging: visualize graph structure
def visualize_graph():
    """
    Print a text representation of the graph structure.
    """
    print("""
    Adaptive Tutor Graph Structure:

    START
      ↓
    [Present] ────→ Retrieve content via RAG
      ↓             Generate teaching message
    [Check] ──────→ Grade student response
      ↓
      ├─→ (score >= 0.8) ──→ [Advance] ─┬→ (step < 10) ──→ [Present]
      │                                   └→ (step >= 10 OR mastery >= 0.85) ──→ END
      │
      └─→ (score < 0.8) ───→ [Remediate] ──→ [Diagnose] ──→ [Present]
                             Provide scaffold   Update evidence
                                               Update mastery (EMA)
    """)


if __name__ == "__main__":
    # Build and visualize for testing
    visualize_graph()
    graph = build_tutor_graph()
    print("\nGraph built successfully!")
