import os
import sys
import traceback
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

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
