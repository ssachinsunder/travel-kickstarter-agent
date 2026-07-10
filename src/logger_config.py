import json
import logging
import re
from typing import Optional, Any

# PII regex patterns
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
# Simple phone regex for common formats
PHONE_REGEX = re.compile(r"(?:\+?1[-. ]?)?\(?\b([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})\b")

class PiiFilter(logging.Filter):
    """Filters out PII from log messages."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redact(record.msg)
        elif isinstance(record.msg, dict):
            record.msg = self.redact_dict(record.msg)
        
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(self.redact(arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
            
        return True

    def redact(self, text: str) -> str:
        text = EMAIL_REGEX.sub("[REDACTED_EMAIL]", text)
        text = PHONE_REGEX.sub("[REDACTED_PHONE]", text)
        return text

    def redact_dict(self, d: dict) -> dict:
        new_dict = {}
        for k, v in d.items():
            if isinstance(v, str):
                new_dict[k] = self.redact(v)
            elif isinstance(v, dict):
                new_dict[k] = self.redact_dict(v)
            else:
                new_dict[k] = v
        return new_dict

class JsonFormatter(logging.Formatter):
    """Formats log records as JSON."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        # Extract extra fields
        standard_fields = {
            'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
            'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
            'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
            'processName', 'process', 'message', 'asctime'
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in standard_fields}
        if extra:
            log_data["extra"] = extra
            
        return json.dumps(log_data)

def setup_logging(level: int = logging.INFO, filename: Optional[str] = None):
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    if filename:
        handler = logging.FileHandler(filename)
    else:
        handler = logging.StreamHandler()
        
    handler.setFormatter(JsonFormatter())
    handler.addFilter(PiiFilter())
    root_logger.addHandler(handler)
