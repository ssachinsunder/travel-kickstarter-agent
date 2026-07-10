import asyncio
import argparse
import os
import sys
import logging
import questionary
from typing import Optional

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.adk.runners import Runner
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from src.memory_service import SQLiteMemoryService
from src.orchestrator import TravelOrchestrator
from src.agent import create_travel_agent
from src.schemas import Itinerary

# Configure logging
logging.basicConfig(
    level=logging.WARNING, # Set to WARNING to keep CLI clean, change to INFO for debugging
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_PATH = "travel_agent.db"
USER_ID = "default_user"
SESSION_ID = "travel_session"

def print_itinerary(itinerary: Itinerary, locked_indices: list[int]):
    print(f"\n==================================================")
    print(f"   🗺️  Trip Itinerary: {itinerary.destination}")
    print(f"==================================================")
    for day in itinerary.days:
        print(f"\n📅 Day {day.day}:")
        print(f"--------------------------------------------------")
        for act in day.activities:
            lock_char = "🔒" if act.index in locked_indices else "  "
            print(f"[{act.index}] {lock_char} {act.slot} ({act.category}): {act.activity}")
            print(f"     {act.description}")
            print(f"--------------------------------------------------")
    print(f"==================================================")

async def refresh_and_display(orchestrator: TravelOrchestrator, itinerary: Itinerary) -> Itinerary:
    """Refreshes the session state from DB and prints the updated itinerary.
    
    Avoids repetitive session reading and display logic.
    """
    session = await orchestrator.runner.session_service.get_session(
        app_name=orchestrator.app_name, user_id=USER_ID, session_id=SESSION_ID
    )
    locked_indices = session.state.get("locked_indices", [])
    current_itinerary_dict = session.state.get("current_itinerary")
    if current_itinerary_dict:
        itinerary = Itinerary.model_validate(current_itinerary_dict)
    print_itinerary(itinerary, locked_indices)
    return itinerary

async def main(trace: bool = False, debug: bool = False):
    if debug:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("google_adk").setLevel(logging.INFO)
        
    if trace:
        from src.telemetry import setup_telemetry
        setup_telemetry(DB_PATH)
        print("🔍 Telemetry enabled. Traces will be saved to SQLite.")

    # Ensure API Key is available
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("\n❌ Error: GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not set.")
        print("Please set it in your .env file or environment.")
        return
        
    # Set env vars for ADK
    os.environ["GEMINI_API_KEY"] = api_key
    os.environ["GOOGLE_API_KEY"] = api_key
    
    # Initialize Services
    session_service = SqliteSessionService(DB_PATH)
    memory_service = SQLiteMemoryService(DB_PATH)
    
    agent = create_travel_agent()
    runner = Runner(
        app_name="travel_app",
        agent=agent,
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=memory_service,
    )
    
    orchestrator = TravelOrchestrator(runner, memory_service)

    print("👋 Welcome to the Travel Activation Agent!")
    
    # Check for existing session
    existing_sessions = await session_service.list_sessions(app_name="travel_app", user_id=USER_ID)
    resume = False
    session = None
    
    if existing_sessions.sessions:
        has_default_session = any(s.id == SESSION_ID for s in existing_sessions.sessions)
        if has_default_session:
            resume = await questionary.confirm(
                "Found an unfinished travel planning session. Do you want to resume?",
                default=True
            ).ask_async()
            
            if resume:
                session = await session_service.get_session(
                    app_name="travel_app", user_id=USER_ID, session_id=SESSION_ID
                )
                if session and session.state.get("current_itinerary"):
                    itinerary = Itinerary.model_validate(session.state["current_itinerary"])
                    print("\n📋 Resuming your previous session...")
                    itinerary = await refresh_and_display(orchestrator, itinerary)
                else:
                    print("\n⚠️ Previous session was empty. Starting a new one.")
                    resume = False
            else:
                await session_service.delete_session(
                    app_name="travel_app", user_id=USER_ID, session_id=SESSION_ID
                )

    if not resume:
        print("Let's plan your next trip. I need a few details first.\n")
        
        # 1. Vibe Check (Gather preferences)
        destination = await questionary.text(
            "Where do you want to go?",
            default="Tokyo"
        ).ask_async()
        if not destination:
            print("Destination is required. Exiting.")
            return
            
        duration_str = await questionary.select(
            "How many days?",
            choices=["1", "2", "3"],
            default="3"
        ).ask_async()
        duration_days = int(duration_str)
        
        vibe = await questionary.text(
            "What is the vibe of the trip? (e.g., adventure, history, food, relaxation, nature)",
            default="culture and food"
        ).ask_async()
        
        home_city = await questionary.text(
            "What is your home city? (for personalization)",
            default="San Francisco"
        ).ask_async()
        
        budget = await questionary.select(
            "What is your budget tier?",
            choices=["low", "medium", "high"],
            default="medium"
        ).ask_async()
        
        diet = await questionary.text(
            "Do you have any dietary restrictions?",
            default="none"
        ).ask_async()
        
        explicit_prefs = {
            "home_city": home_city,
            "budget_tier": budget,
            "dietary_restrictions": diet
        }
        
        # Start Session
        await orchestrator.start_session(USER_ID, SESSION_ID, explicit_prefs)
        
        # Generate Initial Itinerary
        print("\n🧠 Generating your custom itinerary... (this may take a few seconds)")
        itinerary = await orchestrator.generate_initial_itinerary(
            USER_ID, SESSION_ID, destination, duration_days, vibe
        )
        
        if not itinerary:
            print("❌ Failed to generate itinerary. Please try again.")
            return
            
        itinerary = await refresh_and_display(orchestrator, itinerary)
    
    # 4. Command Loop
    while True:
        print("\nAvailable Commands:")
        print("  /lock [index]       - Pin an activity so it doesn't change")
        print("  /swap [index]       - Replace activity with another of the same category")
        print("  /regenerate [feed]  - Regenerate itinerary, preserving locks (optional feedback)")
        print("  /done               - Finalize trip, save preferences, and exit")
        
        cmd_input = input("\nEnter command: ").strip()
        if not cmd_input:
            continue
            
        if cmd_input == "/done":
            print("\nFinalizing your session...")
            await orchestrator.end_session(USER_ID, SESSION_ID)
            print("💾 Preferences saved. Enjoy your trip! ✈️")
            break
            
        elif cmd_input.startswith("/lock"):
            parts = cmd_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /lock [index]")
                continue
            try:
                index = int(parts[1])
                msg = await orchestrator.handle_lock(USER_ID, SESSION_ID, index)
                print(f"\n{msg}")
                itinerary = await refresh_and_display(orchestrator, itinerary)
            except ValueError:
                print("Index must be an integer.")
                
        elif cmd_input.startswith("/swap"):
            parts = cmd_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /swap [index]")
                continue
            try:
                index = int(parts[1])
                print(f"🔄 Swapping activity {index}... (calling LLM)")
                new_itinerary = await orchestrator.handle_swap(USER_ID, SESSION_ID, index)
                if new_itinerary:
                    itinerary = new_itinerary
                    print("✅ Swapped!")
                else:
                    print("❌ Swap failed.")
                itinerary = await refresh_and_display(orchestrator, itinerary)
            except ValueError:
                print("Index must be an integer.")
                
        elif cmd_input.startswith("/regenerate"):
            parts = cmd_input.split(maxsplit=1)
            feedback = parts[1] if len(parts) > 1 else None
            
            print("🔄 Regenerating itinerary... (calling LLM)")
            new_itinerary = await orchestrator.handle_regenerate(USER_ID, SESSION_ID, feedback)
            if new_itinerary:
                itinerary = new_itinerary
                print("✅ Regenerated!")
            else:
                print("❌ Regeneration failed.")
            itinerary = await refresh_and_display(orchestrator, itinerary)
            
        else:
            print("Unknown command. Please use /lock, /swap, /regenerate, or /done.")

def run_cli():
    parser = argparse.ArgumentParser(description="Travel Activation Agent CLI")
    parser.add_argument("--trace", action="store_true", help="Enable local telemetry tracing to SQLite")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    try:
        asyncio.run(main(trace=args.trace, debug=args.debug))
    except KeyboardInterrupt:
        print("\nExiting. Goodbye!")

if __name__ == "__main__":
    run_cli()
