from typing import Optional
from src.orchestrator import TravelOrchestrator
from src.schemas import Itinerary

async def create_new_session(
    orchestrator: TravelOrchestrator,
    user_id: str,
    session_id: str,
    destination: str,
    duration_days: int,
    vibe: str,
    explicit_prefs: dict
) -> Optional[Itinerary]:
    """Starts a new travel session and generates the initial itinerary."""
    await orchestrator.start_session(user_id, session_id, explicit_prefs)
    itinerary = await orchestrator.generate_initial_itinerary(
        user_id, session_id, destination, duration_days, vibe
    )
    return itinerary
