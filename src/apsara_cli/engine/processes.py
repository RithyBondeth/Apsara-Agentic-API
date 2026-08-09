"""Workspace-scoped background process lifecycle and bounded output capture."""

import atexit
import os
import signal
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from uuid import uuid4


@dataclass
class ManagedProcess:
    process_id: str
    command: str
    cwd: Path
    process: subprocess.Popen
    started_at: float = field(default_factory=time)
    output: deque[str] = field(default_factory=lambda: deque(maxlen=2000))

    @property
    def status(self) -> str:
        code = self.process.poll()
        return "running" if code is None else f"exited({code})"


class ProcessManager:
    def __init__(self):
        self._items: dict[str, ManagedProcess] = {}
        self._lock = threading.Lock()

    def start(self, command: str, cwd: Path) -> ManagedProcess:
        popen_options = {}
        if os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_options["start_new_session"] = True
        process = subprocess.Popen(
            command, shell=True, cwd=str(cwd), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            **popen_options,
        )
        item = ManagedProcess(uuid4().hex[:8], command, cwd, process)
        with self._lock:
            self._items[item.process_id] = item

        def collect() -> None:
            if process.stdout is not None:
                for line in process.stdout:
                    item.output.append(line.rstrip("\n"))

        threading.Thread(target=collect, daemon=True, name=f"apsara-{item.process_id}").start()
        return item

    def get(self, process_id: str) -> ManagedProcess | None:
        with self._lock:
            return self._items.get(process_id)

    def list(self, cwd: Path) -> list[ManagedProcess]:
        with self._lock:
            return [item for item in self._items.values() if item.cwd == cwd]

    def stop(self, process_id: str) -> ManagedProcess:
        item = self.get(process_id)
        if item is None:
            raise KeyError(process_id)
        if item.process.poll() is None:
            self._terminate_tree(item.process, force=False)
            try:
                item.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate_tree(item.process, force=True)
                item.process.wait(timeout=5)
        return item

    @staticmethod
    def _terminate_tree(process: subprocess.Popen, *, force: bool) -> None:
        """Stop the process and every descendant created in its process group."""
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", *(("/F",) if force else ())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if completed.returncode == 0:
                return
            (process.kill if force else process.terminate)()
            return

        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            return

    def stop_all(self) -> None:
        for item in list(self._items.values()):
            if item.process.poll() is None:
                try:
                    self.stop(item.process_id)
                except OSError:
                    pass


PROCESS_MANAGER = ProcessManager()
atexit.register(PROCESS_MANAGER.stop_all)
