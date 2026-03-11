import json
import logging
import os
import time
from colorama import Fore
from .audio_manager import AudioManager

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLineEdit, QPushButton, QLabel, QFrame, QTextEdit,
    QSizePolicy, QGraphicsDropShadowEffect, QApplication
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize, QRect, QObject
from PyQt5.QtGui import QFont, QPainter, QPainterPath, QColor, QPixmap, QIcon
from qgis.utils import iface
from qgis.core import QgsProject, Qgis

from .chat_model import chat_with_openai
from .project_management import execute_project_task
from .layout_management import execute_layout_task
from .hotword_manager import QGISHotwordManager
from .workflow_graph import create_workflow_graph

INITIAL_MESSAGE = ("你好！我是你的QGIS智能AI助手，你可以向我提出用QGIS进行的任何操作。例如，你可以对我说：\n"
                   "1.将河流图层的样式设置为蓝色；\n"
                   "2.统计地铁站500m范围内的餐饮店数量；\n"
                   "3.绘制一幅湖北省水系图；\n")

os.environ['NO_PROXY'] = 'dashscope.aliyuncs.com'

# ---配置部分---
API_KEY = "sk-a2cddd46f8924031b2888c97c73c6e43"
MODEL_TYPE = "qwen-plus"
MODEL_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ROUND_LIMIT = 10


# --- 自定义气泡组件 ---
class ChatBubble(QWidget):
    def __init__(self, text, sender, avatar_path=None, parent=None, typing_effect=False):
        super().__init__(parent)
        self.sender = sender
        self.full_text = text
        self.avatar_path = avatar_path
        self.typing_effect = typing_effect
        self.current_text = ""
        self.init_ui()
        
        if self.typing_effect and sender == "ai":
            self.message_label.setText("")
            self.start_typing()
        else:
            self.message_label.setText(text)

    def init_ui(self):
        # 主布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        # 1. 头像区域
        avatar_label = QLabel()
        avatar_size = 26 # 缩小头像尺寸
        avatar_label.setFixedSize(avatar_size, avatar_size)
        
        # 加载头像
        if self.avatar_path and os.path.exists(self.avatar_path):
             pixmap = QPixmap(self.avatar_path)
        else:
             pixmap = QPixmap(avatar_size, avatar_size)
             pixmap.fill(QColor("#10a37f" if self.sender == "ai" else "#8e8e8e"))
        
        # 绘制圆形头像
        rounded = QPixmap(avatar_size, avatar_size)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, avatar_size, avatar_size)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, avatar_size, avatar_size, pixmap)
        painter.end()
        avatar_label.setPixmap(rounded)
        
        # 设置头像对齐方式 (顶部对齐，并增加一点上边距以对齐文字)
        avatar_container = QVBoxLayout()
        avatar_container.setContentsMargins(0, 2, 0, 0) #微调上边距
        avatar_container.addWidget(avatar_label)
        avatar_container.addStretch()

        # 2. 气泡内容容器
        bubble_frame = QFrame()
        bubble_layout = QVBoxLayout(bubble_frame)
        bubble_layout.setContentsMargins(12, 10, 12, 10)
        
        # 3. 消息文本标签
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setFont(QFont("Microsoft YaHei", 10))
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.message_label.setStyleSheet("border: none; background: transparent;")
        self.message_label.setTextFormat(Qt.PlainText)
        
        # 关键修改：设置 Label 的尺寸策略，使其能够正确换行和伸缩
        self.message_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        
        bubble_layout.addWidget(self.message_label)

        # 4. 根据发送者配置样式和布局
        if self.sender == "user":
            layout.addStretch()
            
            # 用户气泡样式
            bubble_frame.setStyleSheet("""
                QFrame {
                    background-color: #f0f0f0;
                    border-radius: 12px;
                    border-top-right-radius: 2px;
                }
            """)
            
            # 用户消息布局：气泡 + 头像
            layout.addWidget(bubble_frame, 1) # 伸缩因子设为1，允许伸缩但不强占
            
            # 为防止气泡过宽，限制最大宽度 (可选，但为了自适应最好不限)
            # layout.addLayout(avatar_container) # 用户头像可选，这里保留
            layout.addWidget(avatar_label) # 直接添加 Label 也可以
            
        else:
            # AI 气泡样式
            bubble_frame.setStyleSheet("""
                QFrame {
                    background-color: transparent;
                }
            """)
            
            # AI 消息布局：头像 + 气泡
            layout.addLayout(avatar_container)
            layout.addWidget(bubble_frame, 1) # 伸缩因子1，占据剩余空间
            layout.addStretch() # 右侧弹簧，确保靠左

    def start_typing(self):
        self.typing_timer = QTimer(self)
        self.typing_timer.timeout.connect(self.update_text)
        self.typing_timer.start(30) # 打字速度: 30ms/字

    def update_text(self):
        if len(self.current_text) < len(self.full_text):
            self.current_text += self.full_text[len(self.current_text)]
            self.message_label.setText(self.current_text)
            
            # 自动滚动到底部 (需要调用父级 ScrollArea 的滚动，这里尝试通过事件或回调)
            # 简单的做法是让 Label 更新 geometry
            self.message_label.adjustSize()
        else:
            self.typing_timer.stop()



