"""What reaches the kiosk's journal (journalctl -u home-organizer).

- The app's own INFO messages ("Woke the screen", "Reply voice loaded"): with
  no handler configured, Python only ever printed warnings and worse.
- Not uvicorn's line for every successful GET: the page polls several
  endpoints every second or faster, which buried everything else. Changes
  (POST, PATCH, DELETE) and failures are still logged.
- The caldav library only at ERROR: its warnings quote raw calendar data
  (event descriptions, addresses) on every sync.
- Not onnxruntime's warning, twice per start, that there's no GPU engine
  (CUDA) to use: the wake-word models ask for one first, and this machine
  has none, so the CPU is used as intended.
"""

import logging
import warnings

_FORMAT = "%(levelname)s [%(name)s] %(message)s"


class QuietSuccessfulReads(logging.Filter):
    """Drops uvicorn access lines for GETs that succeeded."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5:
            _client, method, _path, _http_version, status = args
            return not (method == "GET" and isinstance(status, int) and status < 400)
        return True


def configure_logging() -> None:
    app_logger = logging.getLogger("app")
    if not any(getattr(h, "_home_organizer", False) for h in app_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._home_organizer = True  # so a reload doesn't add a second one
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)

    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QuietSuccessfulReads) for f in access.filters):
        access.addFilter(QuietSuccessfulReads())

    logging.getLogger("caldav").setLevel(logging.ERROR)

    warnings.filterwarnings("ignore", message=r"Specified provider 'CUDAExecutionProvider' is not in available provider")
