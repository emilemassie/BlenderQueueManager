import os, subprocess, sys
import getpass
import threading
import time
from appdirs import user_config_dir
from pygame import mixer



from datetime import datetime

from PyQt5.QtWidgets import QApplication, QWidget, QListWidgetItem, QFileDialog
from PyQt5 import uic
from PyQt5.QtGui import QIcon, QTextCursor, QBrush, QColor
from PyQt5.QtCore import Qt, QEvent, QThread, pyqtSignal

def get_application_root_path():
    # determine if application is a script file or frozen exe
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    elif __file__:
        application_path = os.path.dirname(__file__)

    return application_path

class RenderWorker(QThread):
    progress = pyqtSignal(str, str)  # signal for log updates (text, color)
    set_status = pyqtSignal(QListWidgetItem, bool, bool)  # signal when an item is done
    bars = pyqtSignal(int, int, str)  # signal for progress bars (value, total)

    def __init__(self, blender_path, main_window):
        super().__init__()
        self.blender_path = blender_path
        self.main_window = main_window
        self.running = True


    def run(self):
        self.counter = 0
        self.total_file = self.main_window.ui.listWidget.count()




                # Prevent console window from appearing when compiled (Windows only)
        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        while self.counter < self.total_file:
            print(self.counter, self.total_file)
            item = self.main_window.ui.listWidget.item(self.counter)
            file_path, is_rendered = item.data(Qt.UserRole)
            if not is_rendered:
                self.progress.emit(f"Starting render for: {file_path}", "gray")
                self.set_status.emit(item, False, False)

                
     
                command = [self.blender_path, "-b", file_path, '--python-expr', 'import bpy; print("FRAMERANGE:"+str(bpy.context.scene.frame_start)+"-"+str(bpy.context.scene.frame_end))']
                process = subprocess.Popen( command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)
                frame_range = [None,None]
                while self.running:
                    output = process.stdout.readline()
                    if output == b'' and process.poll() is not None:
                        break
                    if output:
                        if 'FRAMERANGE:' in output.decode():
                            parts = output.decode().strip().split(':')[1].split('-')
                            frame_range[0] = int(parts[0].strip())
                            frame_range[1] = int(parts[1].strip())
                            self.progress.emit(f"Detected frame range: {frame_range[0]} to {frame_range[1]}", "blue")
                            break

                command = [self.blender_path, "-b", file_path, '-a']
                process = subprocess.Popen( command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags)


                current_frame = 0
                progress_percent = 0
                # shared variable for heartbeat thread to read
                self._progress_percent = 0
                # start a lightweight heartbeat thread that emits progress every second
                self.bars.emit(int(progress_percent), int(self.counter/self.total_file*100), f'Rendering {item.text()}')
                
                while self.running:
                    output = process.stdout.readline()
                    if output == b'' and process.poll() is not None:
                        break
                    if output:
                        if 'Fra:' in output.decode():
                            current_frame = int(output.decode().strip().split(':')[1].split(',')[0].split(' ')[0])
                            progress_percent = (current_frame - frame_range[0]) / (frame_range[1] - frame_range[0])*100
                        self.progress.emit(output.decode(), "gray")
                        self.bars.emit(int(progress_percent), int(self.counter/self.total_file*100), f'Rendering frame {current_frame} out of {frame_range[1]-frame_range[0]+1} for {item.text()}')
               
                if self.running:
                    rc = process.poll()
                    self.progress.emit(f"Render completed for: {file_path}", "green")
                    self.bars.emit(100, int(self.counter/self.total_file*100), ' ')
                    self.set_status.emit(item, True, False)

            self.counter += 1
            self.total_file = self.main_window.ui.listWidget.count()
    

        self.main_window.ui.render_button.setEnabled(True)
        self.main_window.ui.pbt.setValue(100)

        return


