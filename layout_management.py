import os
from typing import Dict, Any
from qgis.utils import iface
from qgis.core import (
    QgsProject, QgsPrintLayout, QgsLayoutItemMap, QgsLayoutItemLegend,
    QgsLayoutItemScaleBar, QgsLayoutItemLabel, QgsLayoutPoint,
    QgsLayoutSize, QgsUnitTypes, QgsLayoutItemPage, QgsLayoutExporter,
    QgsLayoutItemPicture, QgsApplication, QgsMessageLog, Qgis, QgsLayoutItem
)
from qgis.PyQt.QtCore import QSettings, Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import QFileDialog


def get_target_layout(project: QgsProject, layout_name: str = None) -> QgsPrintLayout:
    """辅助函数：获取目标布局，若未指定则获取当前活动布局或最后一个布局"""
    if layout_name and layout_name != "AI自动布局":
        layout = project.layoutManager().layoutByName(layout_name)
        if layout:
            return layout
    
    # 获取项目中的布局列表，优先返回最后一个（通常是最新创建的）
    layouts = project.layoutManager().printLayouts()
    if layouts:
        return layouts[-1]
        
    # 尝试获取当前活动布局（兜底）
    try:
        active_layouts = iface.openLayoutDesigners()
        if active_layouts:
            return active_layouts[0].layout()
    except Exception:
        pass
        
    return None

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
            page_size_str = params.get("page_size", "A4").upper()
            layout_manager = project.layoutManager()

            existing_layout = layout_manager.layoutByName(title)
            if existing_layout:
                layout_manager.removeLayout(existing_layout)

            layout = QgsPrintLayout(project)
            layout.initializeDefaults()
            layout.setName(title)
            layout_manager.addLayout(layout)

            # 根据纸张大小设置页面
            valid_sizes = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594)}
            if page_size_str not in valid_sizes:
                page_size_str = "A4"
            page_width, page_height = valid_sizes[page_size_str]

            pc = layout.pageCollection()
            page = pc.page(0)
            page.setPageSize(page_size_str, QgsLayoutItemPage.Orientation.Landscape)

            # 标题
            title_item = QgsLayoutItemLabel(layout)
            title_item.setText(title)
            title_font = QFont("SimHei", 24, QFont.Bold)
            title_item.setFont(title_font)
            title_item.setHAlign(Qt.AlignHCenter)
            title_item.setVAlign(Qt.AlignVCenter)
            title_item.attemptMove(QgsLayoutPoint(0, 5, QgsUnitTypes.LayoutMillimeters))
            title_item.attemptResize(QgsLayoutSize(page_width, 15, QgsUnitTypes.LayoutMillimeters))
            layout.addLayoutItem(title_item)

            # 地图 (留出边距，上25，下10，左右各10)
            map_item = QgsLayoutItemMap(layout)
            map_width = page_width - 20
            map_height = page_height - 35
            map_item.attemptMove(QgsLayoutPoint(10, 25, QgsUnitTypes.LayoutMillimeters))
            map_item.attemptResize(QgsLayoutSize(map_width, map_height, QgsUnitTypes.LayoutMillimeters))
            
            # 缩放到图层范围，并稍微缩小比例（放大地图）使其更加饱满
            map_item.zoomToExtent(canvas.extent())
            current_scale = map_item.scale()
            map_item.setScale(current_scale * 1.2)
            
            map_item.setFrameEnabled(True)
            layout.addLayoutItem(map_item)

            iface.openLayoutDesigner(layout)
            return f"已创建基础布局 '{title}' (纸张: {page_size_str})"

        # --- 3. 组件添加与导出 ---
        elif action_type in ["add_legend", "add_scale_bar", "add_north_arrow", "add_map", "export_layout_pdf", "set_title"]:
            layout = get_target_layout(project, params.get("layout_name"))
            if not layout: 
                return "Error: 没有找到任何可用布局。"
            layout_name = layout.name()

            # --- 设置标题 ---
            if action_type == "set_title":
                new_title = params.get("title", "未命名布局")
                layout.setName(new_title)
                
                # 寻找现有的标题项并更新
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemLabel):
                        # 假设当前布局中唯一的/最先找到的 Label 是标题
                        item.setText(new_title)
                        return f"已将布局标题设置为 '{new_title}'"
                
                # 如果没有找到，则新建一个
                page = layout.pageCollection().page(0)
                page_width = page.pageSize().width()
                title_item = QgsLayoutItemLabel(layout)
                title_item.setText(new_title)
                title_font = QFont("SimHei", 24, QFont.Bold)
                title_item.setFont(title_font)
                title_item.setHAlign(Qt.AlignHCenter)
                title_item.setVAlign(Qt.AlignVCenter)
                title_item.attemptMove(QgsLayoutPoint(0, 5, QgsUnitTypes.LayoutMillimeters))
                title_item.attemptResize(QgsLayoutSize(page_width, 15, QgsUnitTypes.LayoutMillimeters))
                layout.addLayoutItem(title_item)
                return f"已将布局标题设置为 '{new_title}'"

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
                
                # 获取页面尺寸计算地图大小
                page = layout.pageCollection().page(0)
                page_width = page.pageSize().width()
                page_height = page.pageSize().height()
                map_width = page_width - 20
                map_height = page_height - 35
                
                map_item = QgsLayoutItemMap(layout)
                map_item.attemptMove(QgsLayoutPoint(10, 25, QgsUnitTypes.LayoutMillimeters))
                map_item.attemptResize(QgsLayoutSize(map_width, map_height, QgsUnitTypes.LayoutMillimeters))
                map_item.zoomToExtent(canvas.extent())
                layout.addLayoutItem(map_item)
                return f"已在 '{layout_name}' 补充地图"

            elif action_type == "add_legend":
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemLegend): return f"跳过重复图例。"
                legend = QgsLayoutItemLegend(layout)
                if map_item: legend.setLinkedMap(map_item)
                legend.setTitle("图例")
                legend.setAutoUpdateModel(True)
                layout.addLayoutItem(legend)
                
                # 强制重新计算以获取正确的宽高
                legend.adjustBoxSize()
                
                # 固定在地图右下角内侧
                if map_item:
                    # 使用地图项的位置和大小
                    map_pos = map_item.positionWithUnits()
                    map_size = map_item.sizeWithUnits()
                    
                    # 改变参考点为右下角 (8 = LowerRight)，确保图例的右下角绝对不会超出给定的坐标
                    legend.setReferencePoint(8)
                    
                    # 右下角坐标为地图的右下角向内缩 5 毫米
                    legend_x = map_pos.x() + map_size.width() - 5
                    legend_y = map_pos.y() + map_size.height() - 5
                    
                    legend.attemptMove(QgsLayoutPoint(legend_x, legend_y, QgsUnitTypes.LayoutMillimeters))
                return f"已添加图例"

            elif action_type == "add_scale_bar":
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemScaleBar): 
                        return f"跳过重复比例尺。"
                        
                scalebar = QgsLayoutItemScaleBar(layout)
                scalebar.setStyle('Single Box')
                if map_item: scalebar.setLinkedMap(map_item)
                
                # 设置单位和文本
                scalebar.setUnits(QgsUnitTypes.DistanceKilometers)
                scalebar.setUnitLabel("km")
                
                # 分段设置
                scalebar.setNumberOfSegments(4)
                scalebar.setNumberOfSegmentsLeft(0)
                
                # 动态与现有地图适配: 设置分段大小模式为 FitWidth (1)，随地图比例动态调整
                try:
                    scalebar.setSegmentSizeMode(1)
                    scalebar.setMinimumBarWidth(30)
                    scalebar.setMaximumBarWidth(100)
                except Exception:
                    pass
                
                # 确保单位显示在比例尺右边，尝试调整对齐方式
                try:
                    scalebar.setAlignment(2) # 2 = AlignRight
                except Exception:
                    pass
                
                # 保底：若上面没有完全生效，则应用一次默认计算
                scalebar.applyDefaultSize() 
                
                # 尝试调整文本格式 (QGIS 3 兼容方式)
                try:
                    from qgis.core import QgsTextFormat
                    text_format = QgsTextFormat()
                    text_format.setFont(QFont("Arial", 12))
                    scalebar.setTextFormat(text_format)
                except Exception:
                    pass # 忽略字体设置错误
                    
                scalebar.update()
                
                layout.addLayoutItem(scalebar)
                
                # 固定在地图左下角内侧
                if map_item:
                    map_pos = map_item.positionWithUnits()
                    map_size = map_item.sizeWithUnits()
                    
                    # 改变参考点为左下角 (6 = LowerLeft)，确保即使动态调整大小，其左下角位置固定
                    scalebar.setReferencePoint(6)
                    
                    scalebar_x = map_pos.x() + 5
                    scalebar_y = map_pos.y() + map_size.height() - 5
                    
                    scalebar.attemptMove(QgsLayoutPoint(scalebar_x, scalebar_y, QgsUnitTypes.LayoutMillimeters))
                
                return "已动态添加比例尺"

            elif action_type == "add_north_arrow":
                # 添加真实的指北针图片
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemPicture): return f"跳过重复指北针。"
                
                arrow = QgsLayoutItemPicture(layout)
                arrow.setMode(QgsLayoutItemPicture.FormatSVG)
                
                # 尝试获取 SVG 路径
                svg_paths = QgsApplication.svgPaths()
                svg_path = ""
                if svg_paths:
                    # 优先在常见目录寻找
                    for base_path in svg_paths:
                        test_path = os.path.join(base_path, "arrows", "NorthArrow_10.svg")
                        if os.path.exists(test_path):
                            svg_path = test_path
                            break
                    
                    if not svg_path:
                        # 兜底：随便找一个
                        test_path = os.path.join(svg_paths[0], "arrows", "NorthArrow_10.svg")
                        svg_path = test_path
                
                if svg_path:
                    arrow.setPicturePath(svg_path)
                layout.addLayoutItem(arrow)
                
                # 设定指北针的大小
                arrow.attemptResize(QgsLayoutSize(15, 15, QgsUnitTypes.LayoutMillimeters))
                
                # 固定在地图右上角内侧
                if map_item:
                    map_pos = map_item.positionWithUnits()
                    map_size = map_item.sizeWithUnits()
                    arrow_size = arrow.sizeWithUnits()
                    
                    arrow_x = map_pos.x() + map_size.width() - arrow_size.width() - 5
                    arrow_y = map_pos.y() + 5
                    
                    arrow.attemptMove(QgsLayoutPoint(arrow_x, arrow_y, QgsUnitTypes.LayoutMillimeters))
                return f"已添加指北针"

        return f"Error: 未知操作 {action_type}"

    except Exception as e:
        import traceback
        err_msg = str(e)
        full_trace = traceback.format_exc()
        QgsMessageLog.logMessage(f"Layout Management Error: {err_msg}\n{full_trace}", tag='AI_AGENT_DEBUG', level=Qgis.Critical)
        return f"Error: {err_msg}"