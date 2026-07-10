import os
import sys
import pytest
import logging
from google.genai import Client
from google.genai import types

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.adk.runners import Runner
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from src.memory_service import SQLiteMemoryService
from src.agent import create_travel_agent
from src.schemas import Itinerary
from src.config import config

import json

logger = logging.getLogger(__name__)

def json_dumps_readable(obj):
    return json.dumps([o.model_dump() for o in obj], indent=2)

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "eval.db")

@pytest.fixture
async def runner(db_path):
    session_service = SqliteSessionService(db_path)
    memory_service = SQLiteMemoryService(db_path)
    agent = create_travel_agent()
    return Runner(
        app_name="travel_app",
        agent=agent,
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=memory_service,
    )

@pytest.mark.anyio
async def test_rainy_day_adaptation_eval(runner):
    """Eval: Verifies that the agent avoids outdoor activities on rainy days."""
    # "London" (length 6) -> (6 + 0) % 4 = 2 (Rainy) for Day 1
    # Day 2: (6 + 1) % 4 = 3 (Windy)
    # Day 3: (6 + 2) % 4 = 0 (Sunny)
    destination = "London" 
    user_id = "eval_user_1"
    session_id = "eval_session_1"
    
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
    
    try:
        events = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message
        ):
            events.append(event)
    except Exception as e:
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            pytest.skip("Skipping eval due to Gemini API temporary unavailability.")
        raise e
    
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
    
    # Day 1 should be rainy. Let's verify by checking our tool logic:
    # get_weather_forecast("London", 3) should return Rainy for Day 1.
    # We can trust our mock tool returns this.
    
    # Now use LLM-as-a-judge to verify if Day 1 activities are indoor-appropriate.
    day_1_activities = itinerary.days[0].activities
    day_1_json = json_dumps_readable(day_1_activities)
    
    client = Client()
    judge_prompt = f"""You are an evaluator. You need to check if a list of travel activities planned for a day are appropriate for a RAINY day.
The activities should be primarily indoors (e.g. museums, indoor markets, restaurants, indoor galleries) and NOT outdoor-only (e.g. walking tours, parks, beaches, outdoor gardens).

Here are the activities planned for the day:
{day_1_json}

Is this plan appropriate for a rainy day?
Respond with ONLY a JSON object matching this schema:
{{
  "appropriate": boolean,
  "reason": "explanation of why it is or isn't appropriate"
}}
"""
    
    try:
        judge_response = client.models.generate_content(
            model=config.model_name,
            contents=judge_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "appropriate": types.Schema(type=types.Type.BOOLEAN),
                        "reason": types.Schema(type=types.Type.STRING)
                    },
                    required=["appropriate", "reason"]
                )
            )
        )
    except Exception as e:
        if "503" in str(e) or "UNAVAILABLE" in str(e):
            pytest.skip("Skipping eval due to Gemini API temporary unavailability during judging.")
        raise e
    
    judge_result = json.loads(judge_response.text)
    logger.info(f"Judge Result for Rainy Day: {judge_result}")
    print(f"\n👨‍⚖️ Judge Result (Rainy Day London Day 1): {judge_result}")
    
    assert judge_result["appropriate"], f"Judge rejected plan: {judge_result['reason']}"

@pytest.mark.anyio
async def test_weather_fallback_eval(runner):
    """Eval: Verifies that the agent handles weather API failure gracefully."""
    # Simulate weather API failure
    os.environ["MOCK_WEATHER_API_FAIL"] = "1"
    
    destination = "Paris"
    user_id = "eval_user_2"
    session_id = "eval_session_2"
    
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
        try:
            events = []
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=new_message
            ):
                events.append(event)
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                pytest.skip("Skipping eval due to Gemini API temporary unavailability.")
            raise e
        
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
