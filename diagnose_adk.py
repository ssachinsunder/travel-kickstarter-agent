import asyncio
import os
import sys
from google.genai import types

# Adjust path to import src
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.config import config
from google.adk.agents.llm_agent import Agent
from google.adk.runners import InMemoryRunner

def extract_event_text(event) -> str:
    """Extracts plain text parts from the ADK Event."""
    if event.content and event.content.parts:
        text_parts = []
        for part in event.content.parts:
            if part.text:
                text_parts.append(part.text)
        return "".join(text_parts).strip()
    return ""

async def main():
    print("Starting ADK Diagnostics...")
    
    # 1. Verify config
    try:
        api_key = config.gemini_api_key
        print(f"✅ Config loaded. API Key is set (starts with: {api_key[:4]}...)")
    except ValueError as e:
        print(f"❌ Config error: {e}")
        print("\nPlease update the .env file in the root directory with your API key.")
        return

    # Ensure the API key is in the environment for ADK to use
    # Config loader checked both, we set GOOGLE_API_KEY as it's more commonly used by older ADK versions
    # or GEMINI_API_KEY for newer ones. We set both to be safe.
    os.environ["GEMINI_API_KEY"] = api_key
    os.environ["GOOGLE_API_KEY"] = api_key

    # 2. Create Agent
    print("Creating Agent...")
    try:
        agent = Agent(
            name="DiagnosticAgent",
            model="gemini-3.5-flash",
            instruction="You are a helpful assistant. Reply with 'ADK is working!' if you receive this message.",
        )
        print("✅ Agent created.")
    except Exception as e:
        print(f"❌ Failed to create Agent: {e}")
        return

    # 3. Create Runner
    print("Creating Runner...")
    try:
        runner = InMemoryRunner(agent=agent)
        print("✅ Runner created.")
    except Exception as e:
        print(f"❌ Failed to create Runner: {e}")
        return

    # 4. Create Session
    print("Creating Session...")
    try:
        await runner.session_service.create_session(
            app_name=runner.app_name,
            user_id="diagnostic_user",
            session_id="diagnostic_session",
        )
        print("✅ Session created.")
    except Exception as e:
        print(f"❌ Failed to create Session: {e}")
        return

    # 5. Run Agent
    print("Running Agent query...")
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Hello, please verify if you are working.")],
    )
    
    try:
        # runner.run is synchronous generator
        events = list(
            runner.run(
                user_id="diagnostic_user",
                session_id="diagnostic_session",
                new_message=new_message,
            )
        )
        
        response_found = False
        for event in events:
            text = extract_event_text(event)
            if text:
                print(f"\n💬 Agent Response: {text}")
                response_found = True
                
        if response_found:
            print("\n🎉 ADK Diagnostics PASSED!")
        else:
            print("\n⚠️ ADK Diagnostics completed but no response text was received.")
            
    except Exception as e:
        print(f"❌ Failed to run Agent: {e}")

if __name__ == "__main__":
    asyncio.run(main())
