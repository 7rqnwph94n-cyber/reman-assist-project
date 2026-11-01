def test_seed_reset_blocked_in_production(monkeypatch, test_app_factory):
    app = test_app_factory()
    app.config.update(DEBUG=False, TESTING=False, APP_ENV="production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ALLOW_DANGEROUS_COMMANDS", raising=False)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed", "--reset"])
    assert result.exit_code != 0
    assert "Refusing to run seed reset in production" in result.output


def test_seed_reset_allowed_in_dev(monkeypatch, test_app_factory):
    app = test_app_factory()
    app.config.update(DEBUG=True, TESTING=False, APP_ENV="dev")
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("ALLOW_DANGEROUS_COMMANDS", "1")
    runner = app.test_cli_runner()
    result = runner.invoke(args=["seed", "--reset", "--jobs", "1", "--templates", "1", "--items-per-template", "2"])
    assert result.exit_code == 0
