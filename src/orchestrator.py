import json
import logging
from typing import Optional, List, Tuple
from google.genai import types
from google.adk.runners import Runner
from google.adk.sessions.session import Session
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from src.schemas import Itinerary, Activity
from src.memory_service import SQLiteMemoryService

logger = logging.getLogger(__name__)

class TravelOrchestrator:
    """Orchestrates the travel planning flow, managing session state and commands."""
    
    def __init__(self, runner: Runner, memory_service: SQLiteMemoryService):
        self.runner = runner
        self.memory_service = memory_service
        self.app_name = runner.app_name

    async def start_session(self, user_id: str, session_id: str, explicit_prefs: dict) -> Session:
        """Starts a new travel session, initializing state with user preferences."""
        initial_state = {
            "explicit_preferences": explicit_prefs,
            "locked_indices": [],
            "rejected_categories": [],
            "current_itinerary": None
        }
        logger.info(f"Starting session {session_id} for user {user_id} with prefs: {explicit_prefs}")
        session = await self.runner.session_service.create_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=session_id,
            state=initial_state
        )
        return session

    async def session_exists(self, user_id: str, session_id: str) -> bool:
        """Checks if a session exists."""
        sessions = await self.runner.session_service.list_sessions(app_name=self.app_name, user_id=user_id)
        return any(s.id == session_id for s in sessions.sessions)

    async def delete_session(self, user_id: str, session_id: str):
        """Deletes a session."""
        await self.runner.session_service.delete_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )

    async def get_current_itinerary(self, user_id: str, session_id: str) -> Optional[Itinerary]:
        """Gets the current itinerary for the session."""
        session = await self.runner.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if session and session.state.get("current_itinerary"):
            return Itinerary.model_validate(session.state["current_itinerary"])
        return None

    async def get_locked_indices(self, user_id: str, session_id: str) -> List[int]:
        """Gets the locked indices for the session."""
        session = await self.runner.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if session:
            return session.state.get("locked_indices", [])
        return []


    def _extract_itinerary_from_events(self, events) -> Optional[Itinerary]:
        """Extracts and parses the structured Itinerary from runner events."""
        text_parts = []
        for event in events:
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        text_parts.append(part.text)
        response_text = "".join(text_parts).strip()
        if not response_text:
            logger.warning("Empty response from agent.")
            return None
        try:
            if response_text.startswith("```json"):
                response_text = response_text.split("```json", 1)[1]
                response_text = response_text.rsplit("```", 1)[0]
            elif response_text.startswith("```"):
                response_text = response_text.split("```", 1)[1]
                response_text = response_text.rsplit("```", 1)[0]
                
            return Itinerary.model_validate_json(response_text.strip())
        except Exception as e:
            logger.error(f"Failed to parse itinerary: {e}. Raw response:\n{response_text}")
            return None

    async def _update_session_state(self, session: Session, state_delta: dict, event_id: str):
        """Helper to append a state-updating event to the session."""
        update_event = Event(
            id=event_id,
            invocation_id="orch-flow",
            partial=False,
            actions=EventActions(state_delta=state_delta)
        )
        await self.runner.session_service.append_event(session, update_event)

    def _find_activity_by_index(self, itinerary: Itinerary, index: int) -> Optional[Tuple[Activity, int]]:
        """Helper to find an activity by index and return it along with its day number."""
        for day in itinerary.days:
            for act in day.activities:
                if act.index == index:
                    return act, day.day
        return None

    def _get_locked_activities(self, itinerary: Itinerary, locked_indices: List[int]) -> List[dict]:
        """Helper to collect activities that are currently locked."""
        locked_activities = []
        for day in itinerary.days:
            for act in day.activities:
                if act.index in locked_indices:
                    locked_activities.append(act.model_dump())
        return locked_activities

    async def generate_initial_itinerary(
        self, user_id: str, session_id: str, destination: str, duration_days: int, vibe: str
    ) -> Optional[Itinerary]:
        """Generates the initial travel itinerary."""
        prompt = f"Plan a {duration_days}-day trip to {destination}. Vibe/Preferences: {vibe}."
        logger.info(f"Generating initial itinerary for {destination} ({duration_days} days, vibe: {vibe})")
        
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)]
        )
        
        events = list(self.runner.run(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message
        ))
        
        itinerary = self._extract_itinerary_from_events(events)
        if itinerary:
            session = await self.runner.session_service.get_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )
            await self._update_session_state(
                session, 
                {"current_itinerary": itinerary.model_dump()}, 
                f"init-itinerary-{session_id}"
            )
            logger.info("Initial itinerary generated and persisted.")
        return itinerary

    async def handle_lock(self, user_id: str, session_id: str, index: int) -> str:
        """Locks an activity by index, preventing it from being changed."""
        session = await self.runner.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if not session or not session.state.get("current_itinerary"):
            return "No active itinerary to lock activities from."
            
        itinerary = Itinerary.model_validate(session.state["current_itinerary"])
        activity_info = self._find_activity_by_index(itinerary, index)
        if not activity_info:
            return f"Activity index {index} not found."
            
        target_act, _ = activity_info
        locked = session.state.get("locked_indices", [])
        if index in locked:
            return f"Activity {index} ({target_act.activity}) is already locked."
            
        locked.append(index)
        await self._update_session_state(session, {"locked_indices": locked}, f"lock-{index}")
        logger.info(f"Locked activity {index} ({target_act.activity}) in session {session_id}")
        return f"Locked activity {index}: {target_act.activity}."

    async def handle_swap(self, user_id: str, session_id: str, index: int) -> Optional[Itinerary]:
        """Swaps an activity, recording the rejection and preserving locked items."""
        session = await self.runner.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if not session or not session.state.get("current_itinerary"):
            logger.error("No active itinerary for swap.")
            return None
            
        itinerary = Itinerary.model_validate(session.state["current_itinerary"])
        activity_info = self._find_activity_by_index(itinerary, index)
        if not activity_info:
            logger.error(f"Activity index {index} not found for swap.")
            return None
            
        target_act, target_day = activity_info
        
        # 1. Record rejection
        rejected = session.state.get("rejected_categories", [])
        rejected.append(target_act.category)
        
        # 2. Gather locked activities to instruct the agent
        locked_indices = session.state.get("locked_indices", [])
        locked_activities = self._get_locked_activities(itinerary, locked_indices)

        logger.info(f"Swapping activity {index} ({target_act.activity}, category: {target_act.category}) on day {target_day}")
        logger.info(f"Locked activities to preserve: {locked_indices}")

        prompt = f"""The user wants to swap activity index {index}: '{target_act.activity}' (category: '{target_act.category}') on Day {target_day}.
Please suggest an alternative activity of the SAME category '{target_act.category}' for this slot.

CRITICAL REQUIREMENTS:
1. Preserve all other activities.
2. Specifically, the following activities are LOCKED and MUST NOT be changed:
{json.dumps(locked_activities, indent=2, ensure_ascii=False)}
3. Do not recommend '{target_act.activity}' again.
"""
        
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)]
        )
        
        # Update session state with rejections before running
        await self._update_session_state(session, {"rejected_categories": rejected}, f"swap-init-{index}")
        
        events = list(self.runner.run(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message
        ))
        
        new_itinerary = self._extract_itinerary_from_events(events)
        if new_itinerary:
            self._enforce_locks(itinerary, new_itinerary, locked_indices)
            
            # Persist new itinerary
            session = await self.runner.session_service.get_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )
            await self._update_session_state(
                session, 
                {"current_itinerary": new_itinerary.model_dump()}, 
                f"swap-confirm-{index}"
            )
            logger.info("Swap completed and new itinerary persisted.")
            return new_itinerary
            
        return None

    def _enforce_locks(self, old_itinerary: Itinerary, new_itinerary: Itinerary, locked_indices: List[int]):
        """Helper to overwrite regenerated slots with locked ones from the old itinerary."""
        locked_map = {}
        for day in old_itinerary.days:
            for act in day.activities:
                if act.index in locked_indices:
                    locked_map[act.index] = act

        for day in new_itinerary.days:
            for i, act in enumerate(day.activities):
                if act.index in locked_map:
                    day.activities[i] = locked_map[act.index]

    async def handle_regenerate(self, user_id: str, session_id: str, feedback: Optional[str] = None) -> Optional[Itinerary]:
        """Regenerates the itinerary, preserving locked items and incorporating feedback."""
        session = await self.runner.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if not session or not session.state.get("current_itinerary"):
            logger.error("No active itinerary to regenerate.")
            return None
            
        itinerary = Itinerary.model_validate(session.state["current_itinerary"])
        locked_indices = session.state.get("locked_indices", [])
        locked_activities = self._get_locked_activities(itinerary, locked_indices)

        logger.info(f"Regenerating itinerary for {itinerary.destination}, preserving locks: {locked_indices}, feedback: {feedback}")

        prompt = f"""Please regenerate the itinerary for {itinerary.destination}.
Preserve the general flow but try to suggest different activities where possible.
"""
        if feedback:
            prompt += f"\nUser feedback to incorporate: {feedback}\n"
            
        prompt += f"""
CRITICAL REQUIREMENTS:
1. The following activities are LOCKED and MUST NOT be changed:
{json.dumps(locked_activities, indent=2, ensure_ascii=False)}
"""
        
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)]
        )
        
        events = list(self.runner.run(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message
        ))
        
        new_itinerary = self._extract_itinerary_from_events(events)
        if new_itinerary:
            self._enforce_locks(itinerary, new_itinerary, locked_indices)
            session = await self.runner.session_service.get_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )
            await self._update_session_state(
                session, 
                {"current_itinerary": new_itinerary.model_dump()}, 
                "regenerate-confirm"
            )
            logger.info("Regeneration completed and persisted.")
            return new_itinerary
            
        return None

    async def end_session(self, user_id: str, session_id: str):
        """Ends the session and updates long-term memory with accumulated preferences."""
        session = await self.runner.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if session:
            logger.info(f"Ending session {session_id}. Saving to long-term memory.")
            await self.memory_service.add_session_to_memory(session)
