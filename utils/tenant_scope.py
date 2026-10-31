from __future__ import annotations

from contextvars import ContextVar
from typing import Iterable

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

_current_org_id: ContextVar[int | None] = ContextVar("current_org_id", default=None)
_tenant_models: tuple[type, ...] = ()
_guard_installed = False
_session_get_wrapped = False


def set_current_org_id(org_id: int | None) -> None:
    _current_org_id.set(org_id)


def get_current_org_id() -> int | None:
    return _current_org_id.get()


def install_tenant_query_guard(models: Iterable[type]) -> None:
    """
    Apply automatic organization filtering to all SELECT queries for tenant models.
    Models must expose an `organization_id` column.
    """
    global _tenant_models, _guard_installed, _session_get_wrapped

    filtered = [m for m in models if hasattr(m, "organization_id")]
    _tenant_models = tuple(filtered)
    if _guard_installed:
        return

    @event.listens_for(Session, "do_orm_execute", retval=False)
    def _inject_tenant_scope(execute_state):
        if not execute_state.is_select:
            return
        if execute_state.execution_options.get("skip_tenant_scope"):
            return

        org_id = get_current_org_id()
        if org_id is None:
            return

        stmt = execute_state.statement
        for model in _tenant_models:
            stmt = stmt.options(
                with_loader_criteria(
                    model,
                    lambda cls: cls.organization_id == org_id,
                    include_aliases=True,
                )
            )
        execute_state.statement = stmt

    if not _session_get_wrapped:
        original_get = Session.get

        def _tenant_safe_get(self, entity, ident, *args, **kwargs):
            org_id = get_current_org_id()
            if org_id is None or not hasattr(entity, "organization_id"):
                return original_get(self, entity, ident, *args, **kwargs)

            # For non-simple PK lookups, fall back to SQLAlchemy's native behavior.
            if isinstance(ident, (tuple, dict)):
                return original_get(self, entity, ident, *args, **kwargs)

            return (
                self.query(entity)
                .filter(entity.id == ident, entity.organization_id == org_id)
                .first()
            )

        Session.get = _tenant_safe_get
        _session_get_wrapped = True

    _guard_installed = True
