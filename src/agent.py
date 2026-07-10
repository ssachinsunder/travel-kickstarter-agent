from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.google_llm import Gemini
from google.genai import Client
from typing import Optional
from src.schemas import Itinerary
from src.tools import search_places, get_weather_forecast, estimate_transit_time, book_trip_mock
from src.config import config
from google.adk.apps.app import App
from google.adk.apps._configs import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.events.event import Event
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
import json
import re

# =====================================================================
# Agent Instructions
# =====================================================================

ROUTER_INSTRUCTION = """You are the Travel Router Agent. Your job is to understand the user's intent and delegate the task to the correct specialist agent.

You have access to:
1. `planner_agent`: Specialized in planning and refining travel itineraries.
2. `booking_agent`: Specialized in booking flights and hotels.

Rules:
- If the user wants to plan a new trip, adjust an existing itinerary, swap activities, or regenerate the itinerary, you MUST transfer the conversation to `planner_agent`.
- If the user wants to book the trip (flights/hotels), you MUST transfer the conversation to `booking_agent`.
- For general questions (e.g., greeting, asking what you can do, general travel advice), you should answer them yourself.
- Do not attempt to plan itineraries or book trips yourself. Always delegate.
"""

PLANNER_INSTRUCTION = """You are the Travel Planner Agent. Your goal is to help the user plan a personalized travel itinerary (up to 3 days).

You must generate a structured itinerary matching the requested schema.

To do this:
1.  Analyze the user's request (destination, duration, and vibe/preferences).
2.  Search for places of interest using the `search_places` tool.
3.  Check the weather forecast using the `get_weather_forecast` tool to ensure activities are appropriate (e.g., avoid outdoor activities if it's raining, and warn the user).
4.  (Optional) Estimate transit times between activities using `estimate_transit_time` if they seem far apart.
5.  Construct the itinerary.
6.  Ensure you respect the user's past preferences and profile details which are provided in the system instructions under <PAST_CONVERSATIONS>.
    - Avoid categories with low weights.
    - Prioritize categories with high weights or that match the user's explicit interests.
    - If the user's home city is the same as the destination, adjust recommendations accordingly (e.g., focus on staycation or new spots, don't recommend standard tourist things unless asked).

CRITICAL ERROR HANDLING RULE:
If any tool (e.g., `search_places`, `get_weather_forecast`, `estimate_transit_time`) returns a status other than 'success' (e.g., 'fallback', 'fallback_default') and includes an 'llm_recovery_instruction', you MUST follow that instruction. This typically involves:
- Warning the user in the description of the itinerary activities about the API failure (e.g., prepend "[API Fallback: Live weather data unavailable. Assumed fair weather]" to the activity description).
- Adapting your planning choices as directed by the recovery instruction.
- Transparently documenting the fallback in the activity descriptions.

Your final response MUST be a JSON object matching the `Itinerary` schema. Do not include any conversational text in the final response, only the JSON.
"""

BOOKING_INSTRUCTION = """You are the Booking Agent. Your goal is to book the travel itinerary that has been planned.

You must:
1.  Identify the destination and budget tier from the user's request or the session context.
2.  Use the `book_trip_mock` tool to perform the mock booking.
3.  Provide the booking reference and details to the user.

CRITICAL: Before calling the `book_trip_mock` tool, you MUST ask the user for explicit confirmation (e.g., "Would you like me to proceed with booking this trip to Tokyo with a medium budget?"). Only call the tool if the user confirms.
"""

# =====================================================================
# Validation Guards & Callbacks
# =====================================================================

def _extract_weather_forecast(events: list[Event]) -> Optional[dict]:
    for event in reversed(events):
        for resp in event.get_function_responses():
            if resp.name == "get_weather_forecast":
                return resp.response
    return None

