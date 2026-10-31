# Technical Debt

## Security
- [ ] Tighten CSP by extracting inline scripts/styles ([app.py:668](app.py#L668))
  - Currently allows 'unsafe-inline' for both scripts and styles
  - Should extract inline event handlers and style attributes to separate files
  - Benefits: Stronger XSS protection, better compliance with security standards

## Testing
- [ ] Fix broken test suite (tests need organization_id updates)
  - Many tests fail with `NOT NULL constraint failed: templates.organization_id`
  - Need to update test fixtures to include organization_id for multi-tenant models
- [ ] Increase test coverage from 13% to 40%+
  - Current coverage is low, especially for business logic
  - Priority: services/, auth/, parts/ modules

## Performance
- [ ] Add caching layer for frequently accessed data
  - Template listings, user permissions, organization data
  - Consider Redis or in-memory caching with TTL
- [ ] Implement Redis for production (currently optional)
  - Currently falls back to in-memory for login throttling
  - Production should use Redis for proper distributed rate limiting

## Code Quality
- [ ] Add type hints to remaining functions
  - Many functions lack type annotations
  - Would improve IDE support and catch bugs earlier
- [ ] Document complex business logic functions
  - BOM generation, measurement validation, job state transitions
  - Add docstrings with examples for complex workflows

## Infrastructure
- [ ] Set up CI/CD pipeline
  - Automated testing on push
  - Lint checks (flake8, black, mypy)
  - Automated deployment to staging
- [ ] Configure monitoring and alerting
  - APM tool (New Relic, DataDog, or Sentry)
  - Error tracking and performance monitoring
  - Database connection pool monitoring

## Nice to Have
- [ ] Extract inline JavaScript to separate files
  - Remove inline onclick handlers
  - Use event delegation and unobtrusive JavaScript
- [ ] Implement proper logging configuration
  - Structured logging with context (user, org, job)
  - Log rotation and retention policies
- [ ] Add API rate limiting beyond login
  - Prevent abuse of file upload, export, and search endpoints
