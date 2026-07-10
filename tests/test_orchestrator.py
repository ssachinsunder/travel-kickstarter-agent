import os
import sys
import pytest
import json
from unittest.mock import MagicMock, patch
from google.genai import types

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.adk.runners import Runner
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from google.adk.sessions.session import Session
from src.memory_service import SQLiteMemoryService
from src.orchestrator import TravelOrchestrator
from src.schemas import Itinerary, DayPlan, Activity

# Helper to construct a mock event with text
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

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_orch.db")

@pytest.fixture
async def orchestrator(db_path):
    session_service = SqliteSessionService(db_path)
    memory_service = SQLiteMemoryService(db_path)
    
    # Mock Runner
    runner = Runner(
        app_name="travel_app",
        agent=MagicMock(), # Mock agent
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=memory_service,
    )
    
    return TravelOrchestrator(runner, memory_service)

MOCK_ITINERARY_1 = Itinerary(
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
async def test_orchestrator_lifecycle_and_lock(orchestrator):
    user_id = "user_1"
    session_id = "session_1"
    explicit_prefs = {"home_city": "San Jose", "budget_tier": "medium"}
    
    # 1. Start Session
    session = await orchestrator.start_session(user_id, session_id, explicit_prefs)
    assert session.state["explicit_preferences"] == explicit_prefs
    assert session.state["locked_indices"] == []
    
    # 2. Generate Initial Itinerary (Mock LLM response)
    mock_json = MOCK_ITINERARY_1.model_dump_json()
    with patch.object(orchestrator.runner, 'run', return_value=[make_mock_event(mock_json)]) as mock_run:
        itinerary = await orchestrator.generate_initial_itinerary(
            user_id, session_id, "Tokyo", 1, "culture and food"
        )
        assert itinerary is not None
        assert itinerary.destination == "Tokyo"
        mock_run.assert_called_once()
        
        # Verify it was saved to session state
        retrieved_session = await orchestrator.runner.session_service.get_session(
            app_name=orchestrator.app_name, user_id=user_id, session_id=session_id
        )
        assert retrieved_session.state["current_itinerary"] == itinerary.model_dump()

    # 3. Handle Lock
    # Lock index 1 (Sensō-ji)
    lock_msg = await orchestrator.handle_lock(user_id, session_id, 1)
    assert "Locked activity 1" in lock_msg
    
    retrieved_session2 = await orchestrator.runner.session_service.get_session(
        app_name=orchestrator.app_name, user_id=user_id, session_id=session_id
    )
    assert retrieved_session2.state["locked_indices"] == [1]
    
    # Try locking it again
    lock_msg_again = await orchestrator.handle_lock(user_id, session_id, 1)
    assert "already locked" in lock_msg_again

    # Try locking invalid index
    lock_msg_invalid = await orchestrator.handle_lock(user_id, session_id, 99)
    assert "not found" in lock_msg_invalid

@pytest.mark.anyio
async def test_orchestrator_swap_and_safeguard(orchestrator):
    user_id = "user_2"
    session_id = "session_2"
    
    await orchestrator.start_session(user_id, session_id, {})
    
    # Set initial itinerary in state directly for this test
    session = await orchestrator.runner.session_service.get_session(
        app_name=orchestrator.app_name, user_id=user_id, session_id=session_id
    )
    # We need to append an event to set the initial itinerary
    init_event = Event(
        id="init-test-state",
        invocation_id="test",
        partial=False,
        actions=EventActions(state_delta={"current_itinerary": MOCK_ITINERARY_1.model_dump()})
    )
    await orchestrator.runner.session_service.append_event(session, init_event)
    
    # Lock index 3 (Yakitori)
    await orchestrator.handle_lock(user_id, session_id, 3)
    
    # Swap index 2 (Akihabara - category: shopping)
    # Mock LLM response for swap.
    # We will simulate a BAD LLM that tried to change the locked item 3 (Yakitori -> Sushi)
    # and also swapped Akihabara -> Gundam Base.
    bad_swapped_itinerary = Itinerary(
        destination="Tokyo",
        days=[
            DayPlan(
                day=1,
                activities=[
                    Activity(index=1, slot="Morning", activity="Sensō-ji", category="sightseeing", description="Temple"),
                    Activity(index=2, slot="Afternoon", activity="Gundam Base", category="shopping", description="Better Shop"), # swapped
                    Activity(index=3, slot="Evening", activity="Sushi", category="food", description="Eat Sushi"), # CHANGED LOCKED ITEM!
                ]
            )
        ]
    )
    
    mock_json = bad_swapped_itinerary.model_dump_json()
    with patch.object(orchestrator.runner, 'run', return_value=[make_mock_event(mock_json)]) as mock_run:
        new_itinerary = await orchestrator.handle_swap(user_id, session_id, 2)
        assert new_itinerary is not None
        mock_run.assert_called_once()
        
        # Verify that swap prompt contained the lock information
        called_args = mock_run.call_args[1]
        new_msg = called_args["new_message"]
        prompt_text = new_msg.parts[0].text
        assert "LOCKED" in prompt_text
        assert "Yakitori" in prompt_text # locked activity name should be in prompt
        
        # Verify rejection was recorded in session state
        retrieved_session = await orchestrator.runner.session_service.get_session(
            app_name=orchestrator.app_name, user_id=user_id, session_id=session_id
        )
        assert "shopping" in retrieved_session.state["rejected_categories"]
        
        # Verify safeguard: Yakitori (index 3) should have been RESTORED
        assert new_itinerary.days[0].activities[2].activity == "Yakitori"
        # Let's check:
        # Index 1: Sensō-ji (Morning)
        # Index 2: Akihabara (Afternoon)
        # Index 3: Yakitori (Evening)
        # In MOCK_ITINERARY_1, index 3 is Yakitori.
        # In bad_swapped_itinerary, index 3 is Sushi.
        # After enforcement, index 3 should be restored to Yakitori.
        yakitori_act = new_itinerary.days[0].activities[2]
        assert yakitori_act.index == 3
        assert yakitori_act.activity == "Yakitori"
        assert yakitori_act.category == "food"
        
        # Akihabara should be swapped to Gundam Base
        gundam_act = new_itinerary.days[0].activities[1]
        assert gundam_act.index == 2
        assert gundam_act.activity == "Gundam Base"
        
        # Verify it was saved to session state
        assert retrieved_session.state["current_itinerary"] == new_itinerary.model_dump()

@pytest.mark.anyio
async def test_orchestrator_end_session(orchestrator):
    user_id = "user_3"
    session_id = "session_3"
    
    await orchestrator.start_session(user_id, session_id, {
        "explicit_preferences": {"home_city": "Tokyo"}
    })
    session = await orchestrator.runner.session_service.get_session(
        app_name=orchestrator.app_name, user_id=user_id, session_id=session_id
    )
    
    # Simulate some rejections
    update_event = Event(
        id="rejections",
        invocation_id="test",
        partial=False,
        actions=EventActions(state_delta={
            "rejected_categories": ["museum"],
            "explicit_preferences": {"home_city": "Tokyo", "budget_tier": "low"} # update budget during session
        })
    )
    await orchestrator.runner.session_service.append_event(session, update_event)
    
    # End session
    with patch.object(orchestrator.memory_service, 'add_session_to_memory', wraps=orchestrator.memory_service.add_session_to_memory) as mock_add:
        await orchestrator.end_session(user_id, session_id)
        mock_add.assert_called_once()
        
        # Verify that memory DB now contains the profile and decayed weights
        response = await orchestrator.memory_service.search_memory(
            app_name=orchestrator.app_name, user_id=user_id, query="profile"
        )
        assert len(response.memories) == 1
        text = response.memories[0].content.parts[0].text
        assert "Home City: Tokyo" in text
        assert "Budget: low" in text
        assert "museum: 0.50" in text

@pytest.mark.anyio
async def test_orchestrator_regenerate(orchestrator):
    user_id = "user_4"
    session_id = "session_4"
    
    await orchestrator.start_session(user_id, session_id, {})
    session = await orchestrator.runner.session_service.get_session(
        app_name=orchestrator.app_name, user_id=user_id, session_id=session_id
    )
    
    # Set initial itinerary
    init_event = Event(
        id="init-test-state",
        invocation_id="test",
        partial=False,
        actions=EventActions(state_delta={"current_itinerary": MOCK_ITINERARY_1.model_dump()})
    )
    await orchestrator.runner.session_service.append_event(session, init_event)
    
    # Lock index 1 (Sensō-ji)
    await orchestrator.handle_lock(user_id, session_id, 1)
    
    # Mock LLM response for regenerate.
    # Simulates LLM returning a new itinerary where:
    # Day 1, slot Morning: changed to "Meiji Shrine" (violation of lock!)
    # Day 1, slot Afternoon: changed to "Shibuya" (valid change)
    # Day 1, slot Evening: changed to "Ramen" (valid change)
    regenerated_itinerary = Itinerary(
        destination="Tokyo",
        days=[
            DayPlan(
                day=1,
                activities=[
                    Activity(index=1, slot="Morning", activity="Meiji Shrine", category="sightseeing", description="Shrine"), # CHANGED LOCKED ITEM!
                    Activity(index=2, slot="Afternoon", activity="Shibuya", category="shopping", description="Shop Shibuya"),
                    Activity(index=3, slot="Evening", activity="Ramen", category="food", description="Eat Ramen"),
                ]
            )
        ]
    )
    
    mock_json = regenerated_itinerary.model_dump_json()
    with patch.object(orchestrator.runner, 'run', return_value=[make_mock_event(mock_json)]) as mock_run:
        new_itinerary = await orchestrator.handle_regenerate(user_id, session_id, feedback="Add more history")
        assert new_itinerary is not None
        mock_run.assert_called_once()
        
        # Verify prompt contained lock info and feedback
        called_args = mock_run.call_args[1]
        new_msg = called_args["new_message"]
        prompt_text = new_msg.parts[0].text
        assert "LOCKED" in prompt_text
        assert "Sensō-ji" in prompt_text
        assert "Add more history" in prompt_text
        
        # Verify safeguard: Sensō-ji (index 1) should have been RESTORED
        morning_act = new_itinerary.days[0].activities[0]
        assert morning_act.index == 1
        assert morning_act.activity == "Sensō-ji"
        
        # Others should be updated
        shibuya_act = new_itinerary.days[0].activities[1]
        assert shibuya_act.activity == "Shibuya"
        
        # Verify saved to session
        retrieved_session = await orchestrator.runner.session_service.get_session(
            app_name=orchestrator.app_name, user_id=user_id, session_id=session_id
        )
        assert retrieved_session.state["current_itinerary"] == new_itinerary.model_dump()

@pytest.mark.anyio
async def test_orchestrator_errors(orchestrator):
    user_id = "user_err"
    session_id = "session_err"
    
    # Lock/Swap/Regen without session
    msg = await orchestrator.handle_lock(user_id, session_id, 1)
    assert "No active itinerary" in msg
    
    res_swap = await orchestrator.handle_swap(user_id, session_id, 1)
    assert res_swap is None
    
    res_regen = await orchestrator.handle_regenerate(user_id, session_id)
    assert res_regen is None
    
    # Start session but no itinerary
    await orchestrator.start_session(user_id, session_id, {})
    
    msg = await orchestrator.handle_lock(user_id, session_id, 1)
    assert "No active itinerary" in msg

