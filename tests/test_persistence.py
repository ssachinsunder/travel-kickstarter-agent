import os
import sys
import pytest
import aiosqlite

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.adk.sessions.session import Session
from google.adk.events.event import Event
from src.memory_service import SQLiteMemoryService

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_kickstart.db")

@pytest.mark.anyio
async def test_sqlite_session_service_lifecycle(db_path):
    # Initialize service
    session_service = SqliteSessionService(db_path)
    
    app_name = "test_app"
    user_id = "test_user"
    session_id = "test_session"
    initial_state = {"key1": "value1", "user:pref1": "val1"}
    
    # 1. Create Session
    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        state=initial_state,
        session_id=session_id
    )
    
    assert session.id == session_id
    assert session.app_name == app_name
    assert session.user_id == user_id
    # ADK splits state into session, user, app.
    # "user:pref1" should be in user state, "key1" in session state?
    # Actually let's just check if we can retrieve it.
    
    # 2. Get Session
    retrieved_session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id
    )
    assert retrieved_session is not None
    assert retrieved_session.id == session_id
    assert retrieved_session.state["key1"] == "value1"
    
    # 3. Append Event (this updates state if event has state_delta)
    # Event and Action structure in ADK is complex, but we can try to mock/construct it.
    # For simple test, we just verify we can append an event.
    event = Event(id="event-1", partial=False)
    await session_service.append_event(retrieved_session, event)
    
    # Get session again to verify event is appended
    retrieved_session2 = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id
    )
    assert len(retrieved_session2.events) == 1
    assert retrieved_session2.events[0].id == "event-1"
    
    # 4. List Sessions
    sessions_response = await session_service.list_sessions(app_name=app_name, user_id=user_id)
    assert len(sessions_response.sessions) == 1
    assert sessions_response.sessions[0].id == session_id
    
    # 5. Delete Session
    await session_service.delete_session(app_name=app_name, user_id=user_id, session_id=session_id)
    
    # Verify it is deleted
    deleted_session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id
    )
    assert deleted_session is None

@pytest.mark.anyio
async def test_sqlite_memory_service(db_path):
    memory_service = SQLiteMemoryService(db_path)
    
    user_id = "test_user_memory"
    app_name = "test_app"
    
    # 1. Test empty memory
    response = await memory_service.search_memory(app_name=app_name, user_id=user_id, query="anything")
    assert len(response.memories) == 0
    
    # 2. Add session with preferences to memory
    session = Session(
        id="session-1",
        app_name=app_name,
        user_id=user_id,
        state={
            "explicit_preferences": {
                "home_city": "San Jose",
                "budget_tier": "medium",
                "dietary_restrictions": "none"
            },
            "rejected_categories": ["museum", "nature"]
        }
    )
    
    await memory_service.add_session_to_memory(session)
    
    # 3. Search memory and verify content
    response = await memory_service.search_memory(app_name=app_name, user_id=user_id, query="profile")
    assert len(response.memories) == 1
    memory_entry = response.memories[0]
    assert memory_entry.author == "System"
    
    text = memory_entry.content.parts[0].text
    assert "User Profile" in text
    assert "Home City: San Jose" in text
    assert "Budget: medium" in text
    assert "Dietary Restrictions: none" in text
    assert "User Preference Weights" in text
    # Weights should be decayed (default 1.0 * 0.5 = 0.5)
    assert "museum: 0.50" in text
    assert "nature: 0.50" in text
    
    # 4. Add another session to verify merging and further decay
    session2 = Session(
        id="session-2",
        app_name=app_name,
        user_id=user_id,
        state={
            "explicit_preferences": {
                # omit home_city, it should be preserved
                "budget_tier": "high", # update budget
                "dietary_restrictions": "vegan" # update diet
            },
            "rejected_categories": ["museum", "shopping"] # museum rejected again, shopping first time
        }
    )
    
    await memory_service.add_session_to_memory(session2)
    
    response2 = await memory_service.search_memory(app_name=app_name, user_id=user_id, query="profile")
    assert len(response2.memories) == 1
    text2 = response2.memories[0].content.parts[0].text
    
    assert "Home City: San Jose" in text2 # preserved
    assert "Budget: high" in text2 # updated
    assert "Dietary Restrictions: vegan" in text2 # updated
    
    # museum decayed twice: 1.0 * 0.5 * 0.5 = 0.25
    assert "museum: 0.25" in text2
    # nature preserved at 0.5
    assert "nature: 0.50" in text2
    # shopping decayed once: 1.0 * 0.5 = 0.5
    assert "shopping: 0.50" in text2
