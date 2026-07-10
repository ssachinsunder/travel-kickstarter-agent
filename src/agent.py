from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.google_llm import Gemini
from google.genai import Client
from typing import Optional
from src.schemas import Itinerary
from src.tools import search_places, get_weather_forecast, estimate_transit_time, book_trip_mock
from src.config import config

# Define the instruction for the agent
INSTRUCTION = """You are a Travel Activation Agent. Your goal is to help the user plan a personalized travel itinerary (up to 3 days).

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

Your final response MUST be a JSON object matching the `Itinerary` schema. Do not include any conversational text in the final response, only the JSON.
"""

def create_travel_agent(client: Optional[Client] = None) -> LlmAgent:
    """Creates the Travel Agent, optionally injecting a custom Gemini Client."""
    if client is not None:
        class InjectedGemini(Gemini):
            @property
            def api_client(self) -> Client:
                return client
        
        model = InjectedGemini(model=config.model_name)
    else:
        model = config.model_name

    return LlmAgent(
        name="travel_agent",
        model=model,
        instruction=INSTRUCTION,
        tools=[search_places, get_weather_forecast, estimate_transit_time, book_trip_mock],
        output_schema=Itinerary,
    )
