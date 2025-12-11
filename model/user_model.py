from sqlalchemy import Table, Column, String, Integer, DateTime, ForeignKey
from db import metadata

users = Table(
    "users",
    metadata,
    Column("user_id",Integer, primary_key=True, autoincrement=True),
    Column("username", String(100), nullable=False),
    Column("email", String(255)),
    Column("password", String(255)),
    Column("roleId", Integer, ForeignKey("role.roleId")),
)

role = Table(
    "role",
    metadata,
    Column("roleId", Integer, primary_key=True, autoincrement=True),
    Column("roleName", String(100), nullable=False),
    Column("roleDesc", String(255)),
    Column("createdAt", DateTime),
    Column("updatedAt", DateTime),
)
