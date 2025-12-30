import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv()

from shared.services.llm_service import LLMService
from tutor.orchestration.tutor_workflow import build_workflow
from config import get_settings

def generate_graph_image():
    """Generate a PNG image of the LangGraph workflow."""
    print("🚀 Generating workflow visualization...")
    
    # Mock dependencies
    settings = get_settings()
    if not settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = "sk-mock-key-for-visualization"
        
    llm_service = LLMService(api_key="mock", max_retries=1)
    
    # Build the workflow manually to avoid checkpointer dependency
    from tutor.models.state import SimplifiedState
    from tutor.agents.planner_agent import PlannerAgent
    from tutor.agents.executor_agent import ExecutorAgent
    from tutor.agents.evaluator_agent import EvaluatorAgent
    from langgraph.graph import StateGraph, END
    from tutor.orchestration.tutor_workflow import route_entry, route_after_executor, route_after_evaluation
    
    # Create agent instances
    planner = PlannerAgent(llm_service)
    executor = ExecutorAgent(llm_service)
    evaluator = EvaluatorAgent(llm_service)

    # Create StateGraph
    workflow = StateGraph(SimplifiedState)

    # Add nodes
    def router_node(state: SimplifiedState) -> dict:
        return {} 

    workflow.add_node("router", router_node)
    workflow.add_node("planner", planner.execute)
    workflow.add_node("executor", executor.execute)
    workflow.add_node("evaluator", evaluator.execute)

    # Set entry point
    workflow.set_entry_point("router")

    # Add edges
    workflow.add_conditional_edges(
        "router",
        route_entry,
        {
            "planner": "planner",
            "evaluator": "evaluator",
            "executor": "executor",
        },
    )

    workflow.add_edge("planner", "executor")

    workflow.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "evaluator": "evaluator",
            "end": END,
        },
    )

    workflow.add_conditional_edges(
        "evaluator",
        route_after_evaluation,
        {
            "replan": "planner",
            "continue": "executor",
            "end": END,
        },
    )

    # Compile WITHOUT checkpointer
    app = workflow.compile()
    
    # Generate Mermaid PNG
    graph_image = app.get_graph().draw_mermaid_png()
    
    output_path = "tutor_workflow.png"
    with open(output_path, "wb") as f:
        f.write(graph_image)
        
    print(f"✅ Workflow visualization saved to {output_path}")
        


if __name__ == "__main__":
    generate_graph_image()
