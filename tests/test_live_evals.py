import os
import sys
import pytest

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.adk.runners import Runner
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from src.memory_service import SQLiteMemoryService
from src.agent import create_travel_app
from src.schemas import Itinerary

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
# Enable if we have a key that doesn't look like a placeholder
is_live_test_enabled = api_key and api_key != "fake_key" and not api_key.startswith("your_")

pytestmark = pytest.mark.skipif(
    not is_live_test_enabled,
    reason="Live tests require a valid GEMINI_API_KEY or GOOGLE_API_KEY in the environment."
)

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "live_eval.db")

@pytest.fixture
async def live_runner(db_path):
    session_service = SqliteSessionService(db_path)
    memory_service = SQLiteMemoryService(db_path)
    
    # Use real app
    app = create_travel_app()
    
    runner = Runner(
        app=app,
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=memory_service,
    )
    yield runner

@pytest.mark.anyio
async def test_live_weather_fallback_adaptation(live_runner, monkeypatch):
    """Verifies that the real LLM processes the weather API fallback and includes the warning."""
    # Simulate weather API failure
    monkeypatch.setenv("MOCK_WEATHER_API_FAIL", "1")
    
    destination = "London"
    user_id = "live_eval_user"
    session_id = "live_eval_session"
    
    await live_runner.session_service.create_session(
        app_name=live_runner.app_name,
        user_id=user_id,
        session_id=session_id,
        state={
            "explicit_preferences": {"home_city": "New York", "budget_tier": "medium", "dietary_restrictions": "none"},
            "locked_indices": [],
            "rejected_categories": [],
            "current_itinerary": None
        }
    )
    
    from google.genai import types
    prompt = f"Plan a 1-day trip to {destination}. Vibe: museums."
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)]
    )
    
    events = []
    async for event in live_runner.run_async(
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
    
    try:
        itinerary = Itinerary.model_validate_json(response_text)
        assert itinerary.destination.lower() == "london"
        assert len(itinerary.days) == 1
        
        # Check if the warning is present in at least one activity description.
        # We look for "fallback" or "weather" or "unavailable" in descriptions.
        warning_found = False
        for day in itinerary.days:
            for act in day.activities:
                desc_lower = act.description.lower()
                if "fallback" in desc_lower or "weather" in desc_lower or "unavailable" in desc_lower:
                    warning_found = True
                    break
            if warning_found:
                break
                
        assert warning_found, f"Expected fallback warning in activity descriptions, but got: {response_text}"
        print(f"\n✅ Live test passed. Itinerary:\n{itinerary.model_dump_json(indent=2)}")
        
    except Exception as e:
        pytest.fail(f"Failed to parse or validate itinerary: {e}. Response was: {response_text}")

@pytest.mark.anyio
async def test_live_context_compaction(live_runner):
    """Verifies that the context compaction is triggered and creates a summary event."""
    user_id = "live_compaction_user"
    session_id = "live_compaction_session"
    
    # Start session
    await live_runner.session_service.create_session(
        app_name=live_runner.app_name,
        user_id=user_id,
        session_id=session_id,
        state={
            "explicit_preferences": {"home_city": "New York", "budget_tier": "medium", "dietary_restrictions": "none"},
            "locked_indices": [],
            "rejected_categories": [],
            "current_itinerary": None
        }
    )
    
    from google.genai import types
    
    # We need to perform at least 3 interactions to trigger compaction (compaction_interval=3)
    prompts = [
        "Plan a 1-day trip to Tokyo. Vibe: tech.",
        "Actually, swap the morning activity.",
        "And swap the afternoon activity.",
    ]
    
    for i, prompt in enumerate(prompts):
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)]
        )
        events = []
        async for event in live_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message
        ):
            events.append(event)
        print(f"Run {i+1} completed. Events yielded: {len(events)}")
        
    # Now check the session events in the DB
    session = await live_runner.session_service.get_session(
        app_name=live_runner.app_name, user_id=user_id, session_id=session_id
    )
    
    print(f"\nTotal events in session: {len(session.events)}")
    for e in session.events:
        is_comp = "YES" if e.actions and e.actions.compaction else "NO"
        print(f"Event: ID={e.id}, Author={e.author}, InvocationID={e.invocation_id}, Compaction={is_comp}")
        if e.actions and e.actions.compaction:
            print(f"  Summary: {e.actions.compaction.compacted_content.parts[0].text[:100]}...")
            
    compaction_events = [e for e in session.events if e.actions and e.actions.compaction]
    assert len(compaction_events) > 0, "Expected at least one compaction event after 3 runs"
    
    comp_event = compaction_events[0]
    assert comp_event.actions.compaction.compacted_content is not None
    assert comp_event.actions.compaction.compacted_content.parts[0].text

