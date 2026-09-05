import sys
import os
from fastapi import FastAPI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI()

try:
    from main import app as main_app
    app = main_app
except Exception as err:
    @app.get("/")
    @app.get("/{path:path}")
    def catch_error(path: str = ""):
        return {"error": "Failed to import main.py", "details": str(err)}
