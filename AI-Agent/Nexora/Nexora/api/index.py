import sys
import os
import traceback
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI()

@app.get("/")
@app.get("/{path:path}")
def debug_route(path: str = ""):
    try:
        from main import app as main_app
        return {"status": "main_imported_successfully", "path": path}
    except Exception as e:
        tb = traceback.format_exc()
        html_content = f"<h2>Import/Runtime Error in main.py:</h2><pre>{tb}</pre>"
        return HTMLResponse(content=html_content, status_code=200)
