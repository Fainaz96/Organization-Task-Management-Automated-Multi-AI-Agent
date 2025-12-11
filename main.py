import logging
import sys
from fastapi import Depends, FastAPI, HTTPException,status
from fastapi.middleware.cors import CORSMiddleware
from routes import auth, chat
import os
import uvicorn
from dotenv import load_dotenv
from utils.logging_config import configure_logging
from schema.graphql_schema import schema
from strawberry.fastapi import GraphQLRouter
from routes.webhook import router as webhook_router


load_dotenv(override=True)

app = FastAPI(
    title="Blaid AI Multi-Channel API",
    description="Stateful API for interacting with a team of Notion agents via Web and WhatsApp.",
    version="11.1.0", # Definitive fix for response formatting
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:3000"] for more security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_event():
    """
    Configure logging on application startup.
    This is the recommended way to configure logging in FastAPI.
    """
    print("--- Application starting up, configuring logging... ---") # A helpful print statement

    # Get the root logger
    root_logger = logging.getLogger()

    # Remove any existing handlers
    # This is important to ensure you don't get duplicate logs
    # if Uvicorn has already added its own handler.
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # Create a new handler that streams to stdout
    handler = logging.StreamHandler(sys.stdout)

    # Set the log level. e.g., INFO, DEBUG, WARNING
    # You can also get this from an environment variable
    log_level = logging.INFO
    handler.setLevel(log_level)

    # Create a log formatter and add it to the handler
    # This format is easy to read and includes key information
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)

    # Add the configured handler to the root logger
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    logger.info("Logging configured successfully!")

app.include_router(auth.router, prefix="/auth")

app.include_router(chat.router)

graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")
app.include_router(webhook_router)

@app.get("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Default is now 8080
    uvicorn.run("main:app", host="0.0.0.0", port=port)
