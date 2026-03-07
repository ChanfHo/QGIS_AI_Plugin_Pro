import os
from typing import Dict, Any
from qgis.utils import iface
from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend,
    QgsLayoutItemScaleBar, QgsLayoutItemLabel, QgsLayoutPoint,
    QgsLayoutSize, QgsUnitTypes, QgsLayoutItemPage, QgsLayoutExporter
)
from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import QFileDialog


def execute_layout_task(params: Dict[str, Any]) -> str:
    """
    Agent E 的具体执行单元。
    """
    action_type = params.get("action_type")
    canvas = iface.mapCanvas()
    project = QgsProject.instance()

    try:
        # --- 1. 视图控制 ---
        if action_type == "set_scale":
            scale = float(params.get("scale_value", 10000))
            if scale <= 0: scale = 10000
            canvas.zoomScale(int(scale))
            canvas.refresh()
            return f"已将比例尺设置为 1:{int(scale)}"

        elif action_type == "zoom_layer":
            layer_name = params.get("layer_name")
            layers = project.mapLayersByName(layer_name)
            if not layers: return f"Error: 图层 '{layer_name}' 不存在"
            canvas.setExtent(layers[0].extent())
            canvas.refresh()
            return f"已缩放到图层 '{layer_name}'"

        elif action_type == "zoom_full":
            canvas.zoomToFullExtent()
            canvas.refresh()
            return "已显示全图"

        # --- 2. 基础布局创建 ---
        elif action_type == "create_print_layout":
            title = params.get("title", "AI自动布局")
            layout_manager = project.layoutManager()

            existing_layout = layout_manager.layoutByName(title)
            if existing_layout:
                layout_manager.removeLayout(existing_layout)

            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            layout.setName(title)
            layout_manager.addLayout(layout)

            # A4 横向
            pc = layout.pageCollection()
            page = pc.page(0)
            page.setPageSize('A4', QgsLayoutItemPage.Orientation.Landscape)

            # 标题
            title_item = QgsLayoutItemLabel(layout)
            title_item.setText(title)
            title_font = QFont("SimHei", 24, QFont.Bold)
            title_item.setFont(title_font)
            title_item.setHAlign(Qt.AlignHCenter)
            title_item.setVAlign(Qt.AlignVCenter)
            title_item.attemptMove(QgsLayoutPoint(0, 5, QgsUnitTypes.LayoutMillimeters))
            title_item.attemptResize(QgsLayoutSize(297, 15, QgsUnitTypes.LayoutMillimeters))
            layout.addLayoutItem(title_item)

            # 地图
            map_item = QgsLayoutItemMap(layout)
            map_item.attemptMove(QgsLayoutPoint(10, 25, QgsUnitTypes.LayoutMillimeters))
            map_item.attemptResize(QgsLayoutSize(277, 175, QgsUnitTypes.LayoutMillimeters))
            map_item.zoomToExtent(canvas.extent())
            map_item.setFrameEnabled(True)
            layout.addLayoutItem(map_item)

            iface.openLayoutDesigner(layout)
            return f"已创建基础布局 '{title}'"

        # --- 3. 组件添加与导出 ---
        elif action_type in ["add_legend", "add_scale_bar", "add_north_arrow", "add_map", "export_layout_pdf"]:
            layout_name = params.get("layout_name")

            # 智能查找布局
            if not layout_name or layout_name == "AI自动布局":
                layouts = project.layoutManager().printLayouts()
                if layouts:
                    active_layout = iface.openLayoutDesigners()
                    if active_layout:
                        layout_name = active_layout[0].layout().name()
                    else:
                        layout_name = layouts[-1].name()
                else:
                    return "Error: 没有找到任何可用布局。"

            layout = project.layoutManager().layoutByName(layout_name)
            if not layout: return f"Error: 找不到布局 '{layout_name}'"

            # ---  导出 PDF ---
            if action_type == "export_layout_pdf":
                # 弹出文件保存对话框 (在主线程中这是安全的)
                # 参数: 父窗口, 标题, 默认文件名, 文件过滤器
                file_path, _ = QFileDialog.getSaveFileName(
                    None,
                    "导出布局为PDF",
                    f"{layout_name}.pdf",
                    "PDF Files (*.pdf)"
                )

                if file_path:
                    exporter = QgsLayoutExporter(layout)
                    settings = QgsLayoutExporter.PdfExportSettings()
                    # 导出
                    result = exporter.exportToPdf(file_path, settings)

                    if result == QgsLayoutExporter.Success:
                        return f"成功导出 PDF 至: {file_path}"
                    else:
                        return f"Error: 导出失败，错误代码 {result}"
                else:
                    return "操作已取消 (未选择保存路径)"

            map_item = None
            for item in layout.items():
                if isinstance(item, QgsLayoutItemMap):
                    map_item = item
                    break

            if action_type == "add_map":
                if map_item: return f"布局 '{layout_name}' 已存在地图，跳过。"
                map_item = QgsLayoutItemMap(layout)
                map_item.attemptMove(QgsLayoutPoint(10, 25, QgsUnitTypes.LayoutMillimeters))
                map_item.attemptResize(QgsLayoutSize(277, 175, QgsUnitTypes.LayoutMillimeters))
                map_item.zoomToExtent(canvas.extent())
                layout.addLayoutItem(map_item)
                return f"已在 '{layout_name}' 补充地图"

            elif action_type == "add_legend":
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemLegend): return f"跳过重复图例。"
                legend = QgsLayoutItemLegend(layout)
                if map_item: legend.setLinkedMap(map_item)
                legend.setTitle("图例")
                legend.attemptMove(QgsLayoutPoint(245, 150, QgsUnitTypes.LayoutMillimeters))
                layout.addLayoutItem(legend)
                return f"已添加图例"

            elif action_type == "add_scale_bar":
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemScaleBar): return f"跳过重复比例尺。"
                scalebar = QgsLayoutItemScaleBar(layout)
                scalebar.setStyle('Single Box')
                if map_item: scalebar.setLinkedMap(map_item)
                scalebar.applyDefaultSize()
                scalebar.setNumberOfSegments(2)
                scalebar.attemptMove(QgsLayoutPoint(20, 185, QgsUnitTypes.LayoutMillimeters))
                layout.addLayoutItem(scalebar)
                return f"已添加比例尺"

            elif action_type == "add_north_arrow":
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemLabel) and item.text() == "N": return f"跳过重复指北针。"
                arrow = QgsLayoutItemLabel(layout)
                arrow.setText("N")
                arrow_font = QFont("Arial", 28, QFont.Bold)
                arrow.setFont(arrow_font)
                arrow.attemptMove(QgsLayoutPoint(270, 30, QgsUnitTypes.LayoutMillimeters))
                layout.addLayoutItem(arrow)
                return f"已添加指北针"

        return f"Error: 未知操作 {action_type}"

    except Exception as e:
        import traceback
        return f"Error: {str(e)}"