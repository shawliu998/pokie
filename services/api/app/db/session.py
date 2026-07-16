from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from services.api.app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _install_rls_context(connection: Connection, workspace_id: str, principal_id: str) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )
    connection.execute(
        text("SELECT set_config('app.principal_id', :principal_id, true)"),
        {"principal_id": principal_id},
    )


@event.listens_for(Session, "after_begin")
def restore_rls_context_after_begin(
    session: Session,
    _transaction: SessionTransaction,
    connection: Connection,
) -> None:
    workspace_id = session.info.get("glint_workspace_id")
    principal_id = session.info.get("glint_principal_id")
    if isinstance(workspace_id, str) and isinstance(principal_id, str):
        _install_rls_context(connection, workspace_id, principal_id)


def set_rls_context(session: Session, workspace_id: str, principal_id: str) -> None:
    session.info["glint_workspace_id"] = workspace_id
    session.info["glint_principal_id"] = principal_id
    if session.get_bind().dialect.name != "postgresql":
        return
    if session.in_transaction():
        _install_rls_context(session.connection(), workspace_id, principal_id)
    else:
        session.connection()


def set_principal_context(session: Session, principal_id: str) -> None:
    set_rls_context(session, "", principal_id)


def reset_database_caches() -> None:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
