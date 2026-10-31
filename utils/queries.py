"""
Shared database query utilities.

This module contains common query patterns used across multiple blueprints
to avoid code duplication and ensure consistent behavior.
"""

from flask import abort
from auth_utils import get_org_filter
from models import db


def get_or_404(model, ident):
    """
    Get a model instance by ID with automatic 404 handling and organization scoping.

    For multi-tenant models (with organization_id), this automatically filters by
    the current user's organization. For other models, performs a simple get.

    Args:
        model: SQLAlchemy model class
        ident: Primary key value (usually an integer ID)

    Returns:
        Model instance

    Raises:
        404: If object not found or user lacks access (wrong organization)
    """
    if hasattr(model, "organization_id"):
        org_filter = get_org_filter(model)
        obj = model.query.filter(model.id == ident, org_filter).first()
    else:
        obj = db.session.get(model, ident)

    if not obj:
        abort(404)

    return obj


def get_or_none(model, ident):
    """
    Get a model instance by ID with organization scoping, return None if not found.

    Like get_or_404 but returns None instead of aborting.

    Args:
        model: SQLAlchemy model class
        ident: Primary key value

    Returns:
        Model instance or None
    """
    if hasattr(model, "organization_id"):
        org_filter = get_org_filter(model)
        return model.query.filter(model.id == ident, org_filter).first()
    else:
        return db.session.get(model, ident)
