"""
Application constants - centralized configuration values.

This module contains all magic numbers and configuration constants
to improve maintainability and prevent hardcoded values throughout the codebase.
"""

# File Upload Constants
MAX_CONTENT_LENGTH_MB = 50  # Maximum total upload size (reduced from 500MB for security)
MAX_FORM_MEMORY_MB = 50  # Maximum form data in memory
MAX_SINGLE_FILE_MB = 20  # Maximum single file size
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".txt"}
ALLOWED_ALL_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_DOCUMENT_EXTENSIONS

# Pagination Constants
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
DASHBOARD_JOBS_PER_STATUS = 20  # Jobs shown per status on dashboard

# Size Constants
KB = 1024
MB = 1024 * KB
GB = 1024 * MB

# Login Security Constants
LOGIN_MAX_ATTEMPTS = 6
LOGIN_WINDOW_SECONDS = 900  # 15 minutes
LOGIN_LOCKOUT_SECONDS = 900  # 15 minutes
LOGIN_IP_MAX_ATTEMPTS = 20
LOGIN_DELAY_SECONDS = 0.2  # Delay after failed login to slow brute force

# Password Policy Constants
PASSWORD_MIN_LENGTH = 10
PASSWORD_REQUIRE_UPPER = True
PASSWORD_REQUIRE_LOWER = True
PASSWORD_REQUIRE_DIGIT = True
PASSWORD_REQUIRE_SPECIAL = True

# Session Constants
SESSION_TIMEOUT_HOURS = 24

# Report Constants
REPORT_EMBED_IMAGES_DEFAULT = True
REPORT_MAX_IMAGE_EMBEDS = 6
REPORT_MAX_IMAGE_EMBED_MB = 5

# Database Query Constants
AUDIT_LOG_RETENTION_DAYS = 365  # How long to keep audit logs
SLOW_QUERY_THRESHOLD_SECONDS = 1.0  # Log queries slower than this

# UI Constants
FLASH_MESSAGE_MAX_LENGTH = 500
TABLE_ROW_LIMIT_WARNING = 1000  # Warn if displaying more rows than this

# Job Workflow Constants
MAX_SURVEY_ITEMS_PER_JOB = 500
MAX_PART_REQUIREMENTS_PER_JOB = 500
MAX_ATTACHMENTS_PER_JOB = 50

# Cache TTL Constants (seconds)
CACHE_TTL_SHORT = 60  # 1 minute
CACHE_TTL_MEDIUM = 300  # 5 minutes
CACHE_TTL_LONG = 3600  # 1 hour
