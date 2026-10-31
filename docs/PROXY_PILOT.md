# Pilot Proxy Requirements

- Login rate limit: 3 req/min per IP
- Global rate limit: 10 req/sec per IP
- `client_max_body_size` set (200MB default for pilots)
- Timeouts for PDF export: 300s

Use `deploy/pilot_nginx.conf` as the baseline.

Checklist:
- Config installed
- `nginx -t` passes
- Reloaded service
- Verified login throttling in logs
