import os
import sys
from pathlib import Path

# Force testing config before importing app
os.environ.setdefault("FLASK_CONFIG", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# Ensure project root is on sys.path so imports like `import app` work in tests
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