class BlenderQueueManager(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.render_worker = None

    def initUI(self):
        self.setWindowTitle('Blender Queue Manager')
        self.root = os.path.dirname(__file__)

        ui_path = os.path.join(self.root, 'ui', 'BlenderQueueManager.ui')
        self.ui = uic.loadUi(ui_path, self)

        self.ui.logbutton.setIcon(QIcon(os.path.join(self.root, 'icons', 'down.png')))
        self.ui.horizontalWidget_2.setVisible(False)

        self.ui.render_button.clicked.connect(self.start_render)
        self.ui.minb.clicked.connect(self.remove_item)
        self.ui.plusb.clicked.connect(self.add_blend_file)
        self.ui.toolButton.clicked.connect(self.find_blender)
        # enable accepting drops from the OS into the existing QListWidget
        self.ui.listWidget.setAcceptDrops(True)
        # install an event filter on the widget — we'll handle DragEnter/Drop
        self.ui.listWidget.installEventFilter(self)
        self.load_settings()
        self.setWindowIcon(QIcon(os.path.join(self.root, 'icons', 'blender_icon.png')))
        self.setWindowTitle('Blender Queue Manager')
        self.show()

    def add_blend_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        files, _ = QFileDialog.getOpenFileNames(self, "Select .blend Files", "", "Blender Files (*.blend);;All Files (*)", options=options)
        if files:
            for file_path in files:
                name = os.path.basename(file_path)
                item = QListWidgetItem(name)
                # store full path in UserRole for later use
                item.setData(Qt.UserRole, [file_path, 0])
                self.ui.listWidget.addItem(item)

    def update_progress(self, cval=None, tval=None, message=''):
        if cval:
            self.ui.pbc.setValue(cval)
        if tval:
            self.ui.pbt.setValue(tval)
        if message:
            self.ui.pbc.setFormat(message+' %p%')
        self.update()

    def load_settings(self):
        config_file = self.get_config_file()
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    if line.startswith('blender_executable='):
                        blender_path = line.split('=')[1].strip()
                        self.ui.b_exec.setText(blender_path)

    def save_settings(self):
        config_file = self.get_config_file()
        with open(config_file, 'w') as f:
            blender_path = self.ui.b_exec.text()
            f.write(f'blender_executable={blender_path}\n')

    def get_config_file(self):
        # Get the current username
        username = getpass.getuser()

        # Define your application name and author/company name
        app_name = "BlenderQueueManager"
        app_author = "BlenderQueueManager"  # Optional, not needed for Linux

        # Get the user-specific configuration directory
        config_dir = user_config_dir(app_name, app_author)

        # Create the configuration directory if it doesn't exist
        os.makedirs(config_dir, exist_ok=True)

        # Define the path for your configuration file
        config_file = os.path.join(config_dir, f"{username}_settings.conf")
        return config_file   

    def find_blender(self):
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Blender Executable", "", "Executables (*.exe);;All Files (*)", options=options)
        if file_path:
            self.ui.b_exec.setText(file_path)
            self.save_settings()

    def remove_item(self):
        selected_items = self.ui.listWidget.selectedItems()
        for item in selected_items:
            self.ui.listWidget.takeItem(self.ui.listWidget.row(item))

    def set_progress(self, value=None):

        # gro throught all the item in the list widget
        if self.ui.listWidget.count() > 0:
            for i in range(self.ui.listWidget.count()):
                item = self.ui.listWidget.item(i)
                # print the visible text and the stored full path (UserRole)
                print(item.text(), item.data(Qt.UserRole))


        if value:
            print(value)
        #self.ui.pbc.setValue(value)
        #self.ui.pbt.setValue(value)

    def play_sound(self, sound_file):
        mixer.init()
        mixer.music.load(sound_file)
        mixer.music.play()

    def start_render(self):
        blender_executable = self.ui.b_exec.text()
        if not blender_executable:
            self.update_logs("Blender executable not found.", color='red')
            return
        self.update_progress(0,0)
        self.update()

        # Create and setup the worker
        self.render_worker = RenderWorker(blender_executable, self)
        self.render_worker.progress.connect(self.update_logs)
        self.render_worker.set_status.connect(self.mark_item)
        self.render_worker.bars.connect(self.update_progress)
        self.render_worker.finished.connect(lambda: self.ui.render_button.setEnabled(True))
        self.render_worker.finished.connect(lambda: self.update_progress(100,100))
        self.render_worker.finished.connect(lambda: self.play_sound(os.path.join(self.root, 'icons', 'succes_sound.mp3')))
        self.render_worker.start()
        self.ui.render_button.setEnabled(False)

    def mark_item(self, item, done=False, failed=False):
        # mark as rendered
        file_path, is_rendered = item.data(Qt.UserRole)
        if done:
            item.setData(Qt.UserRole, [file_path, 1])  
            item.setForeground(QBrush(QColor('green')))
            item.setText(f"{item.text()} (Done)")
        else:
            item.setForeground(QBrush(QColor('orange')))
        if failed:
            item.setData(Qt.UserRole, [file_path, 0])
            item.setForeground(QBrush(QColor('red')))
            item.setText(f"{item.text()} (Failed)")


    def update_logs(self, text, color='gray'):
        # Move cursor to end and insert HTML, then add a line break so entries stack
        cursor = self.ui.logtext.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.ui.logtext.setTextCursor(cursor)
        # insertHtml doesn't automatically add a newline, so append a <br>
        self.ui.logtext.insertHtml(f'<span style="color:{color}">[{datetime.now().strftime("%y-%m-%d - %H:%M:%S")}] : {text}</span><br>')
        # keep the view scrolled to the bottom
        self.ui.logtext.verticalScrollBar().setValue(self.ui.logtext.verticalScrollBar().maximum())

    def eventFilter(self, source, event):
        """Handle drag/drop events on the list widget to accept .blend files.

        When a file is dropped, add a QListWidgetItem showing the filename
        and store the full path in Qt.UserRole on the item.
        """
        # Only handle events for the specific listWidget
        if source is self.ui.listWidget:
            # Drag enter / move: accept if there are URLs and at least one .blend
            if event.type() == QEvent.DragEnter or event.type() == QEvent.DragMove:
                md = event.mimeData()
                if md.hasUrls():
                    urls = md.urls()
                    for u in urls:
                        path = u.toLocalFile()
                        if path.lower().endswith('.blend'):
                            event.accept()
                            return True
                event.ignore()
                return True

            # Drop: add items for .blend files
            if event.type() == QEvent.Drop:
                md = event.mimeData()
                if md.hasUrls():
                    for u in md.urls():
                        path = u.toLocalFile()
                        if path and path.lower().endswith('.blend'):
                            name = os.path.basename(path)
                            item = QListWidgetItem(name)
                            # store full path in UserRole for later use
                            item.setData(Qt.UserRole, [path, 0])
                            self.ui.listWidget.addItem(item)
                    event.accept()
                    return True

        # default
        return super().eventFilter(source, event)

if __name__ == '__main__':
    app = QApplication([])
    ex = BlenderQueueManager()
    app.exec_()