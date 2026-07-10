import os
import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src import cli
from src.schemas import Itinerary, DayPlan, Activity
from google.adk.events.event import Event
from google.genai import types

def make_mock_event(text: str) -> Event:
    return Event(
        id="mock-event",
        invocation_id="mock-inv",
        partial=False,
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=text)]
        )
    )

MOCK_ITINERARY = Itinerary(
    destination="Tokyo",
    days=[
        DayPlan(
            day=1,
            activities=[
                Activity(index=1, slot="Morning", activity="Sensō-ji", category="sightseeing", description="Temple"),
                Activity(index=2, slot="Afternoon", activity="Akihabara", category="shopping", description="Shop"),
                Activity(index=3, slot="Evening", activity="Yakitori", category="food", description="Eat"),
            ]
        )
    ]
)

@pytest.mark.anyio
@patch("questionary.text")
@patch("questionary.select")
@patch("builtins.input")
@patch("src.cli.Runner") # Mock Runner to avoid actual LLM calls
async def test_cli_main_loop(mock_runner_cls, mock_input, mock_select, mock_text, tmp_path):
    # Setup mocks for questionary
    mock_text.side_effect = lambda question, **kwargs: MagicMock(ask_async=AsyncMock(return_value={
        "Where do you want to go?": "Tokyo",
        "What is the vibe of the trip? (e.g., adventure, history, food, relaxation, nature)": "culture",
        "What is your home city? (for personalization)": "San Jose",
        "Do you have any dietary restrictions?": "none"
    }.get(question, "default_val")))
    
    mock_select.side_effect = lambda question, **kwargs: MagicMock(ask_async=AsyncMock(return_value={
        "How many days?": "1",
        "What is your budget tier?": "medium"
    }.get(question, "default_val")))

    # Setup inputs for the command loop:
    # 1. Lock index 1
    # 2. Swap index 2
    # 3. Regenerate with feedback
    # 4. Done (exit)
    mock_input.side_effect = [
        "/lock 1",
        "/swap 2",
        "/regenerate Add more food",
        "/done"
    ]

    # Setup Mock Runner behavior
    mock_runner = MagicMock()
    mock_runner.app_name = "travel_app"
    mock_runner_cls.return_value = mock_runner
    
    # We need to mock runner.session_service and its methods
    from google.adk.sessions.sqlite_session_service import SqliteSessionService
    db_path = str(tmp_path / "cli_test.db")
    session_service = SqliteSessionService(db_path)
    mock_runner.session_service = session_service

    # Mock runner.run to return itineraries
    # First call: generate_initial_itinerary
    # Second call: handle_swap
    # Third call: handle_regenerate
    mock_runner.run.side_effect = [
        [make_mock_event(MOCK_ITINERARY.model_dump_json())], # initial
        [make_mock_event(MOCK_ITINERARY.model_dump_json())], # swap (mock swap returning same for simplicity)
        [make_mock_event(MOCK_ITINERARY.model_dump_json())], # regen
    ]

    # Set mock db path in cli
    with patch("src.cli.DB_PATH", db_path):
        # We also need to mock environment variable check so it doesn't fail
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key", "GOOGLE_API_KEY": "fake_key"}):
            # Run the CLI main function
            await cli.run_app()

    # Verify that the session was ended (memory service called)
    # We can check if DB has the session data.
    # The session_service should have recorded the events.
    session = await session_service.get_session(app_name="travel_app", user_id=cli.USER_ID, session_id=cli.SESSION_ID)
    assert session is not None
    assert session.state["locked_indices"] == [1]
    assert "shopping" in session.state["rejected_categories"] # swap 2 should have rejected shopping
    assert session.state["current_itinerary"] is not None
    
    # Check that runner.run was called 3 times (init, swap, regen)
    assert mock_runner.run.call_count == 3

@pytest.mark.anyio
@patch("questionary.confirm")
@patch("builtins.input")
@patch("src.cli.Runner")
async def test_cli_resume_flow(mock_runner_cls, mock_input, mock_confirm, tmp_path):
    # Setup confirm mock to return True (resume)
    mock_confirm.side_effect = lambda question, **kwargs: MagicMock(ask_async=AsyncMock(return_value=True))

    # Setup inputs for the command loop: just exit immediately
    mock_input.side_effect = ["/done"]

    # Setup Mock Runner
    mock_runner = MagicMock()
    mock_runner.app_name = "travel_app"
    mock_runner_cls.return_value = mock_runner
    
    from google.adk.sessions.sqlite_session_service import SqliteSessionService
    db_path = str(tmp_path / "cli_test_resume.db")
    session_service = SqliteSessionService(db_path)
    mock_runner.session_service = session_service

    # Pre-populate the session in DB
    session = await session_service.create_session(
        app_name="travel_app",
        user_id=cli.USER_ID,
        session_id=cli.SESSION_ID,
        state={
            "explicit_preferences": {"home_city": "San Jose"},
            "locked_indices": [2],
            "rejected_categories": [],
            "current_itinerary": MOCK_ITINERARY.model_dump()
        }
    )

    # Set mock db path in cli
    with patch("src.cli.DB_PATH", db_path):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key", "GOOGLE_API_KEY": "fake_key"}):
            await cli.run_app()

    # Verify that runner.run was NOT called because we resumed and exited
    assert mock_runner.run.call_count == 0
    
    # Verify state is preserved
    retrieved_session = await session_service.get_session(
        app_name="travel_app", user_id=cli.USER_ID, session_id=cli.SESSION_ID
    )
    assert retrieved_session.state["locked_indices"] == [2]
    assert retrieved_session.state["current_itinerary"] == MOCK_ITINERARY.model_dump()

@pytest.mark.anyio
@patch("questionary.text")
@patch("questionary.select")
@patch("builtins.input")
@patch("src.cli.Runner")
@patch("src.telemetry.setup_telemetry")
async def test_cli_with_trace(mock_setup_telemetry, mock_runner_cls, mock_input, mock_select, mock_text, tmp_path):
    # Setup mocks
    mock_text.side_effect = lambda question, **kwargs: MagicMock(ask_async=AsyncMock(return_value={
        "Where do you want to go?": "Tokyo",
        "What is the vibe of the trip? (e.g., adventure, history, food, relaxation, nature)": "culture",
        "What is your home city? (for personalization)": "San Jose",
        "Do you have any dietary restrictions?": "none"
    }.get(question, "default_val")))
    mock_select.side_effect = lambda question, **kwargs: MagicMock(ask_async=AsyncMock(return_value={
        "How many days?": "1",
        "What is your budget tier?": "medium"
    }.get(question, "default_val")))
    mock_input.side_effect = ["/done"]

    mock_runner = MagicMock()
    mock_runner.app_name = "travel_app"
    mock_runner_cls.return_value = mock_runner
    
    from google.adk.sessions.sqlite_session_service import SqliteSessionService
    db_path = str(tmp_path / "cli_test_trace.db")
    session_service = SqliteSessionService(db_path)
    mock_runner.session_service = session_service
    
    mock_runner.run.return_value = [make_mock_event(MOCK_ITINERARY.model_dump_json())]

    with patch("src.cli.DB_PATH", db_path):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "fake_key", "GOOGLE_API_KEY": "fake_key"}):
            await cli.run_app(trace=True)

    mock_setup_telemetry.assert_called_once_with(db_path)
