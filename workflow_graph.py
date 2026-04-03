import json
import logging
from typing import TypedDict, List, Any, Dict
from langgraph.graph import StateGraph, END
from colorama import Fore

from .chat_model import call_qwen_with_prompt, safe_json_loads
from .prompts import TASK_PLANNER_PROMPT, TASK_ROUTER_PROMPT
from .agents import run_agent_a, run_agent_b, run_agent_c, run_agent_d, run_agent_e

# ==============================
# LangGraph State
# ==============================

class GraphState(TypedDict):
    user_request: str
    task_plan: List[Dict]
    current_step: int
    current_task: str
    assigned_agent: str
    execution_result: Any
    layers: List[Any]  # QGIS Layers
    error: str # 错误信息
    is_gis_task: bool # 是否是GIS任务
    thought: str # 思考过程
    executor: Any # 执行器

# ==============================
# Node 1: Task Planner
# ==============================

def task_planner_node(state: GraphState):
    user_request = state["user_request"]
    prompt = TASK_PLANNER_PROMPT.format(user_request=user_request)
    
    try:
        result = call_qwen_with_prompt(prompt)
        parsed_result = safe_json_loads(result)
        
        # 处理新的返回结构 (包含 thought 和 plan)
        if "thought" in parsed_result:
            state["thought"] = parsed_result["thought"]
        
        if "is_gis_task" in parsed_result:
            state["is_gis_task"] = parsed_result["is_gis_task"]
        else:
            # 默认为True，兼容旧格式
            state["is_gis_task"] = True

        if "plan" in parsed_result:
            task_plan = parsed_result["plan"]
        elif isinstance(parsed_result, list):
            task_plan = parsed_result
        else:
            # 尝试直接把整个对象当做单步任务（容错）
            task_plan = [parsed_result]

        state["task_plan"] = task_plan
        state["current_step"] = 0
        if task_plan:
            state["current_task"] = task_plan[0].get("task", "")
        else:
            state["current_task"] = ""
            
    except Exception as e:
        state["error"] = f"TaskPlanner Error: {str(e)}"
        
    return state

# ==============================
# Node 2: Task Router
# ==============================

def task_router_node(state: GraphState):
    
    # 如果不是GIS任务，直接跳过路由
    if not state.get("is_gis_task", True):
        return state

    step = state["current_step"]
    if step < len(state["task_plan"]):
        task = state["task_plan"][step]["task"]
        prompt = TASK_ROUTER_PROMPT.format(task=task)
        
        try:
            result = call_qwen_with_prompt(prompt)
            router_output = safe_json_loads(result)
            agent = router_output.get("agent", "unknown")
            
            state["assigned_agent"] = agent
            state["current_task"] = task
            # 更新步骤信息，确保一致
            if "step" in state["task_plan"][step]:
                # 有些plan里的step可能是数字
                pass 
        except Exception as e:
            state["error"] = f"TaskRouter Error: {str(e)}"
    
    return state

# ==============================
# Node 3: Agent Executor
# ==============================

def agent_executor_node(state: GraphState):
    
    # 如果不是GIS任务，直接跳过执行
    if not state.get("is_gis_task", True):
        return state

    agent = state["assigned_agent"]
    task = state["current_task"]
    layers = state["layers"]
    
    # 获取外部执行器 (用于主线程操作)
    executor = state.get("executor")
    
    result = {"is_process_complete": False, "possible_problem": "Unknown agent"}
    
    try:
        if agent == "agent_a":
            result = run_agent_a(task, progress_callback=executor.emit_download_progress if executor else None)
        elif agent == "agent_b":
            result = run_agent_b(task, layers)
        elif agent == "agent_c":
            result = run_agent_c(task, layers)
        elif agent == "agent_d":
            # Agent D 需要特殊处理
            plan = run_agent_d(task, execute=False)
            if plan.get("is_process_complete") and plan.get("need_execution"):
                if executor:
                    # 调用外部执行器执行主线程任务
                    # 这是一个阻塞调用
                    p_type = plan["source_type"]
                    p_params = plan["query_params"]
                    exec_res = executor.execute_project_op(p_type, p_params)
                    
                    if exec_res.startswith("Success"):
                         result = {"is_process_complete": True, "tool_result": exec_res}
                         # 刷新图层列表
                         if hasattr(executor, "refresh_layers"):
                             state["layers"] = executor.refresh_layers()
                    else:
                         result = {"is_process_complete": False, "possible_problem": exec_res}
                else:
                    result = {"is_process_complete": False, "possible_problem": "Executor not provided for main thread task"}
            else:
                result = plan
                
        elif agent == "agent_e":
            plan = run_agent_e(task, layers)
            if plan.get("is_process_complete"):
                tasks = plan.get("tasks", [])
                if tasks and executor:
                    # 调用外部执行器执行布局任务
                    exec_res = executor.execute_layout_op(tasks)
                    result = {"is_process_complete": True, "tool_result": exec_res}
                elif not tasks:
                     result = {"is_process_complete": False, "possible_problem": "No layout tasks generated"}
                else:
                     result = {"is_process_complete": False, "possible_problem": "Executor not provided for layout task"}
            else:
                result = plan
        else:
            result = {"is_process_complete": False, "possible_problem": f"Unknown agent: {agent}"}
            
        state["execution_result"] = result
        
    except Exception as e:
        state["error"] = f"AgentExecutor Error: {str(e)}"
        state["execution_result"] = {"is_process_complete": False, "possible_problem": str(e)}

    return state

# ==============================
# Node 4: Step Updater
# ==============================

def step_updater_node(state: GraphState):
    """
    更新任务步骤的节点
    """
    result = state.get("execution_result", {})
    if result.get("is_process_complete", False):
        state["current_step"] += 1
    return state

# ==============================
# Conditional Logic
# ==============================

def check_loop_condition(state: GraphState):
    """
    检查循环条件，决定下一步走向
    """
    if state.get("error"):
        return "error"
    
    if not state.get("is_gis_task", True):
        return "end"

    result = state.get("execution_result", {})
    
    if not result.get("is_process_complete", False):
        # 任务失败
        return "error"
    
    if state["current_step"] < len(state["task_plan"]):
        return "continue"
    else:
        return "end"

# ==============================
# Build Graph
# ==============================

def create_workflow_graph():
    workflow = StateGraph(GraphState)

    workflow.add_node("task_planner", task_planner_node)
    workflow.add_node("task_router", task_router_node)
    workflow.add_node("agent_executor", agent_executor_node)
    workflow.add_node("step_updater", step_updater_node)

    workflow.set_entry_point("task_planner")

    workflow.add_edge("task_planner", "task_router")
    workflow.add_edge("task_router", "agent_executor")
    workflow.add_edge("agent_executor", "step_updater")

    # 条件边
    workflow.add_conditional_edges(
        "step_updater",
        check_loop_condition,
        {
            "continue": "task_router",
            "end": END,
            "error": END
        }
    )

    app = workflow.compile()
    return app
