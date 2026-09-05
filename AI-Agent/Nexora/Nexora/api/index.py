import sys
import os
import traceback
from fastapi import FastAPI
from fastapi.responses import JSONResponse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI()

@app.middleware("http")
def catch_exceptions_middleware(request, call_next):
    try:
        return call_next(request)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error_type": str(type(exc)),
                "error_message": str(exc),
                "traceback": traceback.format_exc().splitlines()
            }
        )

try:
    from main import app as main_app
    app = main_app
except Exception as e:
    @app.get("/{path:path}")
    def import_error(path: str = ""):
        return {"import_error": str(e), "traceback": traceback.format_exc().splitlines()}
