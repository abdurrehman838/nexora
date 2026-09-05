import sys
import os
import traceback
from fastapi import FastAPI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from main import app as main_app
    app = main_app
except Exception as e:
    app = FastAPI()
    error_details = traceback.format_exc()

    @app.get("/{path:path}")
    def catch_all(path: str = ""):
        return {
            "status": "Error loading main.py",
            "error": str(e),
            "traceback": error_details.splitlines()
        }
