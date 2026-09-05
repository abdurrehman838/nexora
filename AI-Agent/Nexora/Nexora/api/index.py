import sys
import os
from fastapi import FastAPI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from main import app
except Exception as e:
    app = FastAPI()

    @app.get("/{path:path}")
    def catch_all(path: str = ""):
        return {"error_importing_main": str(e)}
