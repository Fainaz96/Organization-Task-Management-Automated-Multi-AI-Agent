# Blaid AI Multi-Channel API

**Stateful API for interacting with a team of Notion agents via Web and WhatsApp.**

## Overview

The Blaid AI Multi-Channel API is a robust backend service built with FastAPI that orchestrates a team of AI agents to manage Notion workspaces. It supports multi-channel interactions, allowing users to communicate with agents through both a web interface and WhatsApp. The system leverages OpenAI's GPT models to interpret user intent and perform complex tasks such as creating, modifying, and retrieving Notion pages, as well as managing comments and reminders.

## Key Features

- **Multi-Channel Support**: Seamless interaction via Web and WhatsApp endpoints.
- **Notion Integration**: Comprehensive suite of agents capable of:
    - **Task Creation**: Intelligent creation of tasks with properties.
    - **Task Modification**: Updating existing Notion pages.
    - **Task Retrieval**: Searching and retrieving specific tasks.
    - **Comments & Reminders**: Managing page comments and setting reminders.
- **Specialized AI Agents**:
    - **Supervisor Agent**: Orchestrates the workflow and delegates tasks to sub-agents.
    - **Analysis Agent**: Analyzes task requirements.
    - **Content Generation Agent**: Generates content for tasks.
    - **User Agent**: Manages user contexts.
- **GraphQL API**: Flexible data querying capabilities via `/graphql` using Strawberry.
- **Authentication**: Secure access control via `/auth` endpoints.
- **Webhooks**: Event-driven architecture support.

## Tech Stack

- **Framework**: FastAPI, Uvicorn
- **AI/LLM**: OpenAI API (GPT-4), `openai-agents`
- **Database**: MySQL (`asyncmy`), SQLAlchemy
- **Integrations**: Notion Client, Twilio (implied for WhatsApp), Strawberry GraphQL
- **Utilities**: `pydantic`, `python-dotenv`, `httpx`

## Setup Instructions

### Prerequisites

- Python 3.10+
- MySQL Database
- OpenAI API Key
- Notion Integration Token

### Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd FastAPI_Testapp
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Linux/macOS
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    Create a `.env` file in the root directory and add the following variables:
    ```env
    OPENAI_API_KEY=your_openai_api_key
    NOTION_API_KEY=your_notion_api_key
    DATABASE_URL=mysql+asyncmy://user:password@host/dbname
    # Add other necessary variables based on usage
    ```

5.  **Run the Application:**
    ```bash
    python main.py
    ```
    The server will start on `http://0.0.0.0:8080` (or the port specified in `PORT` env var).

## API Documentation

Once the application is running, you can access the interactive API documentation at:

- **Swagger UI**: `http://localhost:8080/docs`
- **ReDoc**: `http://localhost:8080/redoc`
- **GraphQL Playground**: `http://localhost:8080/graphql`

## Project Structure

- `main.py`: Application entry point and configuration.
- `routes/`: API route definitions (Auth, Chat, Webhook).
- `local_agents/`: Implementation of specialized Notion agents.
- `schema/`: GraphQL schema definitions.
- `services/`: Business logic and service layers.
- `utils/`: Utility functions and logging configuration.
- `model/`: Database models.
- `db.py`: Database connection setup.

## License

[License Name] - See LICENSE file for details.
