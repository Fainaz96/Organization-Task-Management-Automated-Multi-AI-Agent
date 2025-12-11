from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

async def execute_query(
    session: AsyncSession,
    query: str,
    params: dict | tuple | None = None,
    fetch_one: bool = True
):
    """
    Executes a SQL query (SELECT/INSERT/UPDATE/DELETE) using AsyncSession.

    Args:
        session (AsyncSession): SQLAlchemy AsyncSession.
        query (str): SQL query string (use :param for named parameters).
        params (dict | tuple): Query parameters.
        fetch_one (bool): Whether to fetch one row or all (only used for SELECT).

    Returns:
        - dict | list[dict] for SELECT
        - None for INSERT/UPDATE/DELETE
    """
    result = await session.execute(text(query), params or {})

    if query.strip().lower().startswith("select"):
        rows = result.mappings()
        return rows.first() if fetch_one else rows.all()
    else:
        await session.commit() 
        return None
