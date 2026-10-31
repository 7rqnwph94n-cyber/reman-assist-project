from __future__ import annotations


def register_app_blueprints(app, register_optional_blueprint_fn) -> None:
    from survey.routes import survey_bp
    from parts.routes import parts_bp
    from stores.routes import stores_bp
    from auth.routes import auth_bp
    from jobs.routes import jobs_bp
    from templates.routes import templates_bp
    from costing.routes import costing_bp
    from illustrations.routes import illustrations_bp

    if "survey" not in app.blueprints:
        app.register_blueprint(survey_bp)
    if "parts" not in app.blueprints:
        app.register_blueprint(parts_bp)
    if "stores" not in app.blueprints:
        app.register_blueprint(stores_bp)
    if "auth" not in app.blueprints:
        app.register_blueprint(auth_bp)
    if "jobs" not in app.blueprints:
        app.register_blueprint(jobs_bp)
    if "templates_bp" not in app.blueprints:
        app.register_blueprint(templates_bp)
    if "costing" not in app.blueprints:
        app.register_blueprint(costing_bp)
    if "illustrations_bp" not in app.blueprints:
        app.register_blueprint(illustrations_bp)

    register_optional_blueprint_fn(
        app,
        flag_name="ENABLE_EPICOR",
        module_path="epicor.routes",
        blueprint_attr="epicor_bp",
    )
    register_optional_blueprint_fn(
        app,
        flag_name="ENABLE_QUICKBOOKS",
        module_path="quickbooks.routes",
        blueprint_attr="quickbooks_bp",
    )

    if app.config.get("ENABLE_DEV_TOOLS"):
        from dev_tools.routes import dev_tools_bp

        if "dev_tools" not in app.blueprints:
            app.register_blueprint(dev_tools_bp)
