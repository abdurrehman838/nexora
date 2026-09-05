import os
import sys
import sqlite3
import traceback
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

# Force sqlite3 to redirect any relative database connection to /tmp
_orig_connect = sqlite3.connect
def _safe_connect(database, *args, **kwargs):
    if isinstance(database, str) and not database.startswith("/") and database != ":memory:":
        database = os.path.join("/tmp", os.path.basename(database))
    return _orig_connect(database, *args, **kwargs)

sqlite3.connect = _safe_connect

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI()

@app.get("/{path:path}")
@app.get("/")
def catch_all(path: str = ""):
    try:
        from main import app as main_app
        return main_app(path)
    except Exception as e:
        tb = traceback.format_exc()
        return HTMLResponse(content=f"<h3>Critical Startup Error:</h3><pre>{tb}</pre>", status_code=200)
