"""视频关键帧标注工具"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MARKERS = ("pick_start", "drink_start", "drink_end", "pick_end")
MARKER_LABELS = ("pick start", "drink start", "drink end", "pick end")
CONTAINER_TYPES = ("", "plastic bottle", "paper cup small", "paper cup large")
TABLE_HEADERS = ("No.", "pick start", "drink start", "drink end", "pick end", "container type")


@dataclass
class FramePoint:
    second: int
    frame: int

    def display(self) -> str:
        return f"{self.second},{self.frame}"


@dataclass
class DrinkAnnotation:
    identifier: int
    points: dict[str, Optional[FramePoint]] = field(
        default_factory=lambda: {marker: None for marker in MARKERS}
    )
    container_type: str = ""

    def is_complete(self) -> bool:
        return all(self.points[marker] is not None for marker in MARKERS)


@dataclass
class ClickAction:
    annotation_id: int
    marker_index: int
    previous_value: Optional[FramePoint]
    new_value: FramePoint


def natural_sort_key(path: Path) -> list[tuple[int, object]]:
    """按数字片段进行自然排序，文件名仅用于顺序而不用于 second。"""
    # 数字与文本带类型标签，确保诸如 "1.jpg" 和 "a.jpg" 混排时也不会
    # 因为直接比较 int / str 而报错。
    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", path.name)
    ]


def parse_point(text: str) -> Optional[FramePoint]:
    """解析表格标记；空值用于清空未完成/已有标记。"""
    cleaned = text.strip()
    if not cleaned:
        return None
    match = re.fullmatch(r"(\d+)\s*,\s*(\d+)", cleaned)
    if not match:
        raise ValueError("请输入 second,frame，例如：12,17")
    second, frame = (int(value) for value in match.groups())
    if frame > 29:
        raise ValueError("frame 必须在 0 到 29 之间。")
    return FramePoint(second, frame)


class FrameGridView(QGraphicsView):
    """在原始图像 scene 坐标中展示 5×6 网格并返回被点中的 frame。"""

    frame_clicked = Signal(int)
    frame_hovered = Signal(object)
    image_scrolled = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setStyleSheet("background: #303030; border: 1px solid #777;")

        self.image_width = 0.0
        self.image_height = 0.0
        self._hover_item: Optional[QGraphicsRectItem] = None
        self._last_click_item: Optional[QGraphicsRectItem] = None
        self._placeholder: Optional[QGraphicsSimpleTextItem] = None
        self.show_placeholder("请选择图片文件夹")

    def show_placeholder(self, message: str) -> None:
        self.scene.clear()
        self.image_width = self.image_height = 0.0
        self._hover_item = None
        self._last_click_item = None
        text = self.scene.addSimpleText(message)
        text.setBrush(QColor("#dddddd"))
        font = text.font()
        font.setPointSize(16)
        text.setFont(font)
        text.setPos(-text.boundingRect().width() / 2, -text.boundingRect().height() / 2)
        self.scene.setSceneRect(-200, -50, 400, 100)
        self._placeholder = text
        self.fit_image()

    def set_image(self, pixmap: QPixmap) -> None:
        self.scene.clear()
        self._placeholder = None
        self.image_width = float(pixmap.width())
        self.image_height = float(pixmap.height())
        self.scene.addItem(QGraphicsPixmapItem(pixmap))
        self.scene.setSceneRect(0, 0, self.image_width, self.image_height)
        self._draw_grid()
        self._hover_item = self._create_cell_item(QColor(255, 230, 0, 70), QPen(QColor("#ffe600"), 2))
        self._last_click_item = self._create_cell_item(QColor(0, 170, 255, 35), QPen(QColor("#00aaff"), 4))
        self._hover_item.hide()
        self._last_click_item.hide()
        self.fit_image()

    def _draw_grid(self) -> None:
        pen = QPen(QColor("#00ff99"), 2)
        pen.setCosmetic(True)
        for column in range(6):
            x = self.image_width * column / 5
            self.scene.addLine(x, 0, x, self.image_height, pen)
        for row in range(7):
            y = self.image_height * row / 6
            self.scene.addLine(0, y, self.image_width, y, pen)

        font_size = max(9.0, min(24.0, min(self.image_width / 5, self.image_height / 6) / 8))
        font = QFont()
        font.setPointSizeF(font_size)
        for row in range(6):
            for column in range(5):
                number = row * 5 + column
                label = self.scene.addSimpleText(str(number), font)
                label.setBrush(QColor("white"))
                label.setPos(self.image_width * column / 5 + 5, self.image_height * row / 6 + 3)
                label.setZValue(2)

    def _create_cell_item(self, color: QColor, pen: QPen) -> QGraphicsRectItem:
        item = QGraphicsRectItem()
        item.setBrush(color)
        item.setPen(pen)
        item.setZValue(3)
        self.scene.addItem(item)
        return item

    def fit_image(self) -> None:
        if self.scene.sceneRect().isNull():
            return
        self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self.fit_image()

    def _frame_at(self, position) -> Optional[int]:  # type: ignore[no-untyped-def]
        if self.image_width <= 0 or self.image_height <= 0:
            return None
        # QMouseEvent.position() 在 Qt 6 中是 QPointF，而 QGraphicsView 的
        # mapToScene 重载接受 QPoint；直接传入会在真实点击时抛出 TypeError。
        if hasattr(position, "toPoint"):
            position = position.toPoint()
        scene_position = self.mapToScene(position)
        x, y = scene_position.x(), scene_position.y()
        # 将最右/下边缘视作图片边缘并夹紧；其余 scene 留白不属于图片。
        if x < 0 or y < 0 or x > self.image_width or y > self.image_height:
            return None
        column = min(int(x * 5 / self.image_width), 4)
        row = min(int(y * 6 / self.image_height), 5)
        return row * 5 + column

    def _set_item_to_frame(self, item: Optional[QGraphicsRectItem], frame: int) -> None:
        if item is None:
            return
        row, column = divmod(frame, 5)
        x0 = self.image_width * column / 5
        y0 = self.image_height * row / 6
        x1 = self.image_width * (column + 1) / 5
        y1 = self.image_height * (row + 1) / 6
        item.setRect(x0, y0, x1 - x0, y1 - y0)
        item.show()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        frame = self._frame_at(event.position())
        if frame is None:
            if self._hover_item is not None:
                self._hover_item.hide()
        else:
            self._set_item_to_frame(self._hover_item, frame)
        self.frame_hovered.emit(frame)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._hover_item is not None:
            self._hover_item.hide()
        self.frame_hovered.emit(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            frame = self._frame_at(event.position())
            if frame is not None:
                self._set_item_to_frame(self._last_click_item, frame)
                self.frame_clicked.emit(frame)
                event.accept()
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """图片区域内滚轮切图：上滚上一张，下滚下一张。"""
        delta = event.angleDelta().y()
        if delta > 0:
            self.image_scrolled.emit(-1)
            event.accept()
            return
        if delta < 0:
            self.image_scrolled.emit(1)
            event.accept()
            return
        super().wheelEvent(event)

    def show_last_click(self, frame: Optional[int]) -> None:
        if self._last_click_item is None:
            return
        if frame is None:
            self._last_click_item.hide()
        else:
            self._set_item_to_frame(self._last_click_item, frame)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("视频关键帧标注工具")
        self.resize(1200, 760)
        self.image_paths: list[Path] = []
        self.current_image_index = -1
        self.annotations: list[DrinkAnnotation] = []
        self.next_annotation_id = 1
        self.active_annotation_id: Optional[int] = None
        self.next_marker_index = 0
        self.click_history: list[ClickAction] = []
        self.last_click: Optional[FramePoint] = None
        self.dirty = False
        self._updating_table = False

        self._build_ui()
        self._build_actions()
        self._update_navigation()
        self._update_next_marker()

    def _build_ui(self) -> None:
        self.choose_button = QPushButton("选择文件夹")
        self.choose_button.clicked.connect(self.choose_folder)
        self.file_label = QLabel("文件名：—")
        self.image_label = QLabel("图片：—")
        self.second_label = QLabel("秒数：—")
        self.next_marker_label = QLabel()
        self.next_marker_label.setStyleSheet("font-weight: bold; padding: 5px;")

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.choose_button)
        top_layout.addSpacing(12)
        top_layout.addWidget(self.file_label, 1)
        top_layout.addWidget(self.image_label)
        top_layout.addWidget(self.second_label)

        self.viewer = FrameGridView()
        self.viewer.frame_clicked.connect(self.handle_frame_click)
        self.viewer.image_scrolled.connect(self.change_image)

        self.previous_button = QPushButton("上一张")
        self.next_button = QPushButton("下一张")
        self.previous_button.clicked.connect(lambda: self.change_image(-1))
        self.next_button.clicked.connect(lambda: self.change_image(1))
        image_controls = QHBoxLayout()
        image_controls.addWidget(self.previous_button)
        image_controls.addWidget(self.next_button)
        image_controls.addStretch()
        image_controls.addWidget(self.next_marker_label)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.viewer, 1)
        left_layout.addLayout(image_controls)

        self.table = QTableWidget(0, len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(TABLE_HEADERS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self.handle_table_change)

        self.undo_button = QPushButton("撤销上一次点击")
        self.delete_button = QPushButton("删除选中行")
        self.export_button = QPushButton("导出 CSV")
        self.undo_button.clicked.connect(self.undo_last_click)
        self.delete_button.clicked.connect(self.delete_selected_rows)
        self.export_button.clicked.connect(self.export_csv)
        table_controls = QVBoxLayout()
        table_controls.addWidget(self.undo_button)
        table_controls.addWidget(self.delete_button)
        table_controls.addWidget(self.export_button)
        table_controls.addStretch()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.table, 1)
        right_layout.addLayout(table_controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([840, 360])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top_layout)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

    def _build_actions(self) -> None:
        choose_action = QAction(self)
        choose_action.setShortcut(QKeySequence.StandardKey.Open)
        choose_action.triggered.connect(self.choose_folder)
        self.addAction(choose_action)
        undo_action = QAction(self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.undo_last_click)
        self.addAction(undo_action)
        export_action = QAction(self)
        export_action.setShortcut(QKeySequence.StandardKey.Save)
        export_action.triggered.connect(self.export_csv)
        self.addAction(export_action)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        # 表格编辑时保留左右键给文本编辑器使用。
        if self.table.state() == QTableWidget.State.EditingState:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_Left:
            self.change_image(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self.change_image(1)
            event.accept()
            return
        super().keyPressEvent(event)

    def choose_folder(self) -> None:
        folder_name = QFileDialog.getExistingDirectory(self, "选择拼图图片文件夹")
        if not folder_name:
            return
        if self.dirty and self.annotations:
            answer = QMessageBox.question(
                self,
                "切换文件夹",
                "当前存在未导出的标注数据。切换文件夹会清空这些数据，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        paths = sorted(
            (path for path in Path(folder_name).iterdir() if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS),
            key=natural_sort_key,
        )
        if not paths:
            QMessageBox.information(self, "未找到图片", "未找到可读取的图片文件。")
            return
        self.image_paths = paths
        self.current_image_index = 0
        self.annotations.clear()
        self.click_history.clear()
        self.active_annotation_id = None
        self.next_marker_index = 0
        self.last_click = None
        self.dirty = False
        self.render_table()
        self.show_current_image()

    def show_current_image(self) -> None:
        if not (0 <= self.current_image_index < len(self.image_paths)):
            self.viewer.show_placeholder("请选择图片文件夹")
            self.file_label.setText("文件名：—")
            self.image_label.setText("图片：—")
            self.second_label.setText("秒数：—")
            self._update_navigation()
            return
        path = self.image_paths[self.current_image_index]
        pixmap = QPixmap(str(path))
        self.file_label.setText(f"文件名：{path.name}")
        self.image_label.setText(f"图片：{self.current_image_index + 1} / {len(self.image_paths)}")
        self.second_label.setText(f"秒数：{self.current_image_index}")
        if pixmap.isNull():
            self.viewer.show_placeholder("无法读取图片")
            QMessageBox.warning(self, "无法读取图片", f"无法读取图片：\n{path.name}")
        else:
            self.viewer.set_image(pixmap)
            point = self.last_click if self.last_click and self.last_click.second == self.current_image_index else None
            self.viewer.show_last_click(point.frame if point else None)
        self._update_navigation()

    def change_image(self, offset: int) -> None:
        if not self.image_paths:
            return
        new_index = max(0, min(self.current_image_index + offset, len(self.image_paths) - 1))
        if new_index != self.current_image_index:
            self.current_image_index = new_index
            self.show_current_image()

    def _update_navigation(self) -> None:
        has_images = bool(self.image_paths)
        self.previous_button.setEnabled(has_images and self.current_image_index > 0)
        self.next_button.setEnabled(has_images and self.current_image_index < len(self.image_paths) - 1)
        self.undo_button.setEnabled(bool(self.click_history))

    def _find_annotation(self, identifier: int) -> Optional[DrinkAnnotation]:
        return next((annotation for annotation in self.annotations if annotation.identifier == identifier), None)

    def _active_annotation(self) -> Optional[DrinkAnnotation]:
        return self._find_annotation(self.active_annotation_id) if self.active_annotation_id is not None else None

    def _create_annotation(self) -> DrinkAnnotation:
        annotation = DrinkAnnotation(self.next_annotation_id)
        self.next_annotation_id += 1
        self.annotations.append(annotation)
        self.active_annotation_id = annotation.identifier
        self.next_marker_index = 0
        return annotation

    def handle_frame_click(self, frame: int) -> None:
        if not (0 <= self.current_image_index < len(self.image_paths)):
            return
        annotation = self._active_annotation() or self._create_annotation()
        marker = MARKERS[self.next_marker_index]
        point = FramePoint(self.current_image_index, frame)
        previous = annotation.points[marker]
        annotation.points[marker] = point
        self.click_history.append(ClickAction(annotation.identifier, self.next_marker_index, previous, point))
        self.last_click = point
        self.dirty = True
        self.next_marker_index += 1
        if self.next_marker_index == len(MARKERS):
            self.active_annotation_id = None
            self.next_marker_index = 0
        self.render_table()
        self._update_next_marker()
        self._update_navigation()

    def _update_next_marker(self) -> None:
        index = self.next_marker_index
        self.next_marker_label.setText(f"下一标记：{MARKER_LABELS[index]}（{index + 1} / 4）")

    def render_table(self) -> None:
        self._updating_table = True
        self.table.setRowCount(len(self.annotations))
        for row, annotation in enumerate(self.annotations):
            number = QTableWidgetItem(str(row + 1))
            number.setFlags(number.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, number)
            for column, marker in enumerate(MARKERS, start=1):
                point = annotation.points[marker]
                self.table.setItem(row, column, QTableWidgetItem(point.display() if point else ""))
            container_combo = QComboBox()
            container_combo.addItems(CONTAINER_TYPES)
            container_combo.setCurrentText(annotation.container_type)
            container_combo.currentTextChanged.connect(
                lambda value, identifier=annotation.identifier: self.handle_container_type_change(identifier, value)
            )
            self.table.setCellWidget(row, len(TABLE_HEADERS) - 1, container_combo)
        self._updating_table = False

    def handle_table_change(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.column() == 0 or item.column() >= len(MARKERS) + 1:
            return
        row = item.row()
        if not (0 <= row < len(self.annotations)):
            return
        marker = MARKERS[item.column() - 1]
        old_value = self.annotations[row].points[marker]
        try:
            new_value = parse_point(item.text())
        except ValueError as error:
            self._updating_table = True
            item.setText(old_value.display() if old_value else "")
            self._updating_table = False
            QMessageBox.warning(self, "输入无效", str(error))
            return
        self.annotations[row].points[marker] = new_value
        cleaned = new_value.display() if new_value else ""
        if item.text() != cleaned:
            self._updating_table = True
            item.setText(cleaned)
            self._updating_table = False
        self.dirty = True

    def handle_container_type_change(self, annotation_id: int, container_type: str) -> None:
        """容器类型独立于图片点击状态和图片点击撤销历史。"""
        if self._updating_table or container_type not in CONTAINER_TYPES:
            return
        annotation = self._find_annotation(annotation_id)
        if annotation is None or annotation.container_type == container_type:
            return
        annotation.container_type = container_type
        self.dirty = True

    def undo_last_click(self) -> None:
        if not self.click_history:
            return
        action = self.click_history.pop()
        annotation = self._find_annotation(action.annotation_id)
        if annotation is None:  # 删除行后历史已过滤，此处为保护。
            return
        annotation.points[MARKERS[action.marker_index]] = action.previous_value
        self.active_annotation_id = annotation.identifier
        self.next_marker_index = action.marker_index
        self.last_click = action.previous_value
        self.dirty = True
        self.render_table()
        self._update_next_marker()
        if self.current_image_index >= 0:
            point = self.last_click if self.last_click and self.last_click.second == self.current_image_index else None
            self.viewer.show_last_click(point.frame if point else None)
        self._update_navigation()

    def delete_selected_rows(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        if not rows:
            QMessageBox.information(self, "删除标注", "请先选中要删除的行。")
            return
        deleted_ids = {self.annotations[row].identifier for row in rows if 0 <= row < len(self.annotations)}
        self.annotations = [annotation for annotation in self.annotations if annotation.identifier not in deleted_ids]
        self.click_history = [action for action in self.click_history if action.annotation_id not in deleted_ids]
        if self.active_annotation_id in deleted_ids:
            self.active_annotation_id = None
            self.next_marker_index = 0
        self.dirty = True
        self.render_table()
        self._update_next_marker()
        self._update_navigation()

    def export_csv(self) -> None:
        if any(not annotation.is_complete() for annotation in self.annotations):
            answer = QMessageBox.question(
                self,
                "存在未完成标注",
                "当前存在未完成的标注行，是否仍然导出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        file_name, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "annotations.csv", "CSV 文件 (*.csv)")
        if not file_name:
            return
        try:
            with open(file_name, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(TABLE_HEADERS)
                for number, annotation in enumerate(self.annotations, start=1):
                    writer.writerow(
                        [number]
                        + [annotation.points[marker].display() if annotation.points[marker] else "" for marker in MARKERS]
                        + [annotation.container_type]
                    )
        except OSError as error:
            QMessageBox.warning(self, "导出失败", f"无法导出 CSV：\n{error}")
            return
        self.dirty = False
        QMessageBox.information(self, "导出完成", f"CSV 已导出：\n{file_name}")

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.dirty and self.annotations:
            answer = QMessageBox.question(
                self,
                "确认退出",
                "当前存在未导出的标注数据，是否确认退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


def main() -> int:
    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
