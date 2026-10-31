from __future__ import annotations

from importlib import import_module


def register_optional_blueprint(app, *, flag_name: str, module_path: str, blueprint_attr: str) -> None:
    """
    Register an integration blueprint only when enabled and importable.
    """
    if not app.config.get(flag_name, False):
        app.logger.info("Integration %s disabled (%s=false).", module_path, flag_name)
        return

    try:
        module = import_module(module_path)
        blueprint = getattr(module, blueprint_attr)
    except ModuleNotFoundError as exc:
        app.logger.warning("Integration %s unavailable (missing dependency): %s", module_path, exc)
        return
    except Exception as exc:
        app.logger.exception("Integration %s failed to load: %s", module_path, exc)
        return

    if blueprint.name not in app.blueprints:
        app.register_blueprint(blueprint)
