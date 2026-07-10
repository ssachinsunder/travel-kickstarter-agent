# Travel Activation Agent

A personalized travel planning assistant built using the **Google Agent Development Kit (ADK)** and the Gemini API.

The agent helps users plan customized travel itineraries (up to 3 days) by gathering initial preferences (destination, duration, budget, vibe), interacting with mock tools (Places search, Weather forecast, Transit estimation), and learning from user feedback (swapping or locking activities) to update a long-term SQLite-backed preference profile.

## Features

-   **Interactive Vibe Check**: Gathers explicit user preferences at startup.
-   **Structured Itineraries**: Generates itineraries conforming to a strict JSON schema.
-   - **Active Adaptation**: Avoids outdoor activities on rainy days using weather forecast data.
-   **Interactive CLI Loop**:
    -   `/lock [index]`: Pin an activity to preserve it during subsequent regenerations.
    -   `/swap [index]`: Replace an activity with an alternative of the same category (triggers implicit preference weight decay for the disliked category).
    -   `/regenerate [feedback]`: Replan the itinerary, preserving locked items and incorporating optional text feedback.
    -   `/done`: Save the session and update the long-term user profile.
-   **Session Resume**: Automatically detects unfinished sessions and prompts to resume.
-   **Local Observability**: Option to export execution traces locally to SQLite using OpenTelemetry.

## Prerequisites

-   Python 3.10 or higher.
-   A Gemini API Key. Get one from [Google AI Studio](https://aistudio.google.com/).

## Setup Instructions

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/ssachinsunder/travel-kickstarter-agent.git
    cd travel-kickstarter-agent
    ```

2.  **Create and Activate a Virtual Environment**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Configure Environment Variables**:
    Create a `.env` file in the project root directory and add your Gemini API key:
    ```env
    GEMINI_API_KEY=your_actual_gemini_api_key_here
    ```
    The application will automatically load this file on startup.

## Installation

Install the package and its dependencies locally in editable mode:

```bash
pip install -e .
```

To install development dependencies (for running tests):

```bash
pip install -e .[dev]
```

## Running the CLI Application

Once installed, you can launch the interactive planner from anywhere in your virtual environment:

```bash
travel-agent
```

### Options

-   **Enable Local Tracing**: Export OpenTelemetry spans of agent execution directly to your local SQLite database (`travel_agent.db`):
    ```bash
    travel-agent --trace
    ```
    You can query the `spans` table in the database to inspect tool execution and LLM calls.

-   **Enable Debug Logging**:
    ```bash
    travel-agent --debug
    ```

## CLI Commands

During the planning phase, you can use the following slash commands:

-   `/lock <index>`: Pins the activity at the given index. It will not be changed by subsequent `/swap` or `/regenerate` commands.
-   `/swap <index>`: Replaces the activity with another one of the same category. The rejected category's preference weight will decay (long-term learning).
-   `/regenerate [optional feedback]`: Replaces all unlocked activities. You can append text instructions (e.g., `/regenerate add more museum visits`).
-   `/done`: Finalizes the itinerary, updates your long-term preference profile in the database, and exits.

## Running Tests

Ensure you have installed development dependencies (`pip install -e .[dev]`).

### Unit & Integration Tests

Run all unit tests (mock tools, config, persistence) and agent integration tests:

```bash
pytest
```

Run tests with coverage analysis (enforcing 80% coverage check, excluding CLI UI code):

```bash
pytest --cov=src
```

### Quality Evals (LLM-as-a-Judge)

Run the quality evaluation suite (verifies rainy day adaptation and weather API fallbacks):

```bash
pytest -s tests/test_evals.py
```
*(Note: Evals make real LLM calls and may take 30-40 seconds to complete).*
