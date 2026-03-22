import os
import json
import tempfile
import requests

from typing import Dict, Any

from qgis._core import QgsRasterLayer
from qgis.core import (QgsVectorLayer, QgsProject, QgsMapLayer, QgsDataSourceUri)

LOG_TAG = 'AI_AGENT_DEBUG'

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


def fetch_postgis_layer(sql_query: str, target_name: str) -> str:
    """
    【AI 工具】根据 SQL 语句从 PostGIS 数据库直接加载图层。
    """
    from qgis.core import QgsMessageLog, Qgis
    
    QgsMessageLog.logMessage(f"准备连接数据库, 生成的SQL: {sql_query}", tag=LOG_TAG, level=Qgis.Info)

    uri = QgsDataSourceUri()
    uri.setConnection("39.102.119.130", "5432", "qgis_ai_plugin_db", "postgres", "iamchanfho")
    
    # 将 SQL 作为子查询作为数据源，必须指定几何列 'geom' 和主键 'gid'
    uri.setDataSource("", f"({sql_query})", "geom", "", "gid")
    
    uri_string = uri.uri()
    QgsMessageLog.logMessage(f"构造的图层 URI: {uri_string}", tag=LOG_TAG, level=Qgis.Info)
    
    layer = QgsVectorLayer(uri_string, target_name, "postgres")
    
    if layer.isValid():
        QgsMessageLog.logMessage(f"图层验证成功! 坐标系: {layer.crs().authid()}, 要素数量: {layer.featureCount()}", tag=LOG_TAG, level=Qgis.Success)
        if layer.featureCount() == 0:
            QgsMessageLog.logMessage("警告：图层要素数量为 0，这可能是由于 SQL 查询条件未匹配到任何数据，或者是 QGIS 解析子查询时出错。", tag=LOG_TAG, level=Qgis.Warning)
    else:
        error_msg = layer.dataProvider().error().message() if layer.dataProvider() else "未知错误"
        QgsMessageLog.logMessage(f"图层验证失败! 错误信息: {error_msg}", tag=LOG_TAG, level=Qgis.Critical)
    
    return add_layer_to_project(layer, target_name)


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

    elif source_type == 'cloud_database':
        sql_query = query_params.get('sql_query')
        if not sql_query:
            return "Error: 缺少 sql_query 参数"
        return fetch_postgis_layer(sql_query, target_name)

    else:
        return f"Error: 不支持或未知的 source_type '{source_type}'。"

