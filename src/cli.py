import asyncio
import argparse
import os
import random
import sys
import logging
import questionary
from src.logger_config import setup_logging
from dotenv import load_dotenv
from typing import Optional

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.adk.runners import Runner
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from src.memory_service import SQLiteMemoryService
from src.orchestrator import TravelOrchestrator
from src.agent import create_travel_app
from src.schemas import Itinerary
from src.session import create_new_session

# Configure logging
setup_logging(level=logging.WARNING)
logger = logging.getLogger(__name__)

DB_PATH = "travel_agent.db"
USER_ID = "default_user"
SESSION_ID = "travel_session"

# Default Preferences Configuration
DESTINATION_DEFAULTS = ["Tokyo", "Paris", "New York"]
DURATION_CHOICES = ["1", "2", "3"]
DEFAULT_DURATION = "3"
DEFAULT_VIBE = "culture and food"
HOME_CITY_DEFAULTS = ["San Francisco", "London", "Sydney"]
BUDGET_CHOICES = ["low", "medium", "high"]
DEFAULT_BUDGET = "medium"
DEFAULT_DIET = "none"

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

async def refresh_and_display(orchestrator: TravelOrchestrator, itinerary: Itinerary, user_id: str, session_id: str) -> Itinerary:
    """Refreshes the session state from DB and prints the updated itinerary.
    
    Avoids repetitive session reading and display logic.
    """
    locked_indices = await orchestrator.get_locked_indices(user_id, session_id)
    current_itinerary = await orchestrator.get_current_itinerary(user_id, session_id)
    if current_itinerary:
        itinerary = current_itinerary
    print_itinerary(itinerary, locked_indices)
    return itinerary

def _setup_env(debug: bool, trace: bool) -> bool:
    load_dotenv()
    
    if debug:
        setup_logging(level=logging.INFO)
        logging.getLogger("google_adk").setLevel(logging.INFO)
        
    if trace:
        from src.telemetry import setup_telemetry
        setup_telemetry(DB_PATH)
        print("🔍 Telemetry enabled. Traces will be saved to SQLite.")

    # Try Secret Manager
    from src.secret_manager import get_secret
    api_key = get_secret("gemini-api-key")
    
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        
    if not api_key:
        print("\n❌ Error: API Key not found in Secret Manager or env (GEMINI_API_KEY/GOOGLE_API_KEY).")
        return False
        
    # Set env vars for ADK
    os.environ["GEMINI_API_KEY"] = api_key
    os.environ["GOOGLE_API_KEY"] = api_key
    return True

def _init_orchestrator(db_path: str) -> TravelOrchestrator:
    session_service = SqliteSessionService(db_path)
    memory_service = SQLiteMemoryService(db_path)
    
    app = create_travel_app()
    runner = Runner(
        app=app,
        artifact_service=InMemoryArtifactService(),
        session_service=session_service,
        memory_service=memory_service,
    )
    
    return TravelOrchestrator(runner, memory_service)

async def _gather_user_preferences() -> Optional[tuple[str, int, str, dict]]:
    print("Let's plan your next trip. I need a few details first.\n")
    
    default_dest = random.choice(DESTINATION_DEFAULTS)
    destination = await questionary.text(
        "Where do you want to go?",
        default=default_dest
    ).ask_async()
    if not destination:
        print("Destination is required. Exiting.")
        return None
        
    duration_str = await questionary.select(
        "How many days?",
        choices=DURATION_CHOICES,
        default=DEFAULT_DURATION
    ).ask_async()
    duration_days = int(duration_str)
    
    vibe = await questionary.text(
        "What is the vibe of the trip? (e.g., adventure, history, food, relaxation, nature)",
        default=DEFAULT_VIBE
    ).ask_async()
    
    default_home = random.choice(HOME_CITY_DEFAULTS)
    home_city = await questionary.text(
        "What is your home city? (for personalization)",
        default=default_home
    ).ask_async()
    
    budget = await questionary.select(
        "What is your budget tier?",
        choices=BUDGET_CHOICES,
        default=DEFAULT_BUDGET
    ).ask_async()
    
    diet = await questionary.text(
        "Do you have any dietary restrictions?",
        default=DEFAULT_DIET
    ).ask_async()
    
    explicit_prefs = {
        "home_city": home_city,
        "budget_tier": budget,
        "dietary_restrictions": diet
    }
    
    return destination, duration_days, vibe, explicit_prefs

async def _setup_session(orchestrator: TravelOrchestrator, user_id: str, session_id: str) -> Optional[Itinerary]:
    has_default_session = await orchestrator.session_exists(user_id, session_id)
    resume = False
    
    if has_default_session:
        resume = await questionary.confirm(
            "Found an unfinished travel planning session. Do you want to resume?",
            default=True
        ).ask_async()
        
        if resume:
            itinerary = await orchestrator.get_current_itinerary(user_id, session_id)
            if itinerary:
                print("\n📋 Resuming your previous session...")
                return await refresh_and_display(orchestrator, itinerary, user_id, session_id)
            else:
                print("\n⚠️ Previous session was empty. Starting a new one.")
                await orchestrator.delete_session(user_id, session_id)
                resume = False
        else:
            await orchestrator.delete_session(user_id, session_id)

    if not resume:
        prefs = await _gather_user_preferences()
        if not prefs:
            return None
        destination, duration_days, vibe, explicit_prefs = prefs
        
        print("\n🧠 Generating your custom itinerary... (this may take a few seconds)")
        itinerary = await create_new_session(
            orchestrator, user_id, session_id, destination, duration_days, vibe, explicit_prefs
        )
        if not itinerary:
            print("❌ Failed to generate itinerary. Please try again.")
            return None
        return await refresh_and_display(orchestrator, itinerary, user_id, session_id)
    
    return None

