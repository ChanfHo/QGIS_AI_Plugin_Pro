import os
from typing import Any, Dict

from qgis.core import QgsProject, Qgis, QgsMessageLog

# --- 工具函数：项目管理 (供 Agent D 调用) ---

def new_project() -> str:
    """
    新建一个空白的 QGIS 项目。
    这会清除当前项目的所有图层和设置。

    Returns:
        str: 执行结果消息 (Success/Error)
    """
    try:
        # 获取项目单例并清除内容
        project = QgsProject.instance()
        project.clear()

        QgsMessageLog.logMessage("已新建空白项目", tag='AI_AGENT', level=Qgis.Info)
        return "Success: 新项目已创建。"
    except Exception as e:
        error_msg = f"创建新项目失败: {str(e)}"
        QgsMessageLog.logMessage(error_msg, tag='AI_AGENT', level=Qgis.Critical)
        return f"Error: {error_msg}"


def save_project(file_path: str) -> str:
    """
    将当前 QGIS 项目保存到指定路径。

    Args:
        file_path (str): 保存项目的完整文件路径 (例如: 'C:/Projects/my_map.qgz')

    Returns:
        str: 执行结果消息 (Success/Error)
    """
    try:
        if not file_path:
            return "Error: 未提供保存路径。"

        # 确保文件扩展名正确 (默认为 .qgz)
        if not (file_path.endswith('.qgz') or file_path.endswith('.qgs')):
            file_path += '.qgz'

        # 确保目标目录存在
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except OSError as e:
                return f"Error: 无法创建目录 '{directory}': {str(e)}"

        project = QgsProject.instance()

        # 设置文件名并写入
        project.setFileName(file_path)
        success = project.write()

        if success:
            QgsMessageLog.logMessage(f"项目已保存至: {file_path}", tag='AI_AGENT', level=Qgis.Info)
            return f"Success: 项目已成功保存至 {file_path}。"
        else:
            return f"Error: QGIS 无法写入文件 (未知错误)。"

    except Exception as e:
        return f"Error: 保存项目时发生异常: {str(e)}"


def load_project(file_path: str) -> str:
    """
    从指定路径加载 QGIS 项目。

    Args:
        file_path (str): 项目文件的完整路径

    Returns:
        str: 执行结果消息 (Success/Error)
    """
    try:
        if not file_path:
            return "Error: 未提供项目路径。"

        if not os.path.exists(file_path):
            return f"Error: 找不到文件 '{file_path}'。"

        project = QgsProject.instance()

        # 读取项目
        success = project.read(file_path)

        if success:
            QgsMessageLog.logMessage(f"已加载项目: {file_path}", tag='AI_AGENT', level=Qgis.Info)
            return f"Success: 项目 {os.path.basename(file_path)} 已成功加载。"
        else:
            # QgsProject.read() 失败通常意味着文件格式错误或权限问题
            return f"Error: 无法加载项目文件 '{file_path}' (文件可能损坏或格式不正确)。"

    except Exception as e:
        return f"Error: 加载项目时发生异常: {str(e)}"


# --- 核心调度函数 (Agent D 调用) ---

def execute_project_task(source_type: str, query_params: Dict[str, Any]) -> str:
    """
    Agent D 的核心执行函数：根据 source_type 调用对应的新建/保存/加载函数。

    Args:
        source_type (str): 任务类型 ('new_project', 'save_project', 'load_project')
        query_params (dict): 包含参数的字典，如 {'file_path': '...'}

    Returns:
        str: 执行结果消息 (以 Success 或 Error 开头)
    """
    QgsMessageLog.logMessage(f"执行项目任务: Type={source_type}, Params={query_params}", tag='AI_AGENT_DEBUG',
                             level=Qgis.Info)

    if source_type == 'new_project':
        return new_project()

    elif source_type == 'save_project':
        file_path = query_params.get('file_path')
        if not file_path:
            return "Error: 保存项目需要提供 'file_path' 参数。"
        return save_project(file_path)

    elif source_type == 'load_project':
        file_path = query_params.get('file_path')
        if not file_path:
            return "Error: 加载项目需要提供 'file_path' 参数。"
        return load_project(file_path)

    else:
        return f"Error: 未知的项目管理任务类型 '{source_type}'。"