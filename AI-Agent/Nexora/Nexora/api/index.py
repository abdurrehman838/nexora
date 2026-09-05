import sys
import os
import traceback
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI()

try:
    from main import app as main_app
    app = main_app
except Exception as e:
    tb = traceback.format_exc()
    @app.get("/{path:path}")
    @app.get("/")
    def catch_all(path: str = ""):
        return HTMLResponse(content=f"<h3>Runtime/Startup Error inside main.py:</h3><pre>{tb}</pre>", status_code=200)
