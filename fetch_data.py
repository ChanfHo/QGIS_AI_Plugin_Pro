import os
import json
import tempfile
import requests

from typing import Dict, Any

from qgis._core import QgsRasterLayer
from qgis.core import (QgsVectorLayer, QgsProject, QgsMapLayer)

LOG_TAG = 'AI_AGENT_DEBUG'

_CACHED_CATALOG = None
SERVER_IP = "47.100.209.65"
BASE_URL = f"http://{SERVER_IP}:8000"

def get_catalog_for_prompt() -> str:
    """
    内部辅助函数：获取服务器目录，并压缩成字符串，准备喂给 AI Prompt。
    """
    global _CACHED_CATALOG
    if _CACHED_CATALOG:
        return _CACHED_CATALOG

    try:
        url = f"{BASE_URL}/catalog"
        # 设置短超时，避免阻塞
        r = requests.get(url, timeout=3)
        if r.status_code == 200:
            data = r.json()
            # 转换为紧凑的 JSON 字符串 (去空格) 以节省 Token
            json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            _CACHED_CATALOG = json_str
            return json_str
        return "无法连接服务器获取目录。"
    except Exception:
        return "服务器离线或网络错误。"

def add_layer_to_project(layer: QgsMapLayer, target_name: str) -> str:
    """内部辅助函数：将图层添加到 QGIS 项目并设置名称。"""
    if layer and layer.isValid():
        project = QgsProject.instance()

        # 清理同名旧图层
        existing_layers = project.mapLayersByName(target_name)
        if existing_layers:
            project.removeMapLayers([l.id() for l in existing_layers])

        # 添加图层
        project.addMapLayer(layer)
        layer.setName(target_name)
        return f"Success: 数据 '{target_name}' 已成功获取并加载。"
    else:
        return f"Error: 无法加载数据或数据无效。"


def fetch_local_file(file_path: str, target_name: str) -> str:
    """加载本地矢量文件。"""
    if not file_path:
        return "Error: 缺少文件路径参数。"
    if not os.path.exists(file_path):
        # 在实际部署中，可能需要特殊的路径映射，但这里必须假设路径有效
        return f"Error: 找不到本地文件: {file_path}"

    # 使用 QgsVectorLayer(uri, baseName, providerName) 构造函数
    layer = QgsVectorLayer(file_path, target_name, 'ogr')

    return add_layer_to_project(layer, target_name)


def fetch_local_raster(file_path: str, target_name: str) -> str:
    """加载本地栅格文件。"""
    if not file_path: return "Error: 缺少文件路径参数。"
    if not os.path.exists(file_path): return f"Error: 找不到本地文件: {file_path}"

    # 使用 QgsRasterLayer 加载
    layer = QgsRasterLayer(file_path, target_name)
    if layer.isValid():
        return add_layer_to_project(layer, target_name)
    return "Error: 文件存在但无法识别为栅格数据。"


def fetch_file_by_path(file_path: str, target_name: str, layer_type: str = "vector") -> str:
    """
    【AI 工具】根据精准路径下载文件。
    AI 从 Prompt 里看到路径后，直接传给这里。
    """
    download_url = f"{BASE_URL}/download/{file_path}"
    filename = os.path.basename(file_path)
    save_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        headers = {"User-Agent": "QGIS-Direct-Agent"}
        r = requests.get(download_url, headers=headers, stream=True, timeout=60)

        if r.status_code == 404:
            return f"Error: 路径错误，服务器未找到文件: {file_path}"

        r.raise_for_status()

        with open(save_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        # 加载逻辑
        if layer_type == "raster":
            layer = QgsRasterLayer(save_path, target_name)
        else:
            layer = QgsVectorLayer(save_path, target_name, "ogr")

        return add_layer_to_project(layer, target_name)

    except Exception as e:
        return f"Error: 下载失败: {str(e)}"


def execute_fetch_task(source_type: str, query_params: Dict[str, Any]) -> str:
    """
    Agent A 的核心执行函数：根据类型调用对应的数据获取函数。
    """
    target_name = query_params.get('target_name')

    if not target_name:
        return "Error: 必须为新图层指定一个名称 (target_name)。"

    if source_type == 'local_file':
        return fetch_local_file(query_params.get('file_path'), target_name)

    elif source_type == 'local_raster':
        return fetch_local_raster(query_params.get('file_path'), target_name)

    elif source_type == 'private_server':
        file_path = query_params.get('file_path')
        target_name = query_params.get('target_name')
        layer_type = query_params.get('layer_type', 'vector')
        if not file_path:
            return "Error: 缺少 file_path 参数"

        return fetch_file_by_path(file_path, target_name, layer_type)

    else:
        return f"Error: 不支持或未知的 source_type '{source_type}'。"

