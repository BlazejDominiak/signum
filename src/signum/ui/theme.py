"""Shared visual language and readable category badges for the desktop UI."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

CATEGORY_COLORS = (
    ("#2457B5", "#EAF0FF"),
    ("#14755C", "#E5F5EE"),
    ("#6D43AD", "#F1EAFB"),
    ("#94611B", "#FFF3D8"),
    ("#116E88", "#E2F3F8"),
    ("#AA4667", "#FBEAF0"),
    ("#494FB3", "#ECEDFF"),
    ("#167675", "#E1F4F2"),
    ("#A35920", "#FFF0E5"),
    ("#536781", "#ECF1F6"),
    ("#8A4E96", "#F7EBFA"),
    ("#60666F", "#EEF0F3"),
)

SIGNUM_STYLE = """
QMainWindow, QWidget#classificationPanel { background: #F2F5FA; }
QWidget { color: #213248; font-family: 'Segoe UI'; font-size: 13px; }
QLabel { background: transparent; }
QLabel[role='title'] { font-size: 24px; font-weight: 700; color: #182D4B; }
QLabel[role='heading'] { font-size: 15px; font-weight: 600; }
QLabel[role='muted'] { color: #66768C; }
QLabel[role='badge'] { background: #EAF0FB; color: #2457B5;
    border-radius: 10px; padding: 4px 10px; font-weight: 600; }
QWidget[role='card'] { background: #FFFFFF; border: 1px solid #DEE6F1;
    border-radius: 12px; }
QWidget[role='metric'] { background: #F4F7FC; border: 1px solid #E1E8F2;
    border-radius: 10px; }
QWidget[role='metric'][active='true'] { background: #EDF3FF; border-color: #AFC5EE; }
QLabel[role='metricValue'] { font-size: 27px; font-weight: 700; color: #244F91; }
QPushButton, QToolButton { background: #FFFFFF; border: 1px solid #CFDAE9;
    border-radius: 7px; padding: 7px 12px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: #EDF3FC; border-color: #A6BBDA; }
QPushButton:pressed, QToolButton:pressed { background: #DCE8F9; }
QPushButton:disabled, QToolButton:disabled { color: #94A0B1; background: #F3F5F8;
    border-color: #E1E6EF; }
QPushButton[role='primary'] { background: #245CBA; color: white; border-color: #245CBA;
    padding: 9px 22px; }
QPushButton[role='primary']:hover { background: #1C4F9F; }
QPushButton[role='primary']:disabled { background: #A6BADB; border-color: #A6BADB; }
QPushButton[role='quiet'] { background: transparent; border-color: transparent;
    color: #49658E; padding: 5px 8px; }
QPushButton[role='quiet']:hover { background: #EDF3FC; }
QPushButton[role='quiet']:disabled { color: #94A0B1; background: transparent; }
QComboBox, QSpinBox, QLineEdit, QPlainTextEdit { background: white;
    border: 1px solid #CCD8E8; border-radius: 6px; padding: 6px; }
QComboBox:focus, QSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus {
    border-color: #5684CC; }
QTableWidget { background: white; alternate-background-color: #F8FAFD;
    border: 0; selection-background-color: #E4EDFA; selection-color: #213248;
    gridline-color: #EDF1F6; }
QTableWidget::item { padding: 5px; border-bottom: 1px solid #EFF3F8; }
QHeaderView::section { background: #F4F7FB; color: #64758D;
    border: 0; border-bottom: 1px solid #DFE7F2; padding: 9px 7px; font-weight: 600; }
QTableCornerButton::section { background: #F4F7FB; border: 0; }
QTabWidget::pane { border: 0; background: #F2F5FA; }
QTabBar::tab { background: #E9EEF6; color: #63758E; padding: 12px 24px;
    border: 0; border-bottom: 3px solid transparent; font-weight: 600; }
QTabBar::tab:selected { background: #F2F5FA; color: #245CBA;
    border-bottom-color: #245CBA; }
QTabBar::tab:hover { color: #245CBA; }
QSplitter::handle { background: transparent; width: 12px; }
QProgressBar { background: #E6EDF7; border: 0; border-radius: 3px;
    min-height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #3E75CA; border-radius: 3px; }
QToolBar { background: #FFFFFF; border: 0; padding: 6px; spacing: 5px; }
QStatusBar { background: #F2F5FA; }
QToolTip { background: #213248; color: white; border: 0; padding: 6px; }
"""


class CategoryDelegate(QStyledItemDelegate):
    """The same color follows a category from the editable list to its results."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        color_index = index.data(Qt.ItemDataRole.UserRole)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if color_index is None or not text:
            super().paint(painter, option, index)
            return
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.brush(QPalette.ColorRole.Highlight))
        foreground, background = CATEGORY_COLORS[int(color_index) % len(CATEGORY_COLORS)]
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = option.font
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        label = metrics.elidedText(str(text), Qt.TextElideMode.ElideRight, option.rect.width() - 34)
        rect = QRectF(option.rect).adjusted(4, 5, -4, -5)
        rect.setWidth(min(rect.width(), metrics.horizontalAdvance(label) + 28))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setBrush(QColor(foreground))
        painter.drawEllipse(QRectF(rect.left() + 8, rect.center().y() - 3, 6, 6))
        painter.setPen(QColor(foreground))
        painter.drawText(
            rect.adjusted(20, 0, -7, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            label,
        )
        painter.restore()
