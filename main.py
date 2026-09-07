import asyncio
import os
import shutil
import sqlite3
import urllib.parse
import uuid
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google import genai

app = FastAPI(title="Nexora AI Assistant")

UPLOAD_DIR = "/tmp/uploads" if os.environ.get("VERCEL") else "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

STATIC_DIR = "static"
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DB_FILE = "/tmp/chat_database.db" if os.environ.get("VERCEL") else "chat_database.db"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception:
    client = None


def init_db():
    try:
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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


init_db()


@app.get("/")
def read_index():
    if os.path.exists("templates/index.html"):
        return FileResponse("templates/index.html")
    return HTMLResponse("<h3>Error: index.html file missing!</h3>")


@app.get("/sessions")
def get_sessions():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, title FROM sessions ORDER BY rowid DESC")
        rows = cursor.fetchall()
        conn.close()
        return [{"id": row[0], "title": row[1]} for row in rows]
    except Exception:
        return []


@app.post("/sessions")
def create_session():
    session_id = str(uuid.uuid4())
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute(
            "INSERT INTO sessions (id, title) VALUES (?, ?)",
            (session_id, "New Chat"),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"session_id": session_id}


@app.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    try:
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
    except Exception:
        return []


@app.post("/api/signup")
async def signup(data: dict):
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or not password:
        return {"success": False, "message": "Username and password required!"}
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return {"success": True, "message": "Account created successfully"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": "Username already exists!"}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post("/api/login")
async def login(data: dict):
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {"success": True, "username": user[1]}
        else:
            return {"success": False, "message": "Invalid username or password!"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/chat-stream")
async def chat_stream(
    session_id: str = Form(...),
    message: str = Form(...),
    web_search: bool = Form(False),
    file: Optional[UploadFile] = File(None),
):
    file_url = None
    if file:
        try:
            file_ext = os.path.splitext(file.filename or "")[1]
            file_name = f"{uuid.uuid4()}{file_ext}"
            file_path = os.path.join(UPLOAD_DIR, file_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file_url = f"/uploads/{file_name}"
        except Exception:
            pass

    try:
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
    except Exception:
        pass

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
        
        try:
            conn_inner = sqlite3.connect(DB_FILE)
            conn_inner.execute(
                "INSERT INTO messages (session_id, role, message, file_path) VALUES (?, ?, ?, ?)",
                (session_id, "assistant", final_response, None),
            )
            conn_inner.commit()
            conn_inner.close()
        except Exception:
            pass
            
        return PlainTextResponse(final_response)

    else:
        async def response_generator():
            full_response = ""
            max_retries = 2
            retry_delay = 2.0
            success = False

            for attempt in range(max_retries + 1):
                try:
                    if client:
                        response_stream = client.models.generate_content_stream(
                            model="gemini-2.5-flash",
                            contents=message,
                        )
                        for chunk in response_stream:
                            if chunk.text:
                                full_response += chunk.text
                                yield chunk.text
                        success = True
                        break
                    else:
                        full_response = "Error: Gemini client not initialized."
                        yield full_response
                        success = True
                        break
                except Exception as error:
                    err_str = str(error)
                    if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries:
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                            full_response = "Ji farmayiye, main hazir hoon! Dobara message bhejiye."
                        else:
                            full_response = f"AI Error: {err_str}"
                        yield full_response
                        success = True
                        break

            try:
                conn_inner = sqlite3.connect(DB_FILE)
                conn_inner.execute(
                    "INSERT INTO messages (session_id, role, message, file_path) VALUES (?, ?, ?, ?)",
                    (session_id, "assistant", full_response, None),
                )
                conn_inner.commit()
                conn_inner.close()
            except Exception:
                pass

        return StreamingResponse(response_generator(), media_type="text/plain")


@app.post("/clear-history")
def clear_history():
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"status": "success"}