import os
import sys
import pytest
from typing import Generator
from unittest.mock import patch, AsyncMock
from google.genai import types

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.tools import search_places, get_weather_forecast, estimate_transit_time, book_trip_mock
from src.agent import create_travel_agent
from src.schemas import Itinerary, DayPlan, Activity
from google.adk.runners import Runner
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.adk.sessions.session import Session

from src.memory_service import SQLiteMemoryService

# =====================================================================
# Unit Tests for Mock Tools
# =====================================================================

def test_search_places_success():
    res = search_places("hotels", "Tokyo")
    assert res["status"] == "success"
    assert len(res["places"]) > 0
    assert any("Hotel" in p["name"] or "Hostel" in p["name"] for p in res["places"])

def test_search_places_fallback(monkeypatch):
    monkeypatch.setenv("MOCK_PLACES_API_FAIL", "1")
    res = search_places("hotels", "Tokyo")
    assert res["status"] == "fallback"
    assert len(res["places"]) == 2
    assert "Local Park" in res["places"][0]["name"]

def test_get_weather_forecast_success():
    res = get_weather_forecast("Tokyo", days=2)
    assert res["status"] == "success"
    assert len(res["forecast"]) == 2
    assert "weather" in res["forecast"][0]
    assert "temp" in res["forecast"][0]

def test_get_weather_forecast_fallback(monkeypatch):
    monkeypatch.setenv("MOCK_WEATHER_API_FAIL", "1")
    res = get_weather_forecast("Tokyo", days=3)
    assert res["status"] == "fallback"
    assert len(res["forecast"]) == 3
    assert res["forecast"][0]["weather"] == "Fair"

def test_estimate_transit_time_success():
    # Tokyo to Kyoto
    res = estimate_transit_time("Tokyo", "Kyoto", mode="driving")
    assert res["status"] == "success"
    assert res["distance_km"] > 0
    assert res["duration_minutes"] > 0
    assert res["mode"] == "driving"

def test_estimate_transit_time_fallback():
    # Unknown city
    res = estimate_transit_time("Tokyo", "Atlantis", mode="driving")
    assert res["status"] == "fallback_default"
    assert res["distance_km"] == 15.0
    assert res["duration_minutes"] == 30 # 15km / 30km/h = 0.5h = 30m

def test_book_trip_mock():
    res = book_trip_mock("Tokyo", "2026-08-01", "2026-08-05", "medium")
    assert res["status"] == "success"
    assert res["booking_reference"] == "KICK-12345"
    assert res["flight"]["price_usd"] == 300
    assert "Comfort Suites" in res["hotel"]["name"]


# =====================================================================
# Integration Test for Travel Agent (Requires Gemini API Key)
# =====================================================================

def extract_event_text(event) -> str:
    if event.content and event.content.parts:
        text_parts = []
        for part in event.content.parts:
            if part.text:
                text_parts.append(part.text)
        return "".join(text_parts).strip()
    return ""

@pytest.mark.anyio
@patch("google.genai.models.AsyncModels.generate_content")
async def test_travel_agent_itinerary_generation(mock_generate_content, tmp_path, monkeypatch):
    # Set fake API key for ADK initialization
    monkeypatch.setenv("GEMINI_API_KEY", "fake_key")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake_key")

    # Setup mock LLM response
    mock_itinerary = Itinerary(
        destination="Tokyo",
        days=[
            DayPlan(
                day=1,
                activities=[
                    Activity(index=1, slot="Morning", activity="Sensō-ji", category="sightseeing", description="Temple"),
                ]
            )
        ]
    )
    
    mock_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(text=mock_itinerary.model_dump_json())
                    ]
                )
            )
        ]
    )
    mock_generate_content.return_value = mock_response

    db_path = str(tmp_path / "test_agent.db")
    
    # Initialize Services
    session_service = SqliteSessionService(db_path)
    memory_service = SQLiteMemoryService(db_path)
    
    # Pre-populate memory with user profile to test personalization
    # User is from San Francisco, budget is medium, rejects shopping
    # We want to make sure the agent doesn't recommend shopping in Tokyo if it reads this,
    # or at least respects it.
    await memory_service.add_session_to_memory(
        Session(
            id="pre-session",
            app_name="travel_app",
            user_id="user_123",
            state={
                "explicit_preferences": {
                    "home_city": "San Francisco",
                    "budget_tier": "medium",
                    "dietary_restrictions": "none"
                },
                "rejected_categories": ["shopping"]
            }
        )
    )

    # Create Agent and Runner
    agent = create_travel_agent()
    runner = Runner(
        app_name="travel_app",
        agent=agent,
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=memory_service,
    )

    # Create Session
    session_id = "session_123"
    user_id = "user_123"
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
    )

    # Run query
    # Ask for a 1-day trip to Tokyo.
    # The agent should use search_places (for hotels/activities), get_weather_forecast,
    # and maybe estimate_transit_time.
    # It should output structured JSON matching Itinerary.
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Plan a 1-day trip to Tokyo. I want to see historical sites.")],
    )

    # Run the agent
    events = list(
        runner.run(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
        )
    )

    response_text = ""
    for event in events:
        text = extract_event_text(event)
        if text:
            response_text += text

    assert response_text != ""
    
    # Verify it is valid JSON and matches the Itinerary schema
    try:
        itinerary = Itinerary.model_validate_json(response_text)
        assert itinerary.destination.lower() == "tokyo"
        assert len(itinerary.days) == 1
        day = itinerary.days[0]
        assert day.day == 1
        assert len(day.activities) > 0
        
        # Check that none of the activities are 'shopping' category,
        # since we rejected it in memory.
        for act in day.activities:
            assert act.category.lower() != "shopping", f"Should have avoided shopping, but got: {act.activity}"
            
        print(f"\nGenerated Itinerary:\n{itinerary.model_dump_json(indent=2)}")
        
    except Exception as e:
        pytest.fail(f"Failed to parse agent response as Itinerary: {e}\nResponse was: {response_text}")
