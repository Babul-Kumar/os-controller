import traceback
from PyQt5.QtCore import QThread, pyqtSignal

class TaskWorker(QThread):
    """
    Generic QThread to run backend tasks (AI processing, Voice) safely without blocking the UI.
    """
    finished = pyqtSignal(object)  # Emits the result of the callback
    error = pyqtSignal(str)        # Emits error string if exception occurs

    def __init__(self, callback, *args, **kwargs):
        super().__init__()
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.callback(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            traceback.print_exc()
            self.error.emit(str(e))
