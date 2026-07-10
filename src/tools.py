import math
import os
import logging

logger = logging.getLogger(__name__)

# Mock coordinates for distance estimation (needed for straight-line math)
CITY_COORDINATES = {
    "tokyo": (35.6762, 139.6503),
    "kyoto": (35.0116, 135.7681),
    "osaka": (34.6937, 135.5022),
    "san francisco": (37.7749, -122.4194),
    "los angeles": (34.0522, -118.2437),
}

def haversine_distance(coord1, coord2):
    """Calculate the great circle distance between two points on the earth in km."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371.0 # Earth radius in km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def search_places(query: str, location: str) -> dict:
    """Searches for points of interest or hotels in a location.

    Args:
        query: What to search for (e.g., 'hotels', 'restaurants', 'museums').
        location: The city or destination to search within.

    Returns:
        dict: A dictionary containing status and list of places.
    """
    # Check for simulated failure
    if os.getenv("MOCK_PLACES_API_FAIL") == "1":
        logger.warning("Places API failure simulated. Falling back to template items.")
        print("⚠️ Places API unavailable. Using default recommendations.")
        return {
            "status": "fallback",
            "llm_recovery_instruction": "The Places API is currently unavailable. Use these default recommendations, but warn the user that live search failed and suggest they try again later if they want specific spots.",
            "places": [
                {"name": f"Local Park in {location}", "category": "nature", "description": "A beautiful public park."},
                {"name": f"Central Street in {location}", "category": "shopping", "description": "Main street with local shops."}
            ]
        }

    # Mock successful response
    location_lower = location.lower()
    query_lower = query.lower()
    
    places = []
    if "hotel" in query_lower:
        places = [
            {"name": f"Grand Plaza Hotel {location}", "category": "hotel", "description": "Luxury hotel in city center."},
            {"name": f"Cozy Stay Hostel {location}", "category": "hotel", "description": "Budget friendly hostel."}
        ]
    elif "museum" in query_lower or "art" in query_lower:
        places = [
            {"name": f"National Museum of {location}", "category": "museum", "description": "Historical artifacts and exhibits."},
            {"name": f"Modern Art Gallery {location}", "category": "museum", "description": "Contemporary art collections."}
        ]
    else:
        places = [
            {"name": f"Famous Landmark in {location}", "category": "sightseeing", "description": "Must-see attraction."},
            {"name": f"Popular Cafe in {location}", "category": "food", "description": "Great coffee and local snacks."}
        ]
        
    return {
        "status": "success",
        "places": places
    }

def get_weather_forecast(location: str, days: int = 3) -> dict:
    """Retrieves the weather forecast for a location.

    Args:
        location: The city or destination.
        days: Number of days for the forecast (default 3).

    Returns:
        dict: Forecast details.
    """
    if os.getenv("MOCK_WEATHER_API_FAIL") == "1":
        logger.warning("Weather API failure simulated. Assuming fair weather.")
        print("⚠️ Weather API unavailable. Assuming fair weather.")
        return {
            "status": "fallback",
            "llm_recovery_instruction": "Weather API is unavailable. Assuming fair weather (22C, Fair) for all days. Inform the user about this assumption and advise them to check actual weather before traveling.",
            "forecast": [{"day": i+1, "weather": "Fair", "temp": "22C"} for i in range(days)]
        }

    # Mock success
    # Simple deterministic forecast based on name length to make it testable
    hash_val = len(location)
    weathers = ["Sunny", "Cloudy", "Rainy", "Windy"]
    
    forecast = []
    for i in range(days):
        weather = weathers[(hash_val + i) % len(weathers)]
        temp = 15 + (hash_val * 2 + i * 3) % 15
        forecast.append({
            "day": i + 1,
            "weather": weather,
            "temp": f"{temp}C"
        })
        
    return {
        "status": "success",
        "forecast": forecast
    }

def estimate_transit_time(origin: str, destination: str, mode: str = "driving") -> dict:
    """Estimates travel time and distance between two locations using straight-line math.

    Args:
        origin: Starting point (city name or place).
        destination: Ending point (city name or place).
        mode: Transit mode ('driving', 'walking', 'transit').

    Returns:
        dict: Distance, estimated time, and status.
    """
    origin_lower = origin.lower()
    dest_lower = destination.lower()
    
    coord1 = CITY_COORDINATES.get(origin_lower)
    coord2 = CITY_COORDINATES.get(dest_lower)
    
    if not coord1 or not coord2:
        # Fallback if coordinates are not known
        logger.warning(f"Unknown coordinates for {origin} or {destination}. Using default estimate.")
        print(f"⚠️ Distance estimation fallback for {origin} to {destination}.")
        distance_km = 15.0 # Default 15km
        status = "fallback_default"
    else:
        distance_km = haversine_distance(coord1, coord2)
        status = "success"
        
    # Speed assumptions (km/h)
    speeds = {
        "driving": 30.0, # Average city speed as per PRD
        "walking": 5.0,
        "transit": 20.0
    }
    speed = speeds.get(mode, 30.0)
    
    duration_hours = distance_km / speed
    duration_minutes = int(duration_hours * 60)
    
    result = {
        "status": status,
        "distance_km": round(distance_km, 2),
        "duration_minutes": duration_minutes,
        "mode": mode
    }
    if status == "fallback_default":
        result["llm_recovery_instruction"] = "Could not estimate exact transit time due to unknown coordinates. Using a default estimate of 15km / 30 minutes. Warn the user that this is a rough estimate."
    return result

def book_trip_mock(destination: str, check_in: str, check_out: str, budget: str) -> dict:
    """Simulates booking flights and hotels (mock tool).

    Args:
        destination: The destination city.
        check_in: Check-in date.
        check_out: Check-out date.
        budget: Budget tier ('low', 'medium', 'high').

    Returns:
        dict: Booking confirmation details.
    """
    logger.info(f"Simulating booking for {destination} from {check_in} to {check_out} with budget {budget}")
    
    # Simple mock confirmation
    # We use a static number for testability instead of random
    conf_id = f"KICK-12345"
    
    hotel_names = {
        "low": "Budget Inn",
        "medium": "Comfort Suites",
        "high": "The Ritz Luxury"
    }
    hotel = hotel_names.get(budget.lower(), "Standard Hotel")
    
    return {
        "status": "success",
        "booking_reference": conf_id,
        "flight": {
            "carrier": "Mock Airways",
            "price_usd": 150 if budget == "low" else 300 if budget == "medium" else 600
        },
        "hotel": {
            "name": f"{hotel} {destination}",
            "price_per_night_usd": 50 if budget == "low" else 120 if budget == "medium" else 300
        }
    }
