import collections
import logging
import traceback

BUFFER: collections.deque = collections.deque(maxlen=1500)
_installed = False


class BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("uvicorn.access", "httpx", "httpcore")):
            return
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + "".join(traceback.format_exception(*record.exc_info)).strip()
        BUFFER.append({"ts": record.created, "level": record.levelname, "name": record.name, "msg": msg})


def install() -> None:
    global _installed
    if _installed:
        return
    root = logging.getLogger()
    root.addHandler(BufferHandler(level=logging.INFO))
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    _installed = True


def tail(level: str = "INFO", limit: int = 200) -> list[dict]:
    order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    floor = order.get(level.upper(), 20)
    rows = [r for r in BUFFER if order.get(r["level"], 20) >= floor]
    return rows[-limit:][::-1]  # newest first
