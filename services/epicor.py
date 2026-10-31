"""
Epicor (Kinetic) integration helpers.

This module is deliberately light-touch: no external calls are made unless
configuration is present. Network calls should be added once IT provides
endpoints/credentials.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import requests

from models import (
    db,
    EpicorSetting,
)


def _has_api_key(setting: EpicorSetting) -> bool:
    if not setting:
        return False
    if not setting.api_key_env_var:
        return False
    return bool(os.environ.get(setting.api_key_env_var))


def _get_epicor_headers(setting: EpicorSetting) -> Dict[str, str]:
    """
    Get request headers for Epicor, including auth.
    Note: OAuth not yet implemented.
    """
    headers = {"Content-Type": "application/json"}
    if setting and setting.api_key_env_var:
        api_key = os.environ.get(setting.api_key_env_var)
        if api_key:
            headers["x-api-key"] = api_key
    return headers


def test_connection(setting: EpicorSetting) -> Tuple[bool, str]:
    """
    Best-effort test of connectivity/credentials.
    Attempts a lightweight GET to a protected endpoint.
    """
    if not setting or not setting.base_url:
        return False, "Missing base URL."

    if setting.auth_method.name.lower() == "api_key":
        if not _has_api_key(setting):
            return False, f"API key not found in env var {setting.api_key_env_var or 'EPICOR_API_KEY'}."
    else:
        return False, "OAuth not yet implemented. Please use API key authentication."

    headers = _get_epicor_headers(setting)
    if "x-api-key" not in headers:
        return False, "API key is missing from request headers."

    # Use a simple, protected endpoint. Assume BaqSvc endpoint requires auth.
    url = f"{setting.base_url.rstrip('/')}/api/v2/odata/{setting.company}/BaqSvc/"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return True, f"Successfully connected to {setting.company} (HTTP 200)."
        elif resp.status_code == 401:
            return False, "Authentication failed (HTTP 401 Unauthorized). Check your API key."
        else:
            return False, f"HTTP {resp.status_code} from Epicor endpoint. Details: {resp.text[:200]}"
    except Exception as exc:
        return False, f"Connection failed: {exc}"


def execute_baq(setting: EpicorSetting, baq_name: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Execute a BAQ and return the JSON response.
    """
    if not setting or not setting.base_url or not setting.company or not baq_name:
        raise ValueError("Missing required settings for BAQ execution.")

    headers = _get_epicor_headers(setting)
    url = f"{setting.base_url.rstrip('/')}/api/v2/odata/{setting.company}/BaqSvc/{baq_name}"

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to execute BAQ '{baq_name}': {e}") from e


def run_sample_query(setting: EpicorSetting) -> Tuple[bool, str, list[Dict[str, Any]]]:
    """
    Run the configured part cost BAQ as a sample query.
    """
    if not setting or not setting.baq_part_cost:
        return False, "Part cost BAQ not configured.", []

    try:
        data = execute_baq(setting, setting.baq_part_cost)
        rows = data.get("value", [])
        return True, f"Successfully executed BAQ '{setting.baq_part_cost}'.", rows
    except (ValueError, RuntimeError, requests.exceptions.RequestException) as e:
        return False, str(e), []


def mark_synced(setting: EpicorSetting) -> None:
    setting.last_synced_at = datetime.now(timezone.utc)
    db.session.add(setting)


def _map_baq_row_to_costing_line(row: Dict[str, Any], existing_line: "CostingTemplateLine" = None) -> "CostingTemplateLine":
    """
    Map a BAQ result row to a CostingTemplateLine model.
    This is a placeholder and will likely need to be adjusted based on the actual BAQ structure.
    """
    if not existing_line:
        existing_line = CostingTemplateLine()

    existing_line.system_part_number = row.get("Part_PartNum")
    existing_line.part_description = row.get("Part_PartDescription")
    existing_line.default_latest_cost = row.get("PartCost_StdCost")
    existing_line.default_latest_supplier = row.get("Vendor_Name")
    existing_line.default_qty_on_stock = row.get("PartWhse_OnHandQty")

    return existing_line


def sync_catalogue(setting: EpicorSetting) -> Tuple[bool, str]:
    """
    Fetch data from the part cost BAQ and update the local costing template lines.
    """
    if not setting or not setting.baq_part_cost:
        return False, "Part cost BAQ not configured."

    if not setting.template_id:
        return False, "No default engine template configured for this Epicor setting."

    try:
        data = execute_baq(setting, setting.baq_part_cost)
        rows = data.get("value", [])

        if not rows:
            return True, "BAQ executed successfully, but returned no data."

        # Get the active costing template profile for the default template
        profile = (
            CostingTemplateProfile.query.filter_by(
                engine_template_id=setting.template_id, is_active=True
            )
            .order_by(CostingTemplateProfile.version.desc())
            .first()
        )

        if not profile:
            return False, "No active costing template profile found for the default engine template."

        # Create a map of existing lines for efficient lookup
        existing_lines = {
            line.system_part_number: line
            for line in profile.template_lines
            if line.system_part_number
        }

        updated_count = 0
        created_count = 0

        for row in rows:
            part_num = row.get("Part_PartNum")
            if not part_num:
                continue

            existing_line = existing_lines.get(part_num)
            if existing_line:
                _map_baq_row_to_costing_line(row, existing_line)
                updated_count += 1
            else:
                new_line = _map_baq_row_to_costing_line(row)
                new_line.costing_template_profile_id = profile.id
                db.session.add(new_line)
                created_count += 1

        mark_synced(setting)
        db.session.commit()
        return True, f"Sync complete. Updated {updated_count} and created {created_count} costing lines."

    except (ValueError, RuntimeError, requests.exceptions.RequestException) as e:
        return False, str(e)
