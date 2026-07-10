# Implementation Plan: Kickstart Agent (CLI & google-adk)

This plan outlines the step-by-step development of the Kickstart Agent. We will build a pure CLI application using the `google-adk` framework.

## 📂 Repository Info
*   **Local Path**: `/usr/local/google/home/sachinss/github/travel-kickstarter-agent`
*   **Public Link**: `https://github.com/ssachinsunder/travel-kickstarter-agent`

---

## 🛠️ Technology Stack & Defaults
*   **Framework**: `google-adk` (Google Agent Development Kit).
*   **Interface**: Python CLI (using `questionary` for interactive prompts).
*   **Database**: SQLite (via `google-adk` session service and custom memory service).
*   **LLM API**: Gemini API (via Google Gen AI SDK integration in `google-adk`).
*   **Configuration**: `python-dotenv` for local environment variables.

---

## 📋 Phase Breakdown

### Phase 1: Project Setup & Diagnostic Verification ✅
*   **Goal**: Initialize the environment, configure APIs, and verify `google-adk` integration with a minimal diagnostic agent.
*   **Tasks**:
    1.  **Project Setup**: Initialize Python project, setup virtualenv, and install core dependencies (`google-adk`, `python-dotenv`, `pytest`, `pytest-cov`, `questionary`).
        *   *Delegate*: `implementer` sub-agent.
    2.  **Environment Config**: Configure `.env` file management to use the `GEMINI_API_KEY` environment variable.
        *   *Delegate*: `implementer` sub-agent.
    3.  **ADK Diagnostics (Hello World)**: Create a minimal `google-adk` agent (e.g., `diagnose_adk.py`) that sends a simple prompt to Gemini and prints the response. This verifies ADK installation and API key configuration.
        *   *Delegate*: `implementer` sub-agent.
    4.  **Verification**: Write basic configuration loading tests and run the diagnostic agent. Verify both config loading and LLM connectivity (verified by `verifier`).
        *   *Delegate*: `implementer` (write tests) & `verifier` (run/verify).

### Phase 2: Persistence Layer (SQLite & ADK Services) ✅
*   **Goal**: Establish the database and session services before writing agent logic to avoid refactoring.
*   **Tasks**:
    1.  **Session Persistence**: Configure and initialize `google-adk`'s built-in `SqliteSessionService` to store active session states.
        *   *Delegate*: `implementer` sub-agent.
    2.  **Custom Memory Service**: Create a `SQLiteMemoryService` class extending ADK's `BaseMemoryService` to persist long-term user profiles and preferences.
        *   *Delegate*: `implementer` sub-agent.
    3.  **Verification**: Write unit and integration tests (by `implementer`) to verify that sessions and user preferences persist correctly to SQLite. `verifier` runs tests and checks for 80% coverage on DB modules.
        *   *Delegate*: `implementer` (write tests) & `verifier` (run/verify).

### Phase 3: Core Agent Logic & Algorithms ✅
*   **Goal**: Implement the agent's reasoning, tools, and preference learning algorithms.
*   **Tasks**:
    1.  **Implicit Learning Algorithm**: Implement the weight update logic for preferences. Write unit tests (by `implementer`) to verify math and state updates.
        *   *Delegate*: `implementer` sub-agent.
    2.  **Mock Tools**: Create `google-adk` compatible mock tools for Places (with fallback options), Weather (with warnings), Transit (using straight-line math, Mapbox API is out of scope for MVP), and Booking (simulated flight/hotel search).
        *   *Delegate*: `implementer` sub-agent.
    3.  **Vibe Check Prompts**: Design prompts within `google-adk` to generate structured itinerary drafts.
        *   *Delegate*: `implementer` sub-agent.
    4.  **Verification**: Write unit and integration tests for tools and prompts (by `implementer`). `verifier` runs tests and ensures core logic modules achieve 80% coverage.
        *   *Delegate*: `implementer` (write tests) & `verifier` (run/verify).

### Phase 4: Interactive CLI Interface ✅
*   **Goal**: Build the CLI user interface on top of the verified logic and DB layers.
*   **Tasks**:
    1.  **Startup Resume Logic**: Add logic to check for unfinished sessions in SQLite and prompt the user to resume.
        *   *Delegate*: `implementer` sub-agent.
    2.  **CLI Onboarding & Loop**: Implement the interactive "Vibe Check" menus and command loop (`/swap`, `/lock`, `/regenerate`, `/done`) using `questionary`.
        *   *Delegate*: `implementer` sub-agent.
    3.  **Itinerary Renderer**: Implement console formatting to print the itinerary timeline clearly.
        *   *Delegate*: `implementer` sub-agent.
    4.  **Verification**: Define a manual QA walkthrough checklist covering all CLI commands, state transitions, and resume prompts. `verifier` executes this checklist and signs off.
        *   *Delegate*: `verifier` sub-agent.

### Phase 5: Observability & Evals ✅
*   **Goal**: Set up optional tracing and LLM performance evaluations.
*   **Tasks**:
    1.  **Telemetry Flag**: Integrate `google-adk` built-in telemetry, ensuring it is only active when a `--debug` or `--trace` flag is passed to the CLI.
        *   *Delegate*: `implementer` sub-agent.
    2.  **Eval Suite**: Create synthetic test cases to programmatically verify agent logic quality (e.g., verifying that weather fallbacks trigger correctly).
        *   *Delegate*: `verifier` sub-agent.

### Phase 6: CI/CD & Packaging ✅
*   **Goal**: Package the application and set up CI automation.
*   **Tasks**:
    1.  **CLI Packaging**: Package the application as an installable local package (using `poetry` or `setup.py`).
        *   *Delegate*: `implementer` sub-agent.
    2.  **CI Pipeline**: Setup GitHub Actions to run linters, execute unit tests, and enforce the **80% coverage check** (explicitly excluding Phase 4 CLI files from the coverage calculation to avoid blocking PRs on untestable UI code).
        *   *Delegate*: `verifier` sub-agent.
    3.  **Documentation**: Create a `README.md` file with instructions on how to set up the environment (using `GEMINI_API_KEY`), install dependencies, and run the CLI application.
        *   *Delegate*: `implementer` sub-agent.