def validate_itinerary(itinerary: Itinerary, events: list[Event]) -> list[str]:
    warnings = []
    
    # 1. Check duplicate slots and indices
    for day_plan in itinerary.days:
        slots = []
        indices = []
        for activity in day_plan.activities:
            if activity.slot:
                slots.append(activity.slot.lower())
            if activity.index:
                indices.append(activity.index)
                
        if len(slots) != len(set(slots)):
            warnings.append(f"Day {day_plan.day} has duplicate slots: {slots}")
            
        if len(indices) != len(set(indices)):
            warnings.append(f"Day {day_plan.day} has duplicate activity indices: {indices}")
            
    # 2. Check weather conflicts
    weather_info = _extract_weather_forecast(events)
    if weather_info and weather_info.get("status") in ("success", "fallback"):
        forecast = weather_info.get("forecast", [])
        weather_map = {f.get("day"): f.get("weather", "").lower() for f in forecast}
        
        for day_plan in itinerary.days:
            day_weather = weather_map.get(day_plan.day)
            if day_weather in ("rain", "storm", "snow"):
                for activity in day_plan.activities:
                    if activity.category.lower() in ("nature", "sightseeing"):
                        warnings.append(
                            f"Weather alert: Outdoor activity '{activity.activity}' (category: {activity.category}) "
                            f"is planned on Day {day_plan.day} but the forecast is {day_weather}."
                        )
    return warnings

def planner_after_model_callback(callback_context: CallbackContext, llm_response: LlmResponse) -> Optional[LlmResponse]:
    if llm_response.get_function_calls():
        return None
        
    text = None
    if llm_response.content and llm_response.content.parts:
        for part in llm_response.content.parts:
            if part.text:
                text = part.text
                break
    if not text:
        return None
        
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    json_text = json_match.group(1) if json_match else text
        
    try:
        itinerary_dict = json.loads(json_text)
        itinerary = Itinerary.model_validate(itinerary_dict)
    except Exception:
        return None
        
    warnings = validate_itinerary(itinerary, callback_context.session.events)
    
    if warnings:
        itinerary.warnings.extend(warnings)
        new_json_text = itinerary.model_dump_json(indent=2)
        for part in llm_response.content.parts:
            if part.text:
                part.text = new_json_text
                break
        return llm_response
        
    return None

# =====================================================================
# Agent Creators
# =====================================================================

def create_router_agent(client: Optional[Client] = None) -> LlmAgent:
    """Creates the Router Agent."""
    if client is not None:
        class InjectedGemini(Gemini):
            @property
            def api_client(self) -> Client:
                return client
        model = InjectedGemini(model=config.model_name)
    else:
        model = config.model_name

    return LlmAgent(
        name="router_agent",
        model=model,
        instruction=ROUTER_INSTRUCTION,
        mode="chat",
    )

def create_planner_agent(client: Optional[Client] = None) -> LlmAgent:
    """Creates the Planner Agent using the Pro model."""
    if client is not None:
        class InjectedGemini(Gemini):
            @property
            def api_client(self) -> Client:
                return client
        model = InjectedGemini(model=config.pro_model_name)
    else:
        model = config.pro_model_name

    return LlmAgent(
        name="planner_agent",
        model=model,
        instruction=PLANNER_INSTRUCTION,
        tools=[search_places, get_weather_forecast, estimate_transit_time],
        output_schema=Itinerary,
        mode="chat",
        after_model_callback=planner_after_model_callback,
    )

def create_booking_agent(client: Optional[Client] = None) -> LlmAgent:
    """Creates the Booking Agent."""
    if client is not None:
        class InjectedGemini(Gemini):
            @property
            def api_client(self) -> Client:
                return client
        model = InjectedGemini(model=config.model_name)
    else:
        model = config.model_name

    return LlmAgent(
        name="booking_agent",
        model=model,
        instruction=BOOKING_INSTRUCTION,
        tools=[book_trip_mock],
        mode="chat",
    )

# Legacy creator for backward compatibility in tests
def create_travel_agent(client: Optional[Client] = None) -> LlmAgent:
    """Legacy creator returning the Planner Agent directly (since it has the schema)."""
    return create_planner_agent(client)

# =====================================================================
# App Creator
# =====================================================================

def create_travel_app(client: Optional[Client] = None) -> App:
    """Creates the Travel App with multi-agent orchestration and event compaction."""
    router = create_router_agent(client)
    planner = create_planner_agent(client)
    booking = create_booking_agent(client)
    
    # Connect them
    router.sub_agents = [planner, booking]
    
    # Setup compaction
    if client is not None:
        class InjectedGemini(Gemini):
            @property
            def api_client(self) -> Client:
                return client
        llm = InjectedGemini(model=config.model_name)
    else:
        llm = Gemini(model=config.model_name)
        
    summarizer = LlmEventSummarizer(llm=llm)
    compaction_config = EventsCompactionConfig(
        summarizer=summarizer,
        compaction_interval=3,
        overlap_size=1,
    )
    
    return App(
        name="travel_app",
        root_agent=router,
        events_compaction_config=compaction_config
    )
