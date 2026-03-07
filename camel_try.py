import json
import logging
from colorama import Fore

from camel.societies import RolePlaying
from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType
from camel.configs import QwenConfig

# 设置日志级别，避免CAMEL框架内部打印过多警告
logging.getLogger("camel").setLevel(logging.WARNING)

# --- 配置部分 ---
TASK_PROMPT = "绘制一幅湖北省水系图"  # 用户的输入
API_KEY = "sk-a2cddd46f8924031b2888c97c73c6e43"
MODEL_TYPE = ModelType.QWEN_2_5_CODER_32B
MODEL_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ROUND_LIMIT = 10
# 模型初始化
try:
    model = ModelFactory.create(
        model_platform=ModelPlatformType.QWEN,
        model_type=MODEL_TYPE,
        api_key=API_KEY,
        url=MODEL_URL,
        model_config_dict=QwenConfig(temperature=0.2).as_dict(),
    )
except Exception as e:
    # 处理ModelFactory创建失败的情况
    print(f"Warning: ModelFactory failed to create model. Using a placeholder model configuration. Error: {e}")
    # 仅为演示结构，实际运行需要一个可用的模型
    model = None

# --- 构建RolePlaying对象 ---
# 任务参数
task_kwargs = {
    'task_prompt': TASK_PROMPT,
    'with_task_specify': False,
    'output_language': 'zh'
}

# GIS Assistant (Assistant) 参数
assistant_role_kwargs = {
    'assistant_role_name': 'GIS Assistant',
    'assistant_agent_kwargs': {'model': model}
}

# GIS Planner (User) 参数
user_role_kwargs = {
    'user_role_name': 'GIS Planner',
    'user_agent_kwargs': {'model': model}
}

# 创建RolePlaying实例:QGIS-AI工作小组
qgis_agents_workgroup = RolePlaying(
    **task_kwargs,  # 任务参数
    **assistant_role_kwargs,  # GIS Assistant (Assistant) 的参数
    **user_role_kwargs,  # GIS Planner (User) 的参数
)


# --- 打印系统信息函数（测试用） ---
def print_system_info():
    print(f"AI 助手系统消息:\n{qgis_agents_workgroup.assistant_sys_msg}\n")
    print(f"AI 用户系统消息:\n{qgis_agents_workgroup.user_sys_msg}\n")


# --- RolePlaying实例运行函数 ---
def run_role_playing(agents_workgroup: RolePlaying, user_input: str, round_limit: int):
    print(Fore.YELLOW + f"QGIS多智能体工作小组流程启动。[用户需求]{user_input}\n")

    input_msg = agents_workgroup.init_chat()
    try:
        for i in range(round_limit):
            # ---获取planner和assistant的输出---
            assistant_response, planner_response = agents_workgroup.step(input_msg)

            if planner_response.msgs:
                planner_output_content = planner_response.msgs[0].content.strip()
            else:
                print(Fore.BLUE + "[GIS Planner Output]：Planner未生成消息")
                break

            if assistant_response.msgs:
                assistant_output_content = assistant_response.msgs[0].content.strip()
            else:
                print(Fore.GREEN + "[GIS Assistant Output]：Assistant未生成消息")
                break

            # 打印planner和assistant的初始输出
            print(Fore.BLUE + f"[GIS Planner Output]：{planner_output_content}\n")
            # print(Fore.GREEN + f"[GIS Assistant Output]：{assistant_output_content}\n")

            try:
                planner_json = json.loads(planner_output_content)
                assistant_json = json.loads(assistant_output_content)
            except json.JSONDecodeError as e:
                print(f"--- JSON 解析失败，请检查输出格式。错误：{e}。---")
                break

            # ---进入普通聊天模式---
            if not planner_json["is_gis_task"]:
                # ---普通聊天接口---
                print("用户输入与GIS无关，进入普通聊天。")
                break

            # ---QGIS操作智能体召唤接口---
            agent = assistant_json["agent"]
            if agent == "agent_a":
                # agent_a召唤接口
                assistant_json["is_process_complete"] = True  # 任务已完成
            elif agent == "agent_b":
                # agent_b召唤接口
                assistant_json["is_process_complete"] = True  # 任务已完成
            elif agent == "agent_c":
                # agent_c召唤接口
                assistant_json["is_process_complete"] = True  # 任务已完成
            elif agent == "agent_d":
                # agent_d召唤接口
                assistant_json["is_process_complete"] = True  # 任务已完成
            elif agent == "agent_e":
                # agent_e召唤接口
                assistant_json["is_process_complete"] = True  # 任务已完成
            else:
                print(f"未正确输出agent")

            # ---打印完成任务后Assistant的输出---
            print(Fore.GREEN + f"[GIS Assistant Output]：{json.dumps(assistant_json, ensure_ascii=False)}\n")

            # ---检查终止条件---
            if planner_json["is_last_step"]:
                print(Fore.WHITE + "任务执行成功，流程结束！")
                break

            # ---准备下一轮的输入消息 (由Planner发送给Assistant)---
            if assistant_json["is_process_complete"]:
                input_msg = json.dumps(assistant_json, ensure_ascii=False) + "请进行下一个任务"
            else:
                # 该步骤未完成，需要和Assistant交流，让它进行相应处理
                possible_problem = assistant_json["possible_problem"]
                input_msg = json.dumps(assistant_json, ensure_ascii=False) + f"这一个步骤未完成，因为{possible_problem}"

        else:
            print("--- 达到轮次限制，流程终止。---")

    except Exception as e:
        print(f"--- 流程异常终止：{e} ---")


if __name__ == "__main__":
    print_system_info()
    run_role_playing(qgis_agents_workgroup, TASK_PROMPT, ROUND_LIMIT)
