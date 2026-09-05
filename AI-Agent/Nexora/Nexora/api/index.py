import os
import sys

# Ensure project root is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Safe monkeypatch for Vercel read-only filesystem
if os.environ.get("VERCEL") or os.path.exists("/var/task"):
    _orig_makedirs = os.makedirs
    def _safe_makedirs(name, mode=0o777, exist_ok=False):
        if "uploads" in str(name):
            name = "/tmp/uploads"
        try:
            return _orig_makedirs(name, mode, exist_ok)
        except OSError as e:
            if e.errno == 30:
                pass
            else:
                raise
    os.makedirs = _safe_makedirs

from main import app
