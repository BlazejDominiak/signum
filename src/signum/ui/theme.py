"""Quiet, compact desktop surfaces and category markers."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

CATEGORY_COLORS = (
    ("#426A92", "#EFF3F7"), ("#52755D", "#EFF4F0"),
    ("#7B6895", "#F2F0F5"), ("#94783E", "#F7F4ED"),
    ("#4E7B88", "#EFF4F5"), ("#966879", "#F5F0F2"),
    ("#626994", "#F0F1F5"), ("#53817D", "#EFF5F4"),
    ("#9A7255", "#F6F2EF"), ("#677585", "#F1F3F5"),
    ("#8A6E8A", "#F4F0F4"), ("#707070", "#F3F3F3"),
)

SIGNUM_STYLE = """
QMainWindow, QDialog, QWidget#classificationPanel { background: #F3F3F3; }
QWidget { color: #252525; font-family: 'Segoe UI'; font-size: 13px; }
QLabel { background: transparent; }
QLabel[role='title'] { font-size: 18px; font-weight: 600; }
QLabel[role='heading'] { font-size: 13px; font-weight: 600; }
QLabel[role='muted'], QLabel[role='badge'] { color: #616161; }
QWidget[role='card'], QScrollArea#signatureDetailsScroll {
    background: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 0; }
QWidget[role='commandBar'] { background: #FAFAFA; border: 0;
    border-bottom: 1px solid #D4D4D4; }
QWidget[role='metric'] { background: #FAFAFA; border: 0;
    border-right: 1px solid #D4D4D4; }
QLabel[role='metricValue'] { font-size: 17px; font-weight: 600; }
QPushButton, QToolButton { background: #FAFAFA; border: 1px solid #B8B8B8;
    border-radius: 2px; padding: 5px 10px; font-weight: 400; }
QPushButton:hover, QToolButton:hover { background: #E5EDF5; border-color: #7C9BB9; }
QPushButton:pressed, QToolButton:pressed, QPushButton:checked {
    background: #D5E3F0; border-color: #6C8FAF; }
QPushButton:focus, QToolButton:focus { border-color: #315F8A; }
QPushButton:disabled, QToolButton:disabled { color: #808080;
    background: #F3F3F3; border-color: #D4D4D4; }
QPushButton[role='primary'] { background: #315F8A; color: white; border-color: #315F8A; }
QPushButton[role='primary']:hover { background: #254C70; }
QPushButton[role='primary']:disabled { background: #D1DAE3; color: #687887;
    border-color: #D1DAE3; }
QPushButton[role='quiet'] { background: transparent; border-color: transparent; }
QPushButton[role='quiet']:hover, QPushButton[role='quiet']:checked {
    background: #E5EDF5; border-color: #C0CDDA; }
QComboBox, QSpinBox, QLineEdit, QPlainTextEdit { background: white;
    border: 1px solid #B8B8B8; border-radius: 0; padding: 4px; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {
    border-color: #315F8A; }
QTableWidget { background: white; alternate-background-color: #FAFAFA;
    border: 0; selection-background-color: #DCE8F3; selection-color: #252525;
    gridline-color: #E8E8E8; }
QTableWidget::item { padding: 4px; border-bottom: 1px solid #EEEEEE; }
QTableWidget::item:focus { border: 1px solid #7898B7; }
QHeaderView::section { background: #F5F5F5; color: #515151; border: 0;
    border-right: 1px solid #E0E0E0; border-bottom: 1px solid #D4D4D4;
    padding: 6px; font-weight: 400; }
QTableCornerButton::section { background: #F5F5F5; border: 0; }
QTabWidget::pane { border: 0; border-top: 1px solid #C9C9C9; background: #F3F3F3; }
QTabBar::tab { background: #F3F3F3; color: #444444; padding: 9px 20px;
    border: 0; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #244F78; border-bottom-color: #315F8A; font-weight: 600; }
QTabBar::tab:hover { background: #E5E5E5; }
QSplitter::handle { background: #E9E9E9; }
QSplitter::handle:hover { background: #C6D6E5; }
QProgressBar { background: #DEDEDE; border: 0; border-radius: 0;
    min-height: 3px; max-height: 3px; }
QProgressBar::chunk { background: #315F8A; }
QToolBar { background: #FAFAFA; border: 0; padding: 4px; spacing: 4px; }
QStatusBar { background: #F3F3F3; }
QMenu { background: #FFFFFF; border: 1px solid #B8B8B8; padding: 3px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background: #DCE8F3; }
QToolTip { background: #FFFFFF; color: #252525; border: 1px solid #B8B8B8; padding: 5px; }
"""


class CategoryDelegate(QStyledItemDelegate):
    """Keep standard selection/focus rendering with a small category color marker."""

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        color_index = index.data(Qt.ItemDataRole.UserRole)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if color_index is None or not text:
            super().paint(painter, option, index)
            return
        decorated = QStyleOptionViewItem(option)
        self.initStyleOption(decorated, index)
        decorated.text = ""
        style = option.widget.style() if option.widget else None
        if style:
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem, decorated, painter, option.widget,
            )
        painter.save()
        foreground, _ = CATEGORY_COLORS[int(color_index) % len(CATEGORY_COLORS)]
        painter.fillRect(QRectF(option.rect.left() + 7, option.rect.center().y() - 4, 4, 9),
                         QColor(foreground))
        painter.setFont(option.font)
        painter.setPen(option.palette.text().color())
        label = painter.fontMetrics().elidedText(
            str(text), Qt.TextElideMode.ElideRight, max(0, option.rect.width() - 24),
        )
        painter.drawText(option.rect.adjusted(19, 0, -5, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        painter.restore()
