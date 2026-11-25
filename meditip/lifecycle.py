"""Process-local shutdown coordination, used only by the desktop launcher."""
import threading

class DesktopLifecycle:
    def __init__(self):
        self.ready=threading.Event()
        self.finished=threading.Event()
        self._lock=threading.Lock()
        self._server=None
        self._busy=lambda:False
        self._active=0
        self._stopping=False
        self.error=None

    def bind(self,server,busy):
        with self._lock:
            self._server=server
            self._busy=busy
        self.ready.set()

    def enter(self):
        with self._lock:
            if self._stopping:return False
            self._active+=1
            return True

    def leave(self):
        with self._lock:self._active-=1

    def request_stop(self,from_request=False):
        """Reject while a write or job runs; shutdown must occur off the serving thread."""
        with self._lock:
            if self._stopping:return True
            if self._server is None or self._active>(1 if from_request else 0) or self._busy():
                return False
            self._stopping=True
            server=self._server
        threading.Thread(target=server.shutdown,name='server-shutdown',daemon=True).start()
        return True

    def complete(self,error=None):
        self.error=error
        self.ready.set()
        self.finished.set()