# --- 折叠式步骤气泡 ---
class ProcessBubble(QWidget):
    def __init__(self, title, details, parent=None):
        super().__init__(parent)
        self.init_ui(title, details)

    def init_ui(self, title, details):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(42, 2, 10, 2)
        layout.setSpacing(5)

        # 折叠按钮 (作为标题)
        self.toggle_btn = QPushButton(f"▶ {title}")
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                color: #666;
                font-size: 11px;
                border: none;
                padding: 4px;
                background-color: #f9f9f9;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #f0f0f0; color: #333; }
        """)
        self.toggle_btn.clicked.connect(self.toggle_details)
        
        # 详情区域
        self.details_area = QLabel(details)
        self.details_area.setWordWrap(True)
        self.details_area.setFont(QFont("Consolas", 9))
        self.details_area.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details_area.setTextFormat(Qt.PlainText)
        self.details_area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        self.details_area.setStyleSheet("""
            color: #444; 
            padding: 10px; 
            background-color: #f9f9f9;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
        """)
        self.details_area.setVisible(False)
        
        layout.addWidget(self.toggle_btn)
        layout.addWidget(self.details_area)

    def toggle_details(self):
        visible = not self.details_area.isVisible()
        self.details_area.setVisible(visible)
        current_text = self.toggle_btn.text()
        arrow = "▼" if visible else "▶"
        title_part = current_text[2:] if len(current_text) > 2 else current_text
        self.toggle_btn.setText(f"{arrow} {title_part}")


# ---创建智能体工作小组处理工作线程---
class AgentsWorkgroupThread(QThread):
    """
        负责在后台运行的 LangGraph 工作小组逻辑
    """
    # 消息信号: (text, sender, msg_type)
    # sender: "user", "ai"
    # msg_type: "text" (普通), "step" (中间步骤), "success" (成功), "error" (错误)
    message_signal = pyqtSignal(str, str, str)
    
    error_signal = pyqtSignal(str)  # 严重错误信号
    remove_thinking_signal = pyqtSignal()  # 移除思考气泡信号
    create_msg_bar_signal = pyqtSignal(str)  # 创建消息栏信号
    refresh_map_canvas_signal = pyqtSignal()  # 刷新地图画布信号

    # 专门用于请求主线程执行项目操作的信号
    # 参数: (source_type, query_params)
    execute_project_signal = pyqtSignal(str, dict)
    # 用于传递布局任务列表的信号
    layout_task_signal = pyqtSignal(list)
    # 停止信号
    stop_signal = pyqtSignal()

    def __init__(self, user_text, layers, parent=None):
        super().__init__(parent)
        self.user_text = user_text
        self.layers = layers
        # 用于接收主线程执行结果的变量
        self.project_op_result = None
        self._is_stopped = False

    def stop(self):
        """停止线程任务"""
        self._is_stopped = True
        self.stop_signal.emit()

    # 供 LangGraph Node 调用的执行器方法
    def execute_project_op(self, source_type, query_params):
        """执行项目操作（需在主线程运行）"""
        if self._is_stopped: return "任务已停止"
        
        self.project_op_result = None
        self.execute_project_signal.emit(source_type, query_params)
        
        # 阻塞等待结果
        while self.project_op_result is None:
            if self._is_stopped: return "任务已停止"
            self.msleep(50)
            
        return self.project_op_result

    def execute_layout_op(self, tasks):
        """执行布局操作（需在主线程运行）"""
        if self._is_stopped: return "任务已停止"
        
        # 发送布局任务信号
        self.layout_task_signal.emit(tasks)
        
        return "布局任务已发送至主线程执行。"
        
    def refresh_layers(self):
        """刷新并返回最新的图层列表"""
        if self._is_stopped: return []
        # 触发主线程刷新（UI）
        self.refresh_map_canvas_signal.emit()
        # 获取最新图层（注意：QgsProject 实例在多线程访问可能不安全，但读取通常还好）
        self.layers = list(QgsProject.instance().mapLayers().values())
        return self.layers

    # 运行智能体工作小组
    def run(self):
        # 创建 Workflow Graph
        app = create_workflow_graph()

        # 初始状态
        inputs = {
            "user_request": self.user_text,
            "layers": self.layers,
            "task_plan": [],
            "current_step": 0,
            "current_task": "",
            "assigned_agent": "",
            "execution_result": None,
            "error": "",
            "is_gis_task": True,
            "executor": self
        }

        try:
            # 使用 stream 模式运行
            for event in app.stream(inputs):
                if self._is_stopped:
                    self.message_signal.emit("用户已手动停止流程。", "ai", "text")
                    self.remove_thinking_signal.emit()
                    return

                # event 是一个字典，key 是节点名，value 是该节点输出的状态更新
                for node_name, state_update in event.items():
                    if self._is_stopped:
                        self.message_signal.emit("用户已手动停止流程。", "ai", "text")
                        self.remove_thinking_signal.emit()
                        return
                        
                    # 检查是否有错误
                    if "error" in state_update and state_update["error"]:
                        self.error_signal.emit(state_update["error"])
                        return # 终止

                    # 处理 TaskPlanner 输出
                    if node_name == "task_planner":
                        self.remove_thinking_signal.emit()
                        if not state_update.get("is_gis_task", True):
                            ai_response = chat_with_openai(self.user_text)
                            if "聊天接口报错:" in ai_response:
                                self.error_signal.emit(ai_response)
                            else:
                                self.message_signal.emit(ai_response, "ai", "text")
                            return # 结束

                        task_plan = state_update.get("task_plan", [])
                        
                        # 显示计划
                        self.message_signal.emit(f"Planner Output:\n{json.dumps(task_plan, indent=2, ensure_ascii=False)}", "ai", "step")

                    # 处理 TaskRouter 输出
                    elif node_name == "task_router":
                        task = state_update.get("current_task")
                        step_idx = state_update.get("current_step", 0)
                        # 显示正在执行
                        self.message_signal.emit(f"正在执行第{step_idx+1}步：{task}", "ai", "text")

                    # 处理 AgentExecutor 输出
                    elif node_name == "agent_executor":
                        result = state_update.get("execution_result", {})
                        if result.get("is_process_complete"):
                            tool_result = result.get("tool_result", "完成")
                            self.message_signal.emit(f"步骤执行完成！\n详情: {tool_result}", "ai", "step")
                            self.refresh_map_canvas_signal.emit()
                        else:
                            prob = result.get("possible_problem", "未知错误")
                            self.message_signal.emit(f"步骤执行遇到问题: {prob}", "ai", "text")
                            # 这里可以选择终止或继续，workflow_graph 默认会根据 conditional_edge 终止或抛错
                            
            # 循环结束，检查最终状态
            if not self._is_stopped:
                self.message_signal.emit("任务流程结束。", "ai", "text")

        except Exception as e:
            if not self._is_stopped:
                self.error_signal.emit(f"流程异常终止：{e}")


class ChatBox(QObject):
    """
    逻辑控制器类
    不再是 QWidget，而是管理从 .ui 文件加载的控件
    """
    
    def __init__(self, dock_widget):
        super().__init__()
        self.dock_widget = dock_widget
        
        # 绑定 UI 控件
        self.scrollArea = dock_widget.scrollArea
        self.user_inputBox = dock_widget.user_inputBox
        self.send_button = dock_widget.send_button
        self.voice_btn = dock_widget.voice_btn
        # 新增 stop_button 绑定
        self.stop_button = dock_widget.stop_button
        
        # 获取 chat_container 布局 (在 .ui 中是 scrollAreaWidgetContents)
        self.chat_container = dock_widget.scrollAreaWidgetContents
        # 获取或设置布局
        if self.chat_container.layout() is None:
            self.chat_layout = QVBoxLayout(self.chat_container)
            self.chat_layout.setAlignment(Qt.AlignTop)
            self.chat_layout.setSpacing(20)
            self.chat_layout.setContentsMargins(20, 20, 20, 20)
        else:
            self.chat_layout = self.chat_container.layout()
            self.chat_layout.setAlignment(Qt.AlignTop)

        # 初始化状态
        self.ai_thinking_bubble = None
        self.agents_workgroup = None

        # 连接信号槽
        self.setup_connections()
        
        # 初始化音频管理器
        self.init_audio()

    def setup_connections(self):
        # 监控输入框高度变化 (模拟 auto-height)
        self.user_inputBox.textChanged.connect(self.adjust_input_height)
        
        # 监控 Enter 键发送
        # QTextEdit 没有 returnPressed 信号，需要事件过滤器
        self.user_inputBox.installEventFilter(self)
        
        # 发送按钮
        self.send_button.clicked.connect(self.send_message)
        
        # 停止按钮
        self.stop_button.clicked.connect(self.stop_process)

    def init_audio(self):
        # 初始化音频管理器
        self.audio_manager = AudioManager(api_key=API_KEY)
        self.audio_manager.transcription_ready.connect(self.on_voice_text_received)
        self.audio_manager.error_occurred.connect(self.on_voice_error)
        self.audio_manager.recording_started.connect(self.on_recording_started)
        self.audio_manager.recording_stopped.connect(self.on_recording_stopped)

        # 创建热词管理器，并传入音频管理器
        self.hotword_manager = QGISHotwordManager()
        self.audio_manager.set_hotword_manager(self.hotword_manager)

        # 绑定按住/松开事件
        self.voice_btn.pressed.connect(self.audio_manager.start_recording)
        self.voice_btn.released.connect(self.audio_manager.stop_recording)

    def eventFilter(self, obj, event):
        if obj == self.user_inputBox and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Return:
                if event.modifiers() & Qt.ShiftModifier:
                    # Shift+Enter: 换行，不做处理，默认行为
                    return False
                else:
                    # Enter: 发送
                    self.send_message()
                    return True  # 拦截事件
        return super().eventFilter(obj, event)

    def adjust_input_height(self):
        doc_height = self.user_inputBox.document().size().height()
        new_height = min(max(40, doc_height + 10), 100)
        self.user_inputBox.setFixedHeight(int(new_height))

    # --- 生成对话气泡 ---
    def add_message(self, text, sender="user", msg_type="text", typing_effect=False):
        """
        添加消息到聊天窗口
        :param text: 消息内容
        :param sender: 发送者 ("user" 或 "ai")
        :param msg_type: 消息类型 ("text", "step", "error" 等)
        :param typing_effect: 是否启用打字机效果
        """
        # 确定头像路径
        avatar_path = None
        if sender == "ai":
            avatar_path = os.path.join(os.path.dirname(__file__), "icon.png")
        
        if msg_type == "step":
            lines = text.split('\n', 1)
            title = lines[0]
            details = lines[1] if len(lines) > 1 else text
            bubble = ProcessBubble(title, details)
        else:
            bubble = ChatBubble(text, sender, avatar_path, typing_effect=typing_effect)

        self.chat_layout.addWidget(bubble)

        # 自动滚动到底部
        QTimer.singleShot(10, lambda: self.scrollArea.verticalScrollBar().setValue(
            self.scrollArea.verticalScrollBar().maximum()
        ))
        return bubble

    # --- 发送消息事件 ---
    def send_message(self):
        user_text = self.user_inputBox.toPlainText().strip()
        if not user_text:
            return

        # 1. 显示用户输入
        self.add_message(user_text, "user")
        self.user_inputBox.clear()

        # 2. 获取当前QGIS项目中的图层
        layers = list(QgsProject.instance().mapLayers().values())

        # 3. 显示思考状态 (不使用打字机效果)
        self.ai_thinking_bubble = self.add_message("正在思考中...", "ai", typing_effect=False)

        # 4. 更新UI状态：隐藏发送按钮，显示停止按钮
        self.send_button.setVisible(False)
        self.stop_button.setVisible(True)

        # 5. 实例化并启动工作小组工作线程
        self.agents_workgroup = AgentsWorkgroupThread(user_text, layers)

        # 6. 连接信号到槽函数
        self.agents_workgroup.message_signal.connect(self.receive_ai_message)  # 处理消息
        self.agents_workgroup.error_signal.connect(self.process_error)  # 处理错误
        self.agents_workgroup.remove_thinking_signal.connect(self.remove_thinking_bubble)  # 移除气泡
        self.agents_workgroup.create_msg_bar_signal.connect(create_msg_bar)  # 创建消息栏
        self.agents_workgroup.finished.connect(self.agents_workgroup.deleteLater)
        self.agents_workgroup.finished.connect(self.on_thread_finished) # 线程结束恢复UI
        self.agents_workgroup.refresh_map_canvas_signal.connect(self.refresh_map_canvas)  # 刷新地图画布
        self.agents_workgroup.execute_project_signal.connect(self.handle_project_execution)
        self.agents_workgroup.layout_task_signal.connect(self.handle_layout_tasks)

        # 7. 启动线程
        self.agents_workgroup.start()

    def stop_process(self):
        """用户点击停止按钮"""
        if self.agents_workgroup and self.agents_workgroup.isRunning():
            self.agents_workgroup.stop()
            # UI 更新将在 thread finished 信号中处理
            # 但为了即时反馈，禁用按钮
            self.stop_button.setEnabled(False)

    def on_thread_finished(self):
        """线程结束时的清理工作"""
        self.stop_button.setVisible(False)
        self.stop_button.setEnabled(True)
        self.send_button.setVisible(True)
        self.remove_thinking_bubble()
        self.agents_workgroup = None

    # ---槽函数：在主线程执行项目操作---
    def handle_project_execution(self, source_type, params):
        try:
            result = execute_project_task(source_type, params)
        except Exception as e:
            result = f"Error: 主线程执行异常: {str(e)}"
        if self.agents_workgroup:
            self.agents_workgroup.project_op_result = result

    # 槽函数：在主线程安全地操作 QGIS 界面 ---
    def handle_layout_tasks(self, tasks):
        results = []
        for req in tasks:
            res_msg = execute_layout_task(req)
            results.append(res_msg)
        final_msg = " | ".join(results)
        self.add_message(f"布局操作执行结果：\n{final_msg}", "ai")
        self.refresh_map_canvas()

    # ---槽函数：接收线程结果---
    def receive_ai_message(self, text, sender, msg_type="text"):
        # 确保 msg_type 有默认值，虽然信号通常会传所有参数
        # 仅对 AI 的普通文本消息启用打字机效果
        typing = (sender == "ai" and msg_type == "text")
        self.add_message(text, sender, msg_type, typing_effect=typing)

    # ---槽函数：接收线程错误信息---
    def process_error(self, err_msg):
        self.remove_thinking_bubble()
        create_msg_bar(err_msg, Qgis.Info)
        self.add_message(f"任务执行出错: {err_msg}", "ai")

    def remove_thinking_bubble(self):
        if self.ai_thinking_bubble:
            self.ai_thinking_bubble.deleteLater()
            self.ai_thinking_bubble = None

    def show_initial_message(self):
        self.add_message(INITIAL_MESSAGE, "ai")
        # 强制更新布局
        self.chat_container.update()
        self.scrollArea.update()
        QTimer.singleShot(50, lambda: self.scrollArea.verticalScrollBar().setValue(
            self.scrollArea.verticalScrollBar().maximum()
        ))

    # 槽函数：刷新地图画布
    def refresh_map_canvas(self):
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()

    def on_recording_started(self):
        self.voice_btn.setStyleSheet("background-color: #ffcccc; border-radius: 16px; border: 1px solid red;")
        self.user_inputBox.setPlaceholderText("正在听...")

    def on_recording_stopped(self):
        self.voice_btn.setStyleSheet("background-color: transparent; border-radius: 16px; color: #666666;")
        self.user_inputBox.setPlaceholderText("给QGIS AI发送消息...")
        self.user_inputBox.setEnabled(False)

    def on_voice_text_received(self, text):
        self.user_inputBox.setReadOnly(False)
        self.user_inputBox.setEnabled(True)
        self.user_inputBox.setPlainText(text)
        cursor = self.user_inputBox.textCursor()
        cursor.movePosition(cursor.End)
        self.user_inputBox.setTextCursor(cursor)

    def on_voice_error(self, error_msg):
        self.user_inputBox.setReadOnly(False)
        self.user_inputBox.setEnabled(True)
        self.user_inputBox.setPlaceholderText(f"错误: {error_msg}")


def create_msg_bar(msg, level=Qgis.Info):
    bar = iface.messageBar()
    widget = bar.createMessage("AI助手", msg)
    bar.pushWidget(widget, level, 7)
