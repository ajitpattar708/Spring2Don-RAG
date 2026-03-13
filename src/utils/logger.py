"""
Logging utilities
"""

import logging
import os
import sys


class ColorFormatter(logging.Formatter):
    """Simple ANSI color formatter for terminal log output."""

    RESET = "\033[0m"
    COLORS = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[34m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[1;31m",
        logging.CRITICAL: "\033[1;35m",
    }

    def __init__(self, fmt: str, datefmt: str | None = None, use_color: bool = True):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original_levelname = record.levelname
        original_name = record.name

        if self.use_color:
            color = self.COLORS.get(record.levelno, "")
            if color:
                record.levelname = f"{color}{record.levelname}{self.RESET}"
                record.name = f"\033[94m{record.name}{self.RESET}"

        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname
            record.name = original_name


def _should_use_color(stream) -> bool:
    """Enable colors for interactive terminals unless explicitly disabled."""
    no_color = os.getenv("NO_COLOR")
    log_color = os.getenv("LOG_COLOR", "auto").lower()

    if no_color is not None or log_color in {"0", "false", "never", "off"}:
        return False
    if log_color in {"1", "true", "always", "on"}:
        return True
    return hasattr(stream, "isatty") and stream.isatty()


_TEXT_COLORS = {
    "title": "\033[1;35m",
    "phase": "\033[1;36m",
    "info": "\033[34m",
    "ok": "\033[32m",
    "warn": "\033[33m",
    "error": "\033[1;31m",
    "muted": "\033[90m",
}


def color_text(text: str, role: str = "info", stream=None) -> str:
    """Colorize plain terminal text for migration progress output."""
    target_stream = stream or sys.stdout
    if not _should_use_color(target_stream):
        return text
    color = _TEXT_COLORS.get(role, "")
    if not color:
        return text
    return f"{color}{text}{ColorFormatter.RESET}"


def setup_logger(name: str, log_level: str = None) -> logging.Logger:
    """Setup logger with consistent formatting"""
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    # Set log level
    level = log_level or os.getenv('LOG_LEVEL', 'INFO')
    logger.setLevel(getattr(logging, level.upper()))
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    
    # Create formatter
    formatter = ColorFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        use_color=_should_use_color(sys.stdout)
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    logger.propagate = False
    
    return logger
