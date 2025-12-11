import os
import urllib.parse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import MetaData
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# Create metadata instance for table definitions
metadata = MetaData()

# --- Database Connection Setup ---

DATABASE_URL = None
connect_args = {}

if os.environ.get('K_SERVICE'):
    # Production environment (Google Cloud Run)
    print("Connecting to database via Cloud SQL socket...")
    unix_socket_path = f"/cloudsql/{os.environ['INSTANCE_CONNECTION_NAME']}/.s.mysql.5.7"
    DB_USER = os.environ['DB_USER']
    DB_PASSWORD = os.environ['DB_PASSWORD']
    DB_NAME = os.environ['DB_NAME']

    # Use the asyncmy driver for asyncio support
    DATABASE_URL = f"mysql+asyncmy://{DB_USER}:{DB_PASSWORD}@/{DB_NAME}?unix_socket={unix_socket_path}"
else:
    # Local development environment
    print("Connecting to database via local TCP...")
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_USER = os.getenv("DB_USER")
    # DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_PASSWORD = urllib.parse.quote_plus(os.getenv("DB_PASSWORD"))
    DB_NAME = os.getenv("DB_NAME")
    DB_PORT = os.getenv("DB_PORT", "3306")

    DATABASE_URL = f"mysql+asyncmy://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    connect_args = {
        "ssl": {"ssl_disabled": True}  # skips certificate verification
    }   
    print(DATABASE_URL)
if not DATABASE_URL:
    raise Exception("Database configuration not found!")

# --- SQLAlchemy Engine and Session Factory ---

# Create the core async engine with connection pooling
# This is the most important part for fixing your issue
engine = create_async_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_size=20,
    max_overflow=10,
    pool_recycle=1800,
    pool_pre_ping=True,  # NEW: detect stale connections automatically
    echo=False
)

# Create a factory for generating new async sessions
AsyncSessionFactory = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False  # Good practice for FastAPI dependencies
)


# --- FastAPI Dependency ---

async def get_db_session() -> AsyncSession:
    """
    FastAPI dependency that provides a database session per request.
    This ensures each request has a clean, isolated session from the pool.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# Alias for backward compatibility
get_db_connection = get_db_session
