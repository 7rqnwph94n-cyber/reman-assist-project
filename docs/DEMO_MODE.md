# Demo Mode (Hard-Blocked in Prod)

Demo reset is allowed only when:
- `APP_ENV=demo`
- `DEMO_RESET_ENABLED=1`

Command:
```
python -m flask --app app:create_app demo-reset --seed
```

Attempting in production logs a warning and fails.
