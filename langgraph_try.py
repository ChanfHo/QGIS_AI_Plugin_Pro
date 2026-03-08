import json
import requests
from typing import TypedDict, List
from colorama import Fore
from langgraph.graph import StateGraph, END

from openai import OpenAI
from prompts import TASK_PLANNER_PROMPT, TASK_ROUTER_PROMPT


# ==============================
# API配置
# ==============================

API_KEY = "sk-a2cddd46f8924031b2888c97c73c6e43"
MODEL_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen-plus"

USER_REQUEST = "绘制一幅南宁市普通地图。"


# ==============================
# Qwen调用函数
# ==============================

def call_qwen(prompt):
    try:
        client = OpenAI(
            api_key=API_KEY,
            base_url=MODEL_URL,
        )

        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {'role': 'user', 'content': prompt}
            ]
        )
        return completion.choices[0].message.content
    except Exception as e:
        error_str = str(e)
        if "Arrearage" in error_str or "Access denied" in error_str:
            return "聊天接口报错: 阿里云 API Key 已欠费或无效，请检查配置。"
        return f"聊天接口报错: {error_str}"


def safe_json_loads(text):

    import re

    text = text.strip()

    # 去掉markdown
    text = text.replace("```json", "")
    text = text.replace("```", "")

    # 提取JSON
    match = re.search(r'\[.*\]', text, re.S)

    if match:
        return json.loads(match.group())

    match = re.search(r'\{.*\}', text, re.S)

    if match:
        return json.loads(match.group())

    raise Exception(f"无法解析JSON: {text}")

# ==============================
# LangGraph State
# ==============================


class GraphState(TypedDict):

    user_request: str
    task_plan: List
    current_step: int
    current_task: str
    assigned_agent: str
    execution_result: str


# ==============================
# State打印函数
# ==============================

def print_state(state, title):

    print(Fore.CYAN + f"\n===== STATE SNAPSHOT ({title}) =====")

    print(json.dumps(state, indent=2, ensure_ascii=False))


# ==============================
# Node 1 Task Planner
# ==============================

def task_planner_node(state: GraphState):

    print(Fore.YELLOW + "\n[Node] TaskPlanner")

    user_request = state["user_request"]

    prompt = TASK_PLANNER_PROMPT.format(user_request=user_request)

    result = call_qwen(prompt)
    
    # 打印原始返回结果以便调试
    print(Fore.BLUE + f"LLM 原始返回: {result}")

    try:
        parsed_result = safe_json_loads(result)
        
        # 处理新的返回结构 (包含 thought 和 plan)
        if isinstance(parsed_result, dict) and "thought" in parsed_result and "plan" in parsed_result:
            print(Fore.YELLOW + "\n[Task Planner 思考过程]")
            print(Fore.WHITE + parsed_result["thought"])
            task_plan = parsed_result["plan"]
        else:
            # 兼容旧格式（如果是直接返回列表）
            task_plan = parsed_result
            
    except Exception as e:
        print(Fore.RED + f"JSON解析失败: {e}")
        # 如果解析失败，抛出更详细的异常或者结束
        raise e

    state["task_plan"] = task_plan
    state["current_step"] = 0
    state["current_task"] = task_plan[0]["task"]

    print(Fore.GREEN + "TaskPlanner 输出任务计划：")

    print(json.dumps(task_plan, indent=2, ensure_ascii=False))

    print_state(state, "After TaskPlanner")

    return state


# ==============================
# Node 2 Task Router
# ==============================

def task_router_node(state: GraphState):

    print(Fore.YELLOW + "\n[Node] TaskRouter")

    step = state["current_step"]
    task = state["task_plan"][step]["task"]

    prompt = TASK_ROUTER_PROMPT.format(task=task)

    result = call_qwen(prompt)

    router_output = safe_json_loads(result)

    agent = router_output["agent"]

    state["assigned_agent"] = agent
    state["current_task"] = task

    print(Fore.GREEN + "TaskRouter 选择 Agent：")

    print(json.dumps(router_output, indent=2, ensure_ascii=False))

    print_state(state, "After TaskRouter")

    return state


# ==============================
# Node 3 Agent Executor
# ==============================

def agent_executor_node(state: GraphState):

    print(Fore.YELLOW + "\n[Node] AgentExecutor")

    agent = state["assigned_agent"]
    task = state["current_task"]

    print(Fore.MAGENTA + f"执行Agent：{agent}")
    print(Fore.MAGENTA + f"执行任务：{task}")

    # 模拟执行成功
    state["execution_result"] = "success"

    print(Fore.GREEN + "任务执行成功")

    print_state(state, "After AgentExecution")

    return state


# ==============================
# Step Controller & Updater
# ==============================

def check_continuation(state: GraphState):

    step = state["current_step"]
    plan = state["task_plan"]

    if plan[step]["is_last_step"]:
        print(Fore.WHITE + "\nWorkflow结束：所有任务执行完成")
        return END

    return "update_step"


def update_step_node(state: GraphState):

    state["current_step"] += 1
    plan = state["task_plan"]
    next_task = plan[state["current_step"]]["task"]
    state["current_task"] = next_task

    print(Fore.CYAN + f"\n进入下一任务 Step {state['current_step'] + 1}")

    return state


# ==============================
# 构建LangGraph
# ==============================

builder = StateGraph(GraphState)

builder.add_node("planner", task_planner_node)
builder.add_node("router", task_router_node)
builder.add_node("executor", agent_executor_node)
builder.add_node("update_step", update_step_node)

builder.set_entry_point("planner")

builder.add_edge("planner", "router")
builder.add_edge("router", "executor")
builder.add_edge("update_step", "router")

builder.add_conditional_edges(
    "executor",
    check_continuation
)

graph = builder.compile()


# ==============================
# 运行
# ==============================

if __name__ == "__main__":

    print(Fore.WHITE + "\n===== LangGraph GIS Workflow Start =====")

    graph.invoke({
        "user_request": USER_REQUEST
    }, {"recursion_limit": 100})