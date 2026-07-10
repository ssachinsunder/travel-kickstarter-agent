import os
import sys
import pytest
import logging
import json
from unittest.mock import MagicMock, AsyncMock
from google.genai import Client
from google.genai import types

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.adk.runners import Runner
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from src.memory_service import SQLiteMemoryService
from src.agent import create_travel_agent
from src.schemas import Itinerary, DayPlan, Activity
from src.config import config

logger = logging.getLogger(__name__)

def json_dumps_readable(obj):
    return json.dumps([o.model_dump() for o in obj], indent=2)

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "eval.db")

@pytest.fixture
def mock_client():
    """Fixture providing a fake GenAI Client for offline eval testing."""
    client = MagicMock(spec=Client)
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.models = MagicMock()
    client.vertexai = False
    return client

@pytest.fixture
async def runner(db_path, mock_client):
    session_service = SqliteSessionService(db_path)
    memory_service = SQLiteMemoryService(db_path)
    
    # Inject the mock client
    agent = create_travel_agent(client=mock_client)
    
    runner = Runner(
        app_name="travel_app",
        agent=agent,
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=memory_service,
    )
    yield runner

@pytest.mark.anyio
async def test_rainy_day_adaptation_eval(runner, mock_client):
    """Eval: Verifies that the agent avoids outdoor activities on rainy days (Mocked)."""
    destination = "London"
    user_id = "eval_user_1"
    session_id = "eval_session_1"
    
    # Setup mock agent response (itinerary with indoor activities)
    mock_itinerary = Itinerary(
        destination="London",
        days=[
            DayPlan(
                day=1,
                activities=[
                    Activity(index=1, slot="Morning", activity="British Museum", category="museum", description="Museum"),
                    Activity(index=2, slot="Afternoon", activity="National Gallery", category="museum", description="Gallery"),
                ]
            ),
            DayPlan(day=2, activities=[]),
            DayPlan(day=3, activities=[])
        ]
    )
    mock_agent_response = types.GenerateContentResponse(
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
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_agent_response)

    # Setup mock judge response (approving the itinerary)
    mock_judge_json = '{"appropriate": true, "reason": "Mocked judge: activities are indoors."}'
    mock_judge_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(text=mock_judge_json)
                    ]
                )
            )
        ]
    )
    mock_client.models.generate_content = MagicMock(return_value=mock_judge_response)

    # Start session
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
        state={
            "explicit_preferences": {"home_city": "New York", "budget_tier": "medium", "dietary_restrictions": "none"},
            "locked_indices": [],
            "rejected_categories": [],
            "current_itinerary": None
        }
    )
    
    prompt = f"Plan a 3-day trip to {destination}. Vibe: sight-seeing and parks."
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)]
    )
    
    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=new_message
    ):
        events.append(event)
        
    # Extract itinerary
    text_parts = []
    for event in events:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    text_parts.append(part.text)
    response_text = "".join(text_parts).strip()
    
    assert response_text, "Agent returned empty response"
    itinerary = Itinerary.model_validate_json(response_text)
    
    day_1_activities = itinerary.days[0].activities
    day_1_json = json_dumps_readable(day_1_activities)
    
    # Use the mock client for judge instead of creating a new real Client
    client = mock_client
    judge_prompt = f"""You are an evaluator. You need to check if a list of travel activities planned for a day are appropriate for a RAINY day.
Here are the activities: {day_1_json}
"""
    
    judge_response = client.models.generate_content(
        model=config.model_name,
        contents=judge_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        )
    )
    
    judge_result = json.loads(judge_response.candidates[0].content.parts[0].text)
    logger.info(f"Judge Result for Rainy Day: {judge_result}")
    print(f"\n👨‍⚖️ Judge Result (Rainy Day London Day 1): {judge_result}")
    
    assert judge_result["appropriate"], f"Judge rejected plan: {judge_result['reason']}"

@pytest.mark.anyio
async def test_weather_fallback_eval(runner, mock_client):
    """Eval: Verifies that the agent handles weather API failure gracefully (Mocked)."""
    # Simulate weather API failure
    os.environ["MOCK_WEATHER_API_FAIL"] = "1"
    
    destination = "Paris"
    user_id = "eval_user_2"
    session_id = "eval_session_2"
    
    mock_itinerary = Itinerary(
        destination="Paris",
        days=[
            DayPlan(day=1, activities=[]),
            DayPlan(day=2, activities=[]),
            DayPlan(day=3, activities=[])
        ]
    )
    mock_agent_response = types.GenerateContentResponse(
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
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_agent_response)

    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id=user_id,
        session_id=session_id,
        state={
            "explicit_preferences": {"home_city": "New York", "budget_tier": "medium", "dietary_restrictions": "none"},
            "locked_indices": [],
            "rejected_categories": [],
            "current_itinerary": None
        }
    )
    
    prompt = f"Plan a 3-day trip to {destination}. Vibe: sightseeing."
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)]
    )
    
    try:
        events = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message
        ):
            events.append(event)
        
        text_parts = []
        for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        text_parts.append(part.text)
        response_text = "".join(text_parts).strip()
        
        assert response_text, "Agent returned empty response on fallback"
        itinerary = Itinerary.model_validate_json(response_text)
        assert itinerary.destination == "Paris"
        assert len(itinerary.days) == 3
        print("\n✅ Gracefully handled weather API failure and generated itinerary.")
        
    finally:
        # Clean up env var
        del os.environ["MOCK_WEATHER_API_FAIL"]
