import sys
import os

# Bulletproof monkeypatch to handle Vercel read-only file system globally
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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from main import app
except Exception as e:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    import traceback
    app = FastAPI()
    @app.get("/{path:path}")
    @app.get("/")
    def startup_error(path: str = ""):
        tb = traceback.format_exc()
        return HTMLResponse(content=f"<h3>Startup Error:</h3><pre>{tb}</pre>", status_code=200)