def _parse_command(user_input: str) -> tuple[str, str]:
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args

def _parse_index_arg(args_str: str) -> Optional[int]:
    try:
        return int(args_str)
    except ValueError:
        print("Index must be an integer.")
        return None

async def _handle_done(orchestrator: TravelOrchestrator, user_id: str, session_id: str, itinerary: Itinerary, args: str) -> tuple[Optional[Itinerary], bool]:
    print("\nFinalizing your session...")
    await orchestrator.end_session(user_id, session_id)
    await orchestrator.wait_for_pending_tasks()
    print("💾 Preferences saved. Enjoy your trip! ✈️")
    return itinerary, True

async def _handle_lock(orchestrator: TravelOrchestrator, user_id: str, session_id: str, itinerary: Itinerary, args: str) -> tuple[Optional[Itinerary], bool]:
    if not args:
        print("Usage: /lock [index]")
        return itinerary, False
    index = _parse_index_arg(args)
    if index is None:
        return itinerary, False
    
    msg = await orchestrator.handle_lock(user_id, session_id, index)
    print(f"\n{msg}")
    itinerary = await refresh_and_display(orchestrator, itinerary, user_id, session_id)
    return itinerary, False

async def _handle_swap(orchestrator: TravelOrchestrator, user_id: str, session_id: str, itinerary: Itinerary, args: str) -> tuple[Optional[Itinerary], bool]:
    if not args:
        print("Usage: /swap [index]")
        return itinerary, False
    index = _parse_index_arg(args)
    if index is None:
        return itinerary, False
        
    print(f"🔄 Swapping activity {index}... (calling LLM)")
    new_itinerary = await orchestrator.handle_swap(user_id, session_id, index)
    if new_itinerary:
        itinerary = new_itinerary
        print("✅ Swapped!")
    else:
        print("❌ Swap failed.")
    itinerary = await refresh_and_display(orchestrator, itinerary, user_id, session_id)
    return itinerary, False

async def _handle_regenerate(orchestrator: TravelOrchestrator, user_id: str, session_id: str, itinerary: Itinerary, args: str) -> tuple[Optional[Itinerary], bool]:
    feedback = args if args else None
    print("🔄 Regenerating itinerary... (calling LLM)")
    new_itinerary = await orchestrator.handle_regenerate(user_id, session_id, feedback)
    if new_itinerary:
        itinerary = new_itinerary
        print("✅ Regenerated!")
    else:
        print("❌ Regeneration failed.")
    itinerary = await refresh_and_display(orchestrator, itinerary, user_id, session_id)
    return itinerary, False

async def _command_loop(orchestrator: TravelOrchestrator, itinerary: Itinerary, user_id: str, session_id: str):
    COMMAND_HANDLERS = {
        "/done": _handle_done,
        "/lock": _handle_lock,
        "/swap": _handle_swap,
        "/regenerate": _handle_regenerate,
    }

    while True:
        print("\nAvailable Commands:")
        print("  /lock [index]       - Pin an activity so it doesn't change")
        print("  /swap [index]       - Replace activity with another of the same category")
        print("  /regenerate [feed]  - Regenerate itinerary, preserving locks (optional feedback)")
        print("  /done               - Finalize trip, save preferences, and exit")
        
        try:
            cmd_input = await asyncio.to_thread(input, "\nEnter command: ")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
            
        cmd_input = cmd_input.strip()
        if not cmd_input:
            continue
            
        cmd, args = _parse_command(cmd_input)
        
        if cmd in COMMAND_HANDLERS:
            handler = COMMAND_HANDLERS[cmd]
            itinerary, should_exit = await handler(orchestrator, user_id, session_id, itinerary, args)
            if should_exit:
                break
        else:
            print("Unknown command. Please use /lock, /swap, /regenerate, or /done.")

async def run_app(trace: bool = False, debug: bool = False):
    if not _setup_env(debug, trace):
        return
        
    orchestrator = _init_orchestrator(DB_PATH)

    try:
        print("👋 Welcome to the Travel Activation Agent!")
        
        itinerary = await _setup_session(orchestrator, USER_ID, SESSION_ID)
        if not itinerary:
            return
            
        await _command_loop(orchestrator, itinerary, USER_ID, SESSION_ID)
    finally:
        await orchestrator.wait_for_pending_tasks()

def run_cli():
    parser = argparse.ArgumentParser(description="Travel Activation Agent CLI")
    parser.add_argument("--trace", action="store_true", help="Enable local telemetry tracing to SQLite")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    try:
        asyncio.run(run_app(trace=args.trace, debug=args.debug))
    except KeyboardInterrupt:
        print("\nExiting. Goodbye!")

if __name__ == "__main__":
    run_cli()
