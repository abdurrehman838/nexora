import sys
import os

# Add root folder to sys.path to prevent import errors
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Nexora is Live and Working Successfully!"}
