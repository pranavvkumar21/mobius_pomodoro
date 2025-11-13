import sys
import logging
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction,
                             QWidget, QVBoxLayout, QLabel, QLineEdit, QFormLayout,
                             QPushButton, QDialog)
from PyQt5.QtGui import QIcon, QColor, QPainter, QLinearGradient, QFont
from PyQt5.QtCore import Qt, QTimer, QRect
import yaml, os


# Setup logging for verbose output
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger()

class PreferencesDialog(QDialog):
    def __init__(self, work, rest, cycles):
        super().__init__()
        self.setWindowTitle("Pomodoro Preferences")
        self.setFixedSize(300, 150)
        self.work_input = QLineEdit(str(work))
        self.rest_input = QLineEdit(str(rest))
        self.cycles_input = QLineEdit(str(cycles))

        form_layout = QFormLayout()
        form_layout.addRow("Work (minutes):", self.work_input)
        form_layout.addRow("Rest (minutes):", self.rest_input)
        form_layout.addRow("Cycles:", self.cycles_input)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.accept)

        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(self.save_button)
        self.setLayout(layout)

    def get_values(self):
        return (int(self.work_input.text()), int(self.rest_input.text()), int(self.cycles_input.text()))

class FloatingTimer(QWidget):
    def __init__(self, screen_geometry):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool | 
            Qt.WindowTransparentForInput  # makes widget ignore mouse events
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.label = QLabel(self)
        self.label.setStyleSheet("color: white;")
        font = QFont("Arial", 20, QFont.Bold)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.resize(120, 40)
        self.resize(120, 40)

        # Position bottom-right corner above the taskbar with a small margin
        margin_x, margin_y = 15, 50
        x = screen_geometry.width() - self.width() - margin_x
        y = screen_geometry.height() - self.height() - margin_y
        self.move(x, y)

        self.show()

    def update_time(self, text):
        self.label.setText(text)

class TopBarProgress(QWidget):
    def __init__(self, screen_width, height=3):
        super().__init__()
        self.screen_width = screen_width
        self.bar_height = height
        self.progress = 0.0
        self.is_rest = False
        
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.setGeometry(0, 0, self.screen_width, self.bar_height)
        self.show()

    def set_progress(self, percent, is_rest):
        self.progress = max(0.0, min(percent, 1.0))
        self.is_rest = is_rest
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)

        # Draw transparent dark background for bar depth
        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

        progress_width = int(self.width() * self.progress)
        gradient_rect = QRect(0, 0, progress_width, self.bar_height)

        # Choose gradient colors
        gradient = QLinearGradient(0, 0, progress_width, 0)
        if self.is_rest:
            # Electric Purple to Soft Lavender (Rest)
            gradient.setColorAt(0, QColor(140, 0, 255, 200))    # Electric Purple
            gradient.setColorAt(1, QColor(230, 230, 250, 200))  # Lavender Mist
        else:
            # Visually aesthetic green gradient (Work)
            gradient.setColorAt(0, QColor(56, 142, 60, 220))    # Dark Green
            gradient.setColorAt(1, QColor(129, 199, 132, 220))  # Light Green

        painter.fillRect(gradient_rect, gradient)

class FullScreenOverlay(QWidget):
    def __init__(self, screen_geometry):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen_geometry)
        
        self.message = ""
        
        self.font = QFont("Arial", 40, QFont.Bold)
        self.text_color = QColor(255, 255, 255, 230)  # White with some transparency
        
        self.hide()

    def set_message(self, text):
        self.message = text
        self.show()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        
        # Draw translucent black background
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        
        # Draw centered message text
        painter.setPen(self.text_color)
        painter.setFont(self.font)
        painter.drawText(self.rect(), Qt.AlignCenter, self.message)

    def mousePressEvent(self, event):
        # Hide overlay on any mouse click
        self.hide()


