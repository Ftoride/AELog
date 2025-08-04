import sys
import os
from datetime import datetime
from pynput import mouse, keyboard
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QPainter, QPixmap, QColor, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QLineEdit, QSpinBox, QHBoxLayout, QVBoxLayout,
    QFileDialog, QSystemTrayIcon, QMenu, QAction, QStyle,
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout
)

DAYS_RU = {
    "Monday": "Пн", "Tuesday": "Вт", "Wednesday": "Ср",
    "Thursday": "Чт", "Friday": "Пт", "Saturday": "Сб", "Sunday": "Вс"
}


class CombinedCounter(QObject):
    count_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.click_count = 0
        self._mouse_listener = None
        self._key_listener = None

    def on_mouse_click(self, x, y, button, pressed):
        if pressed:
            self.click_count += 1
            self.count_changed.emit(self.click_count)

    def on_key_press(self, key):
        self.click_count += 1
        self.count_changed.emit(self.click_count)

    def start(self):
        if not self._mouse_listener or not self._mouse_listener.running:
            self._mouse_listener = mouse.Listener(on_click=self.on_mouse_click)
            self._mouse_listener.start()
        if not self._key_listener or not self._key_listener.running:
            self._key_listener = keyboard.Listener(on_press=self.on_key_press)
            self._key_listener.start()

    def stop(self):
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._key_listener:
            self._key_listener.stop()

    def reset(self):
        self.click_count = 0
        self.count_changed.emit(self.click_count)


class SettingsDialog(QDialog):
    def __init__(self, parent, current_log, current_interval, current_idle):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setModal(True)

        self.log_path_edit = QLineEdit(current_log)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(current_interval)

        self.idle_minutes_spin = QSpinBox()
        self.idle_minutes_spin.setRange(1, 1440)
        self.idle_minutes_spin.setValue(current_idle)

        form_layout = QFormLayout()
        form_layout.addRow("Лог:", self.log_path_edit)
        form_layout.addRow("Интервал (мин):", self.interval_spin)
        form_layout.addRow("Задержка смены фона (мин):", self.idle_minutes_spin)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def get_values(self):
        return (
            self.log_path_edit.text(),
            self.interval_spin.value(),
            self.idle_minutes_spin.value()
        )


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AE Log")

        self.idle_minutes = 5  # значение по умолчанию

        img_path = os.path.join(os.path.dirname(__file__), '40.jpg')
        self.original_img_path = img_path
        self.idle_img_path = os.path.join(os.path.dirname(__file__), '41.png')

        if os.path.exists(img_path):
            self.background = QPixmap(img_path)
            self.bg_color = None
            icon = QIcon(img_path)
        else:
            self.background = None
            self.bg_color = QColor('#001f3f')
            icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)

        self.tray_icon = QSystemTrayIcon(icon, self)
        tray_menu = QMenu(self)
        restore_action = QAction("Восстановить", self)
        exit_action = QAction("Выход", self)
        restore_action.triggered.connect(self._restore_from_tray)
        exit_action.triggered.connect(QApplication.quit)
        tray_menu.addAction(restore_action)
        tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)

        self.counter = CombinedCounter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.log_clicks)

        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(self.idle_minutes * 60 * 1000)
        self.idle_timer.timeout.connect(self.on_idle_timeout)
        self.idle_timer.start()
        self.idle = False

        self._build_ui()
        self._connect_signals()

        self.start_logging()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.background:
            pix = self.background.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(0, 0, pix)
        else:
            painter.fillRect(self.rect(), self.bg_color)
        super().paintEvent(event)

    def _build_ui(self):
        container = QWidget(self)
        container.setStyleSheet(
            "background-color: rgba(255, 255, 255, 160); border-radius: 10px;"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20)

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setFont(self._set_font_size(14))

        self.label = QLabel("Кликов: 0")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setFont(self._set_font_size(16))

        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setFont(self._set_font_size(12))

        self.log_path_edit = QLineEdit("mouse_log.txt")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(2)

        self.start_btn = QPushButton("Старт")
        self.stop_btn = QPushButton("Стоп")
        self.minimize_btn = QPushButton("Свернуть")
        self.stop_btn.setEnabled(True)
        self.start_btn.setEnabled(False)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.minimize_btn)

        self.settings_btn = QPushButton("⚙ Настройки")
        self.settings_btn.setFixedWidth(110)
        self.always_on_top_cb = QCheckBox("Поверх окон")
        self.always_on_top_cb.stateChanged.connect(self.toggle_always_on_top)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.settings_btn)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.always_on_top_cb)

        layout.addWidget(self.time_label)
        layout.addWidget(self.label)
        layout.addWidget(self.date_label)
        layout.addLayout(btn_layout)
        layout.addLayout(bottom_layout)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(container)
        self.setLayout(main_layout)

        self.time_timer = QTimer(self)
        self.time_timer.timeout.connect(self.update_time)
        self.time_timer.start(1000)
        self.update_time()

    def _set_font_size(self, size):
        font = self.font()
        font.setPointSize(size)
        return font

    def toggle_always_on_top(self, state):
        flags = self.windowFlags()
        if state == Qt.Checked:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
        self.show()

    def update_time(self):
        now = datetime.now()
        weekday_en = now.strftime("%A")
        weekday_ru = DAYS_RU.get(weekday_en, "")
        self.time_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%d.%m.%Y") + f" ({weekday_ru})")

    def _connect_signals(self):
        self.start_btn.clicked.connect(self.start_logging)
        self.stop_btn.clicked.connect(self.stop_logging)
        self.minimize_btn.clicked.connect(self._minimize_to_tray)
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        self.counter.count_changed.connect(self.update_label)
        self.counter.count_changed.connect(self.handle_user_activity)

    def _minimize_to_tray(self):
        self.hide()
        self.tray_icon.show()
        self.tray_icon.showMessage("AE Logger", "Свернуто в трей.")

    def _restore_from_tray(self):
        self.show()
        self.tray_icon.hide()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._restore_from_tray()

    def open_settings_dialog(self):
        dlg = SettingsDialog(self, self.log_path_edit.text(), self.interval_spin.value(), self.idle_minutes)
        if dlg.exec_():
            log_path, interval, idle_delay = dlg.get_values()
            self.log_path_edit.setText(log_path)
            self.interval_spin.setValue(interval)
            self.idle_minutes = idle_delay
            self.idle_timer.setInterval(self.idle_minutes * 60 * 1000)
            self.idle_timer.start()

    def update_label(self, count):
        self.label.setText(f"Кликов: {count}")

    def start_logging(self):
        self.counter.start()
        interval_ms = self.interval_spin.value() * 60 * 1000
        self.timer.start(interval_ms)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_logging(self):
        self.counter.stop()
        self.timer.stop()
        self.log_clicks()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def log_clicks(self):
        count = self.counter.click_count
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{now} - Кликов/нажатий: {count}\n"
        with open(self.log_path_edit.text(), "a", encoding="utf-8") as f:
            f.write(entry)

    def handle_user_activity(self, _=None):
        if self.idle:
            if os.path.exists(self.original_img_path):
                self.background = QPixmap(self.original_img_path)
                self.idle = False
                self.update()
        self.idle_timer.start()

    def on_idle_timeout(self):
        if os.path.exists(self.idle_img_path):
            self.background = QPixmap(self.idle_img_path)
            self.idle = True
            self.update()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(__file__)
    icon_path = os.path.join(base_path, "ae.ico")
    app.setWindowIcon(QIcon(icon_path))

    w = MainWindow()
    w.resize(420, 320)
    w.show()
    sys.exit(app.exec_())
