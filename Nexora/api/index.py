import os
import sys
import sqlite3

# Global sqlite3 connection redirect to /tmp for Vercel
_orig_connect = sqlite3.connect
def _safe_connect(database, *args, **kwargs):
    if isinstance(database, str) and not database.startswith("/") and database != ":memory:":
        database = os.path.join("/tmp", os.path.basename(database))
    return _orig_connect(database, *args, **kwargs)
sqlite3.connect = _safe_connect

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
