from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"status": "Nexora Live!"}

@app.get("/{path:path}")
def catch_all(path: str):
    return {"status": "Nexora Live!", "path": path}