class TrayPomodoro:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False) 
        screen = self.app.primaryScreen()
        screen_geometry = screen.geometry()
        self.floating_timer = FloatingTimer(screen_geometry)
        self.overlay = FullScreenOverlay(screen_geometry)
        if not os.path.exists('pomodoro_config.yaml'):
            # Create default config file
            with open('pomodoro_config.yaml', 'w') as f:
                yaml.dump({
                    'work_minutes': 25,
                    'rest_minutes': 5,
                    'cycles': 4
                }, f)
            logger.info("Created default pomodoro_config.yaml")
            
        with open('pomodoro_config.yaml', 'r') as f:
            config = yaml.safe_load(f)

        self.progress_bar = TopBarProgress(screen_geometry.width(), height=3)

        self.work_minutes = config.get('work_minutes', 25)
        self.rest_minutes = config.get('rest_minutes', 5)
        self.cycles = config.get('cycles', 4)
        self.current_cycle = 1
        self.phase = 'stopped'  # 'work', 'rest', or 'stopped'
        self.seconds_left = 0

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)

        # Keep persistent reference for preferences dialog to avoid garbage collection
        self.pref_dialog = None

        # Create tray icon and menu
        icon = QIcon("assets/mobius.png")
        if icon.isNull():
            icon = QApplication.style().standardIcon(QApplication.style().SP_ComputerIcon)  # fallback icon

        self.tray = QSystemTrayIcon(icon, self.app)

        self.menu = QMenu()

        self.start_action = QAction("Start")
        self.start_action.triggered.connect(self.start)
        self.pause_action = QAction("Pause")
        self.pause_action.triggered.connect(self.pause)

        self.menu.addAction(self.start_action)

        reset_action = QAction("Reset", self.menu)
        reset_action.triggered.connect(self.reset)
        self.menu.addAction(reset_action)

        pref_action = QAction("Preferences", self.menu)
        pref_action.triggered.connect(self.open_preferences)
        self.menu.addAction(pref_action)

        self.menu.addSeparator()

        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.quit_app)
        self.menu.addAction(quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.show()

        logger.debug("Initialized TrayPomodoro")

    def start(self):
        logger.debug("Start clicked")
        if self.phase == 'stopped':
            self.phase = 'work'
            self.current_cycle = 1
            self.seconds_left = self.work_minutes * 60
        self.timer.start(100)
        self.update_menu(True)
        self.update_tray()

    def pause(self):
        logger.debug("Pause clicked")
        self.timer.stop()
        self.update_menu(False)
        self.update_tray()


    def reset(self):
        logger.debug("Resetting timer")
        # Do NOT stop the timer here to keep event loop alive
        # self.timer.stop()
        self.phase = 'stopped'
        self.current_cycle = 1
        self.seconds_left = 0
        self.progress_bar.set_progress(0, False)
        self.update_menu(False)
        self.update_tray()
        self.tray.show()
        self.progress_bar.show()

    def save_preferences(self):
        with open('pomodoro_config.yaml', 'w') as f:
            yaml.dump({
                'work_minutes': self.work_minutes,
                'rest_minutes': self.rest_minutes,
                'cycles': self.cycles
            }, f)
        logger.info("Preferences saved to pomodoro_config.yaml")

    def open_preferences(self):
        logger.debug("Opening preferences dialog")
        self.pause()
        self.pref_dialog = PreferencesDialog(self.work_minutes, self.rest_minutes, self.cycles)
        if self.pref_dialog.exec_() == QDialog.Accepted:
            work, rest, cycles = self.pref_dialog.get_values()
            if work < 1 or rest < 1 or cycles < 1:
                logger.warning("Invalid input")
                return
            self.work_minutes, self.rest_minutes, self.cycles = work, rest, cycles
            logger.info(f"Preferences updated: Work={work}, Rest={rest}, Cycles={cycles}")
            self.save_preferences()
            self.reset()
            self.start()  # Restart timer to keep app running
        else:
            logger.debug("Preferences dialog canceled")


    def tick(self):
        decrement = self.timer.interval() / 1000.0  # seconds per tick

        if self.seconds_left > 0:
            self.seconds_left -= decrement
            if self.seconds_left < 0:
                self.seconds_left = 0
            self.update_tray()

        else:
            if self.phase == 'work':
                self.tray.showMessage("Break Time", "Time to rest!", QSystemTrayIcon.Information, 3000)
                self.phase = 'rest'
                self.seconds_left = float(self.rest_minutes * 60)
                self.update_tray()

                # Show overlay with rest message
                self.overlay.set_message("Time to Rest!")

            elif self.phase == 'rest':
                self.current_cycle += 1
                if self.current_cycle > self.cycles:
                    self.tray.showMessage("Pomodoro Finished", "All cycles complete! Good job!", QSystemTrayIcon.Information, 3000)
                    self.reset()
                else:
                    self.tray.showMessage("Work Time", "Back to work!", QSystemTrayIcon.Information, 3000)
                    self.phase = 'work'
                    self.seconds_left = float(self.work_minutes * 60)
                    self.update_tray()

                    # Show overlay with work message
                    self.overlay.set_message("Time to Work!")



    def update_menu(self, running):
        logger.debug(f"Updating menu, running={running}")
        
        # Remove both start and pause actions safely, if present
        if self.start_action in self.menu.actions():
            self.menu.removeAction(self.start_action)
        if self.pause_action in self.menu.actions():
            self.menu.removeAction(self.pause_action)
        
        # Insert the correct action as the first item in the menu (before reset)
        # Find reset_action position or just insert at index 0
        actions = self.menu.actions()
        if actions:
            insert_before = actions[0]
            if running:
                self.menu.insertAction(insert_before, self.pause_action)
            else:
                self.menu.insertAction(insert_before, self.start_action)
        else:
            # If no actions, just add
            if running:
                self.menu.addAction(self.pause_action)
            else:
                self.menu.addAction(self.start_action)
        
        # Ensure tray icon stays shown
        self.tray.show()

    def update_tray(self):
        mins, secs = divmod(int(self.seconds_left), 60)
        time_str = f"{mins:02d}:{secs:02d}"
        self.floating_timer.update_time(time_str)

        phase_str = "Rest" if self.phase == 'rest' else ("Work" if self.phase == 'work' else "Stopped")
        tooltip = f"{phase_str} Cycle {self.current_cycle}/{self.cycles} - {time_str}"
        self.tray.setToolTip(tooltip)

        if self.phase == 'work':
            total = self.work_minutes * 60
            progress = self.seconds_left / total if total else 0
        elif self.phase == 'rest':
            total = self.rest_minutes * 60
            progress = self.seconds_left / total if total else 0
        else:
            progress = 0

        self.progress_bar.set_progress(progress, self.phase == 'rest')

    def quit_app(self):
        logger.info("Quit selected, stopping timer and hiding UI")
        self.timer.stop()
        self.progress_bar.hide()
        self.tray.hide()
        QApplication.quit()

    def run(self):
        logger.info("Starting application event loop")
        exit_code = self.app.exec_()
        logger.info(f"Application event loop exited with code {exit_code}")
        sys.exit(exit_code)


if __name__ == '__main__':
    pomodoro = TrayPomodoro()
    pomodoro.run()
