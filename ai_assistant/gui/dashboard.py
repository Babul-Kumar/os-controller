"""
dashboard.py — Performance Dashboard UI View
Built with rich custom styling, glowing KPI cards, dynamic charts via QPainter, 
and tables displaying recent commands and model comparisons.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout, 
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea
)
from PyQt5.QtCore import Qt, QPoint, QRectF
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QLinearGradient, QFont, QAntialiasing

from core.metrics_store import get_store

_CARD_BG = "#131326"
_BORDER_COLOR = "#222240"
_TEXT_BRIGHT = "#ffffff"
_TEXT_DIM = "#9c9cc0"
_ACCENT_BLUE = "#00AEEF"
_ACCENT_GREEN = "#00e676"
_ACCENT_RED = "#ff1744"
_GRID_LINE = "#1a1a38"


# ── Custom QPainter Chart ──────────────────────────────────────────────────────

class CustomActivityChart(QWidget):
    """
    Custom-painted 7-day sparkline/activity chart.
    Renders successes (green) and failures (red) with filled gradients, 
    grid lines, and clean typography.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_points = []  # List of {"day": str, "ok": int, "fail": int}
        self.setMinimumHeight(220)

    def set_data(self, data):
        self.data_points = data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Margins
        padding_left = 40
        padding_right = 20
        padding_top = 30
        padding_bottom = 30
        
        chart_w = width - padding_left - padding_right
        chart_h = height - padding_top - padding_bottom
        
        # Background card styling
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(_CARD_BG)))
        painter.drawRoundedRect(0, 0, width, height, 12, 12)
        
        # Title
        painter.setPen(QColor(_TEXT_BRIGHT))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(15, 22, "7-Day Command Volume Activity")
        
        if not self.data_points:
            # Draw placeholder state
            painter.setPen(QColor(_TEXT_DIM))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignCenter, "No activity data recorded yet.")
            return

        # Find max value to scale Y axis
        max_val = 5  # Default baseline scale
        for pt in self.data_points:
            tot = pt["ok"] + pt["fail"]
            if tot > max_val:
                max_val = tot
        # Add 20% margin to top of chart
        max_val = int(max_val * 1.2) or 5
        
        # Draw horizontal grid lines & Y labels
        grid_lines = 4
        painter.setFont(QFont("Segoe UI", 8))
        for g in range(grid_lines + 1):
            y = padding_top + (chart_h * g // grid_lines)
            val = max_val - (max_val * g // grid_lines)
            
            # Grid line
            painter.setPen(QPen(QColor(_GRID_LINE), 1, Qt.DashLine))
            painter.drawLine(padding_left, y, width - padding_right, y)
            
            # Label
            painter.setPen(QColor(_TEXT_DIM))
            painter.drawText(10, y + 4, str(val))

        # Calculate coordinates
        x_coords = []
        n_pts = len(self.data_points)
        for idx in range(n_pts):
            if n_pts > 1:
                x = padding_left + (chart_w * idx // (n_pts - 1))
            else:
                x = padding_left + (chart_w // 2)
            x_coords.append(x)

        # Draw X labels (days)
        painter.setFont(QFont("Segoe UI", 8))
        for idx, pt in enumerate(self.data_points):
            day_str = pt["day"][-5:] if len(pt["day"]) >= 5 else pt["day"]  # MM-DD
            x = x_coords[idx]
            
            # Label
            painter.setPen(QColor(_TEXT_DIM))
            painter.drawText(x - 15, height - 10, day_str)

        # Build paths for successes (ok) and total/failures (fail)
        ok_points = []
        fail_points = []
        
        for idx, pt in enumerate(self.data_points):
            x = x_coords[idx]
            ok_val = pt["ok"]
            fail_val = pt["fail"]
            
            # Calculate Y positions
            y_ok = padding_top + chart_h - (chart_h * ok_val // max_val)
            y_fail = padding_top + chart_h - (chart_h * (ok_val + fail_val) // max_val)
            
            ok_points.append(QPoint(x, y_ok))
            fail_points.append(QPoint(x, y_fail))

        # ── 1. Draw Failures / Total Area (Red) ──
        if len(fail_points) > 1:
            grad_fail = QLinearGradient(0, padding_top, 0, padding_top + chart_h)
            grad_fail.setColorAt(0.0, QColor(255, 23, 68, 80))  # Semi-transparent red
            grad_fail.setColorAt(1.0, QColor(255, 23, 68, 0))
            
            from PyQt5.QtGui import QPainterPath
            path_fail = QPainterPath()
            path_fail.moveTo(x_coords[0], padding_top + chart_h)
            for p in fail_points:
                path_fail.lineTo(p.x(), p.y())
            path_fail.lineTo(x_coords[-1], padding_top + chart_h)
            path_fail.closeSubpath()
            
            painter.setBrush(grad_fail)
            painter.setPen(Qt.NoPen)
            painter.drawPath(path_fail)
            
            # Draw line
            painter.setPen(QPen(QColor(_ACCENT_RED), 2))
            painter.setBrush(Qt.NoBrush)
            for idx in range(n_pts - 1):
                painter.drawLine(fail_points[idx], fail_points[idx+1])

        # ── 2. Draw Successes Area (Green) ──
        if len(ok_points) > 1:
            grad_ok = QLinearGradient(0, padding_top, 0, padding_top + chart_h)
            grad_ok.setColorAt(0.0, QColor(0, 230, 118, 90))  # Semi-transparent green
            grad_ok.setColorAt(1.0, QColor(0, 230, 118, 0))
            
            path_ok = QPainterPath()
            path_ok.moveTo(x_coords[0], padding_top + chart_h)
            for p in ok_points:
                path_ok.lineTo(p.x(), p.y())
            path_ok.lineTo(x_coords[-1], padding_top + chart_h)
            path_ok.closeSubpath()
            
            painter.setBrush(grad_ok)
            painter.setPen(Qt.NoPen)
            painter.drawPath(path_ok)
            
            # Draw line
            painter.setPen(QPen(QColor(_ACCENT_GREEN), 2))
            painter.setBrush(Qt.NoBrush)
            for idx in range(n_pts - 1):
                painter.drawLine(ok_points[idx], ok_points[idx+1])

        # ── 3. Draw Nodes / Dots ──
        for idx in range(n_pts):
            p_ok = ok_points[idx]
            p_fail = fail_points[idx]
            
            # Success node dot
            painter.setPen(QPen(QColor("#0a0a1a"), 1.5))
            painter.setBrush(QBrush(QColor(_ACCENT_GREEN)))
            painter.drawEllipse(p_ok.x() - 4, p_ok.y() - 4, 8, 8)
            
            # Failure dot if failure count > 0
            if self.data_points[idx]["fail"] > 0:
                painter.setBrush(QBrush(QColor(_ACCENT_RED)))
                painter.drawEllipse(p_fail.x() - 4, p_fail.y() - 4, 8, 8)


# ── KPI Card Widget ────────────────────────────────────────────────────────────

class KPICard(QFrame):
    """Clean, glassmorphism KPI Card showing a title, big stat, and small detail."""
    def __init__(self, title, val, detail, icon="✦", border_accent=None, parent=None):
        super().__init__(parent)
        self.setObjectName("KPICard")
        
        accent = border_accent or _BORDER_COLOR
        self.setStyleSheet(f"""
            #KPICard {{
                background-color: {_CARD_BG};
                border: 1.5px solid {accent};
                border-radius: 12px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        
        # Header (icon + title)
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)
        
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: {_ACCENT_BLUE}; font-size: 13px; font-weight: bold;")
        header_layout.addWidget(icon_lbl)
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; font-family: 'Segoe UI'; font-weight: 500;")
        header_layout.addWidget(title_lbl, 1)
        
        layout.addLayout(header_layout)
        
        # Stat value
        self.val_lbl = QLabel(val)
        self.val_lbl.setStyleSheet(f"color: {_TEXT_BRIGHT}; font-size: 22px; font-family: 'Segoe UI'; font-weight: 700; padding-top: 4px;")
        layout.addWidget(self.val_lbl)
        
        # Detail / Subtext
        self.detail_lbl = QLabel(detail)
        self.detail_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; font-family: 'Segoe UI';")
        layout.addWidget(self.detail_lbl)

    def update_stats(self, val, detail):
        self.val_lbl.setText(val)
        self.detail_lbl.setText(detail)


# ── Performance Dashboard View ─────────────────────────────────────────────────

class PerformanceDashboard(QWidget):
    """
    Central view for the Botbro Performance Dashboard.
    Holds KPI grid, daily activity chart, STT comparison, and recent log.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.refresh_data()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 12, 16, 16)
        main_layout.setSpacing(12)
        
        # Top title row
        title_row = QHBoxLayout()
        title_lbl = QLabel("📊 Performance Analytics")
        title_lbl.setStyleSheet(f"color: {_TEXT_BRIGHT}; font-size: 16px; font-family: 'Segoe UI'; font-weight: bold;")
        title_row.addWidget(title_lbl)
        
        desc_lbl = QLabel("Real-time SQLite local telemetry")
        desc_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; font-family: 'Segoe UI'; font-style: italic;")
        title_row.addStretch()
        title_row.addWidget(desc_lbl)
        main_layout.addLayout(title_row)
        
        # Scrollable content frame (in case the panel is resized small)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: #0d0d1a;
                width: 6px;
            }
            QScrollBar::handle:vertical {
                background: #2a2a4a;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #00AEEF66;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(12)
        
        # ── Grid Layout for KPI Cards ──
        kpi_widget = QWidget()
        kpi_grid = QGridLayout(kpi_widget)
        kpi_grid.setContentsMargins(0, 0, 0, 0)
        kpi_grid.setHorizontalSpacing(10)
        kpi_grid.setVerticalSpacing(10)
        
        self.card_cmd = KPICard("COMMAND PIPELINE", "0.0%", "0 commands logged", "⚡", "#00AEEF33")
        self.card_stt = KPICard("LOCAL SPEECH (STT)", "0.0 ms", "0 transcriptions", "🎤", "#ab47bc33")
        self.card_ocr = KPICard("VISION & OCR", "0.0%", "0 vision lookups", "👁️", "#00e67633")
        self.card_agent = KPICard("AGENTS & WORKFLOWS", "0.0%", "0 orchestrations", "🤖", "#ff910033")
        
        kpi_grid.addWidget(self.card_cmd, 0, 0)
        kpi_grid.addWidget(self.card_stt, 0, 1)
        kpi_grid.addWidget(self.card_ocr, 0, 2)
        kpi_grid.addWidget(self.card_agent, 0, 3)
        
        scroll_layout.addWidget(kpi_widget)
        
        # ── Middle Row: Chart & STT Comparison Table ──
        mid_row = QHBoxLayout()
        mid_row.setSpacing(10)
        
        # Custom painter chart
        self.chart = CustomActivityChart()
        mid_row.addWidget(self.chart, 3)
        
        # STT Model Table Card
        self.stt_card = QFrame()
        self.stt_card.setStyleSheet(f"""
            QFrame {{
                background-color: {_CARD_BG};
                border: 1px solid {_BORDER_COLOR};
                border-radius: 12px;
            }}
        """)
        stt_layout = QVBoxLayout(self.stt_card)
        stt_layout.setContentsMargins(12, 10, 12, 10)
        stt_layout.setSpacing(6)
        
        stt_title = QLabel("Speech Engine Benchmark Comparison")
        stt_title.setStyleSheet(f"color: {_TEXT_BRIGHT}; font-size: 10px; font-weight: bold; font-family: 'Segoe UI';")
        stt_layout.addWidget(stt_title)
        
        self.stt_table = QTableWidget()
        self.stt_table.setColumnCount(4)
        self.stt_table.setHorizontalHeaderLabels(["Engine/Model", "Lat. ms", "TPS", "Runs"])
        self.stt_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stt_table.verticalHeader().setVisible(False)
        self.stt_table.setStyleSheet(self._table_stylesheet())
        self.stt_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        stt_layout.addWidget(self.stt_table)
        
        mid_row.addWidget(self.stt_card, 2)
        scroll_layout.addLayout(mid_row)
        
        # ── Bottom Section: Recent Activities log table ──
        log_card = QFrame()
        log_card.setStyleSheet(f"""
            QFrame {{
                background-color: {_CARD_BG};
                border: 1px solid {_BORDER_COLOR};
                border-radius: 12px;
            }}
        """)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(14, 12, 14, 12)
        log_layout.setSpacing(8)
        
        log_title = QLabel("Recent Telemetry Audit Log")
        log_title.setStyleSheet(f"color: {_TEXT_BRIGHT}; font-size: 11px; font-weight: bold;")
        log_layout.addWidget(log_title)
        
        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(["Time", "Pipeline Action", "Raw Prompt Input", "Lat. ms", "Status"])
        self.log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setStyleSheet(self._table_stylesheet())
        self.log_table.setMinimumHeight(180)
        
        # Set column widths
        header = self.log_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        
        log_layout.addWidget(self.log_table)
        scroll_layout.addWidget(log_card)
        
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll, 1)

    def refresh_data(self):
        """Fetch latest statistics from sqlite MetricsStore and refresh UI."""
        store = get_store()
        summary = store.get_summary()
        
        if not summary:
            return

        # 1. Update KPI Card 1: Commands
        cmd_rate = summary.get("command_success_rate", 0.0)
        cmd_tot = summary.get("command_count", 0)
        cmd_lat = summary.get("command_avg_latency_ms", 0.0)
        self.card_cmd.update_stats(
            f"{cmd_rate}%", 
            f"{cmd_tot} commands ({cmd_lat} ms avg)"
        )
        
        # 2. Update KPI Card 2: Speech
        stt_tot = summary.get("stt_count", 0)
        stt_lat = summary.get("stt_avg_latency_ms", 0.0)
        stt_tps = summary.get("stt_avg_tps", 0.0)
        self.card_stt.update_stats(
            f"{stt_lat} ms", 
            f"{stt_tot} transcriptions ({stt_tps} tok/s)"
        )
        
        # 3. Update KPI Card 3: OCR
        ocr_rate = summary.get("ocr_success_rate", 0.0)
        ocr_tot = summary.get("ocr_count", 0)
        ocr_lat = summary.get("ocr_avg_latency_ms", 0.0)
        self.card_ocr.update_stats(
            f"{ocr_rate}%", 
            f"{ocr_tot} vision calls ({ocr_lat} ms avg)"
        )
        
        # 4. Update KPI Card 4: Agents & Workflows
        agent_rate = summary.get("agent_success_rate", 0.0)
        agent_tot = summary.get("agent_count", 0)
        wf_rate = summary.get("workflow_success_rate", 0.0)
        wf_tot = summary.get("workflow_count", 0)
        self.card_agent.update_stats(
            f"{agent_rate}%", 
            f"{agent_tot} agents / {wf_tot} macros (WF: {wf_rate}%)"
        )
        
        # 5. Update Daily activity chart
        daily_counts = store.get_daily_command_counts(days=7)
        self.chart.set_data(daily_counts)
        
        # 6. Update STT Model comparison table
        stt_comp = store.get_stt_model_comparison()
        self.stt_table.setRowCount(0)
        for idx, row in enumerate(stt_comp):
            self.stt_table.insertRow(idx)
            
            # Parse engine / model name
            backend = row.get("backend", "")
            model = row.get("model", "")
            engine_name = f"{backend} ({model})" if model else backend
            
            self.stt_table.setItem(idx, 0, self._cell(engine_name))
            self.stt_table.setItem(idx, 1, self._cell(f"{row.get('avg_latency', 0.0):.0f} ms"))
            self.stt_table.setItem(idx, 2, self._cell(f"{row.get('avg_tps', 0.0):.1f}"))
            self.stt_table.setItem(idx, 3, self._cell(str(row.get('runs', 0))))
            
        # 7. Update Recent Audit Log table
        recent = store.get_recent_commands(limit=15)
        self.log_table.setRowCount(0)
        for idx, row in enumerate(recent):
            self.log_table.insertRow(idx)
            
            # Format timestamp
            ts = row.get("timestamp", "")
            if ts and "T" in ts:
                ts = ts.split("T")[1][:8]  # HH:MM:SS
                
            action = row.get("action", "")
            prompt = row.get("raw_input", "")
            lat = f"{row.get('latency_ms', 0.0):.0f} ms"
            
            success = row.get("success", 0)
            status_item = QTableWidgetItem("  Success  " if success else "  Failed  ")
            status_item.setTextAlignment(Qt.AlignCenter)
            if success:
                status_item.setForeground(QColor(_ACCENT_GREEN))
                status_item.setBackground(QColor(0, 230, 118, 15))
            else:
                status_item.setForeground(QColor(_ACCENT_RED))
                status_item.setBackground(QColor(255, 23, 68, 15))
            status_item.setFont(QFont("Segoe UI", 8, QFont.Bold))
            
            self.log_table.setItem(idx, 0, self._cell(ts, dim=True))
            self.log_table.setItem(idx, 1, self._cell(action, bold=True))
            self.log_table.setItem(idx, 2, self._cell(prompt, left=True))
            self.log_table.setItem(idx, 3, self._cell(lat))
            self.log_table.setItem(idx, 4, status_item)

    def _cell(self, text, bold=False, dim=False, left=False) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if left else Qt.AlignCenter)
        item.setForeground(QColor(_TEXT_DIM if dim else _TEXT_BRIGHT))
        
        font = QFont("Segoe UI", 9)
        if bold:
            font.setBold(True)
            item.setForeground(QColor(_ACCENT_BLUE))
        item.setFont(font)
        return item

    def _table_stylesheet(self) -> str:
        return f"""
            QTableWidget {{
                background-color: transparent;
                border: none;
                gridline-color: #1a1a38;
                color: {_TEXT_BRIGHT};
                font-family: "Segoe UI", sans-serif;
            }}
            QHeaderView::section {{
                background-color: #161632;
                color: {_TEXT_DIM};
                font-weight: bold;
                font-size: 10px;
                padding: 6px;
                border: none;
                border-bottom: 1.5px solid {_BORDER_COLOR};
            }}
            QTableWidget::item {{
                padding: 5px;
                border-bottom: 1px solid #14142b;
            }}
            QTableWidget::item:selected {{
                background-color: #1c1c3c;
            }}
        """
