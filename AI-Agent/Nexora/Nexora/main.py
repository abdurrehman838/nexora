import os
import shutil
import sqlite3
import urllib.parse
import uuid
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google import genai

app = FastAPI(title="Abdur AI Universal Assistant")

UPLOAD_DIR = "/tmp/uploads" if os.environ.get("VERCEL") else "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DB_FILE = "chat_database.db"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception:
    client = None


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            message TEXT,
            file_path TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions (id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


@app.get("/")
def read_index():
    if os.path.exists("templates/index.html"):
        return FileResponse("templates/index.html")
    return HTMLResponse(
        "<h3>Error: index.html file missing in templates folder! "
        "Please make sure it is inside the 'templates' directory.</h3>"
    )


@app.get("/sessions")
def get_sessions():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM sessions ORDER BY rowid DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": row[0], "title": row[1]} for row in rows]


@app.post("/sessions")
def create_session():
    session_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "INSERT INTO sessions (id, title) VALUES (?, ?)",
        (session_id, "New Chat"),
    )
    conn.commit()
    conn.close()
    return {"session_id": session_id}


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, message, file_path FROM messages WHERE session_id = ?",
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {"role": row[0], "message": row[1], "file_path": row[2]}
        for row in rows
    ]


@app.post("/chat-stream")
async def chat_stream(
    session_id: str = Form(...),
    message: str = Form(...),
    web_search: bool = Form(False),
    file: Optional[UploadFile] = File(None),
):
    file_url = None
    if file:
        file_ext = os.path.splitext(file.filename or "")[1]
        file_name = f"{uuid.uuid4()}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        file_url = f"/uploads/{file_name}"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (session_id, role, message, file_path) VALUES (?, ?, ?, ?)",
        (session_id, "user", message, file_url),
    )
    cursor.execute("SELECT title FROM sessions WHERE id = ?", (session_id,))
    result = cursor.fetchone()
    if result and result[0] == "New Chat":
        new_title = message[:30] + ("..." if len(message) > 30 else "")
        cursor.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (new_title, session_id),
        )
    conn.commit()
    conn.close()

    lower_message = message.lower()
    image_keywords = [
        "generate image", "draw", "image banao", "picture", "photo",
        "tasveer", "create an image", "generate a picture", "paint",
    ]
    is_image_request = any(keyword in lower_message for keyword in image_keywords)

    if is_image_request:
        image_prompt = message
        for keyword in image_keywords:
            image_prompt = image_prompt.replace(keyword, "").strip()
        encoded_prompt = urllib.parse.quote(image_prompt or message)
        generated_image_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            "?width=1024&height=768&nologo=true"
        )
        final_response = (
            "**Here is your generated image based on your prompt:**\n\n"
            f"![Generated Art]({generated_image_url})\n\n"
            f"*(Prompt: {message})*"
        )
    else:
        try:
            if client:
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=message,
                )
                final_response = response.text
            else:
                final_response = "**Client Error:** GenAI client is not initialized properly."
        except Exception as error:
            final_response = f"Error processing query with AI model: {error}"

    async def generate():
        for index in range(0, len(final_response), 20):
            yield final_response[index:index + 20]

        conn_inner = sqlite3.connect(DB_FILE)
        conn_inner.execute(
            "INSERT INTO messages (session_id, role, message, file_path) VALUES (?, ?, ?, ?)",
            (session_id, "assistant", final_response, None),
        )
        conn_inner.commit()
        conn_inner.close()

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/clear-history")
def clear_history():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()
    return {"status": "success"}
