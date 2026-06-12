# core/logger.py
from __future__ import annotations
import json
import inspect
import logging
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

from sanapo.addr import Addr
from sanapo.enums import Logs

if TYPE_CHECKING:
    from sanapo.config import Config
    from sanapo.translator import Translator

# TODO in v2: different output and settings for WrameWork log and APP log
class Logger:
    _print_lock = threading.Lock()
    def __init__(self,
                addr: Addr | str,
                config: Config,
                translator: Translator | None = None
            ) -> None:
        self._addr = f"[{addr}]"
        self._cfg = config
        self._translator: Translator | None = translator

        self.file_handler = RotatingFileHandler(
            "sanapo.log", maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        import os
        if config.PATH_LOGS and not os.path.exists(config.PATH_LOGS):
            os.makedirs(config.PATH_LOGS, exist_ok=True)
        
    def set_translator(self, translator: Translator) -> None:
        self._translator = translator

    def _output(self, level: Logs, text: str, **kwargs) -> None:
        
        if self._translator:
            translated_text = self._translator.translate(text, **kwargs)
        else:
            translated_text = text.format(**kwargs) if kwargs else text

        COLORS = {
            "crt": "\033[41m\033[37m", # white on red
            "err": "\033[91m",         # red
            "wrn": "\033[93m",         # yellow
            "inf": "\033[92m",         # green
            "dbg": "\033[94m",         # blue
            "end": "\033[0m"           # default
        }

        # Traceback for err crt
        trc_str = ""
        if level in [Logs.CRT, Logs.ERR]:
            import sys
            import traceback
            caller = inspect.stack()[3]
            filename = caller.filename.replace('\\', '/').split('/')[-1] # for os windows
            lineno = caller.lineno
            trc_str = f" ({filename}:{lineno})"
            if sys.exc_info()[0] is not None:
                trc_str += f"\n\033[91m{traceback.format_exc()}\033[0m"

        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_str = f"{time_str} {level.value} {self._addr}: {translated_text}{trc_str}"

        # Console.
        if level in self._cfg.DEFAULT_LOG_FLAGS["console"]:
            c_bgn = COLORS.get(level.value, "")
            c_end = COLORS.get('end', "")
            with self._print_lock:
                print(c_bgn + log_str + c_end)
                
        # File (string).
        if level in self._cfg.DEFAULT_LOG_FLAGS["file"]:
            self.file_handler.emit(logging.LogRecord(
                self._addr, logging.INFO, "", 0, log_str, None, None
            ))
    
    def err(self, text: str, **kwargs) -> None:
        self._output(Logs.ERR, text, **kwargs)

    def crt(self, text: str, **kwargs) -> None:
        self._output(Logs.CRT, text, **kwargs)

    def wrn(self, text: str, **kwargs) -> None:
        self._output(Logs.WRN, text, **kwargs)

    def inf(self, text: str, **kwargs) -> None:
        self._output(Logs.INF, text, **kwargs)

    def dbg(self, text: str, **kwargs) -> None:
        self._output(Logs.DBG, text, **kwargs)
