from pydantic import BaseModel, Field
from typing import List

class Activity(BaseModel):
    index: int = Field(description="Unique index of the activity in the itinerary (1-indexed).")
    slot: str = Field(description="Time slot of the activity (e.g., 'Morning', 'Afternoon', 'Evening').")
    activity: str = Field(description="Name or brief title of the activity.")
    category: str = Field(description="Category of the activity (e.g., 'sightseeing', 'shopping', 'food', 'nature', 'relaxation').")
    description: str = Field(description="Detailed description of what to do.")

class DayPlan(BaseModel):
    day: int = Field(description="Day number (1, 2, 3...).")
    activities: List[Activity] = Field(description="List of activities planned for this day.")

class Itinerary(BaseModel):
    destination: str = Field(description="The destination of the trip.")
    days: List[DayPlan] = Field(description="Day-by-day plan.")
