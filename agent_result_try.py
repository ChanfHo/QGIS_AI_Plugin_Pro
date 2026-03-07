import logging
from agent_prompts import agent_a_prompt, agent_b_prompt, agent_c_prompt

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.models import ModelFactory
from camel.types import ModelPlatformType, ModelType
from camel.configs import QwenConfig

from qgis.core import QgsProject

# --- 配置 ---
logging.getLogger('camel').setLevel(logging.CRITICAL)
API_KEY = "sk-a2cddd46f8924031b2888c97c73c6e43"
MODEL_TYPE = ModelType.QWEN_2_5_CODER_32B
MODEL_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# --- 角色名称 ---
agent_a_name = "数据获取智能体"
agent_b_name = "数据处理智能体"
agent_c_name = "样式处理智能体"

task = "给水库设置合适的样式"
available_layers = ['湖北省水库', '武汉市湖泊', '武汉市土地利用', '湖北省', '武汉市', '武汉大学', '武汉市自然用地', '洪山区地铁站', '武汉市DEM']
dynamic_prompt = f"{agent_c_prompt} + 【当前 QGIS 项目中的可用图层列表】 + {available_layers}"

layers = None  # 假设 layers 是一个列表，包含所有图层

model = ModelFactory.create(
    model_platform=ModelPlatformType.QWEN,
    model_type=MODEL_TYPE,
    api_key=API_KEY,
    url=MODEL_URL,
    model_config_dict=QwenConfig(temperature=0.2).as_dict(),
)
sys_msg = BaseMessage.make_assistant_message(role_name=agent_b_name, content=dynamic_prompt)
agent = ChatAgent(system_message=sys_msg, model=model)

response = agent.step(task)
if response.msgs:
    json_content = response.msgs[0].content.strip()
else:
    # 如果列表为空，设置错误信息，避免 IndexError
    json_content = "ERROR: LLM did not return any message. Check API status or communication logs."

    # 增加调试信息，打印完整的响应对象，便于查看具体错误原因
    print("--- DEBUG INFO ---")
    print(f"Empty message list received. Full response object: {response}")
    print("------------------")

if __name__ == "__main__":
    print(f"user_input:{task}")
    print(f"llm response:{json_content}")


