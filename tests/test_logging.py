import logging
import json
import io
import pytest
from src.logger_config import PiiFilter, JsonFormatter

def test_pii_filter():
    pii_filter = PiiFilter()
    
    # Test email redaction
    assert pii_filter.redact("Contact me at test@example.com") == "Contact me at [REDACTED_EMAIL]"
    assert pii_filter.redact("My emails are a@b.com and x@y.org") == "My emails are [REDACTED_EMAIL] and [REDACTED_EMAIL]"
    
    # Test phone redaction
    assert pii_filter.redact("Call 123-456-7890") == "Call [REDACTED_PHONE]"
    assert pii_filter.redact("My number is (123) 456-7890.") == "My number is [REDACTED_PHONE]."
    assert pii_filter.redact("Try +1-123-456-7890 or 123.456.7890") == "Try [REDACTED_PHONE] or [REDACTED_PHONE]"
    
    # Test mixed
    assert pii_filter.redact("Email test@example.com or call 123-456-7890") == "Email [REDACTED_EMAIL] or call [REDACTED_PHONE]"

def test_json_formatter():
    formatter = JsonFormatter()
    logger = logging.getLogger("test_json_formatter")
    
    # Capture log output
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    logger.info("Hello world", extra={"user_id": "123", "action": "test"})
    
    output = log_capture.getvalue().strip()
    assert output != ""
    
    # Verify it is valid JSON
    log_data = json.loads(output)
    assert log_data["message"] == "Hello world"
    assert log_data["logger"] == "test_json_formatter"
    assert log_data["level"] == "INFO"
    assert "timestamp" in log_data
    assert "extra" in log_data
    assert log_data["extra"]["user_id"] == "123"
    assert log_data["extra"]["action"] == "test"
    
    # Test exception formatting
    try:
        raise ValueError("Simulated error")
    except ValueError:
        logger.exception("Something went wrong")
        
    output_lines = log_capture.getvalue().strip().split("\n")
    exc_output = output_lines[-1]
    exc_data = json.loads(exc_output)
    assert exc_data["message"] == "Something went wrong"
    assert "exception" in exc_data
    assert "ValueError: Simulated error" in exc_data["exception"]


def test_structured_logging_callbacks():
    from unittest.mock import MagicMock
    from google.genai import types
    from google.adk.models.llm_response import LlmResponse
    from src.agent import router_after_model_callback, planner_after_model_callback
    from src.schemas import Itinerary, DayPlan, Activity
    
    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    
    # 1. Test Router callback logging
    mock_ctx = MagicMock()
    mock_ctx.session.id = "session_123"
    
    fc = types.FunctionCall(name="transfer_to_agent", args={"agent_name": "planner_agent"})
    mock_response = LlmResponse(
        content=types.Content(role="model", parts=[types.Part(function_call=fc)])
    )
    
    router_after_model_callback(mock_ctx, mock_response)
    
    output = log_capture.getvalue().strip()
    assert output != ""
    log_data = json.loads(output)
    assert log_data["message"] == "Router routing to planner_agent"
    assert log_data["extra"]["session_id"] == "session_123"
    assert log_data["extra"]["target_agent"] == "planner_agent"
    
    # Clear capture
    log_capture.seek(0)
    log_capture.truncate(0)
    
    # 2. Test Planner callback logging
    mock_itinerary = Itinerary(
        destination="Tokyo",
        days=[
            DayPlan(
                day=1,
                activities=[
                    Activity(index=1, slot="Morning", activity="A", category="food", description=""),
                    Activity(index=2, slot="Morning", activity="B", category="food", description=""),
                ]
            )
        ]
    )
    
    mock_planner_response = LlmResponse(
        content=types.Content(role="model", parts=[types.Part.from_text(text=mock_itinerary.model_dump_json())])
    )
    
    mock_ctx.session.events = []
    
    planner_after_model_callback(mock_ctx, mock_planner_response)
    
    output = log_capture.getvalue().strip()
    assert output != ""
    lines = output.split("\n")
    # Find our log in the lines (might have other logs if handlers are shared)
    our_log = None
    for line in reversed(lines):
        if line.strip():
            data = json.loads(line)
            if data["logger"] == "src.agent":
                our_log = data
                break
    assert our_log is not None
    assert "Itinerary generated for Tokyo" in our_log["message"]
    assert our_log["extra"]["session_id"] == "session_123"
    assert our_log["extra"]["warnings_count"] == 1
    assert "duplicate slots" in our_log["extra"]["warnings"][0]
