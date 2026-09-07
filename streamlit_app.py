import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterator

import streamlit as st
from google import genai

APP_DIR = Path(__file__).resolve().parent
DB_FILE = Path(os.getenv("NEXORA_DB_PATH", str(APP_DIR / "chat_database.db")))
UPLOAD_DIR = APP_DIR / "uploads"
IMAGE_KEYWORDS = (
    "generate image",
    "draw",
    "image banao",
    "picture",
    "photo",
    "tasveer",
    "create an image",
    "generate a picture",
    "paint",
)

st.set_page_config(
    page_title="Nexora",
    page_icon=":speech_balloon:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_connection() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                file_path TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            );
            """
        )


def list_sessions() -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            "SELECT id, title FROM sessions ORDER BY rowid DESC"
        ).fetchall()


def create_session() -> str:
    session_id = str(uuid.uuid4())
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (id, title) VALUES (?, ?)",
            (session_id, "New Chat"),
        )
    return session_id


def get_messages(session_id: str) -> list[sqlite3.Row]:
    with get_connection() as connection:
        return connection.execute(
            "SELECT role, message, file_path FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()


def save_message(
    session_id: str, role: str, message: str, file_path: str | None = None
) -> None:
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO messages (session_id, role, message, file_path) "
            "VALUES (?, ?, ?, ?)",
            (session_id, role, message, file_path),
        )
        if role == "user":
            session = connection.execute(
                "SELECT title FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if session and session["title"] == "New Chat":
                title = message[:30] + ("..." if len(message) > 30 else "")
                connection.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?",
                    (title, session_id),
                )


def get_api_key() -> str:
    try:
        secret = st.secrets.get("GEMINI_API_KEY", "")
    except FileNotFoundError:
        secret = ""
    return str(secret or os.getenv("GEMINI_API_KEY", ""))


def get_client() -> Any:
    api_key = get_api_key()
    return genai.Client(api_key=api_key) if api_key else None


def generate_response(message: str, client: Any) -> str:
    lower_message = message.lower()
    if any(keyword in lower_message for keyword in IMAGE_KEYWORDS):
        image_prompt = message
        for keyword in IMAGE_KEYWORDS:
            image_prompt = image_prompt.replace(keyword, "").strip()
        from urllib.parse import quote

        encoded_prompt = quote(image_prompt or message)
        image_url = (
            "https://image.pollinations.ai/prompt/"
            f"{encoded_prompt}?width=1024&height=768&nologo=true"
        )
        return (
            "🎨 **Here is your generated image based on your prompt:**\n\n"
            f"![Generated Art]({image_url})\n\n*(Prompt: {message})*"
        )

    if client is None:
        return (
            "**Gemini is not configured.** Add `GEMINI_API_KEY` to Streamlit "
            "Secrets or your deployment environment variables."
        )

    try:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=message,
        )
        return response.text or "The model returned an empty response."
    except Exception as error:
        return f"**Error processing query:** {error}"


def response_chunks(response: str) -> Iterator[str]:
    for index in range(0, len(response), 20):
        yield response[index : index + 20]


def save_upload(uploaded_file: Any) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploaded_file.name).suffix
    filename = f"{uuid.uuid4()}{suffix}"
    path = UPLOAD_DIR / filename
    path.write_bytes(uploaded_file.getvalue())
    return str(path)


init_db()
if "session_id" not in st.session_state:
    sessions = list_sessions()
    st.session_state.session_id = sessions[0]["id"] if sessions else create_session()

with st.sidebar:
    st.title("Nexora")
    st.caption("Your intelligent AI assistant")

    if st.button("+ New chat", use_container_width=True):
        st.session_state.session_id = create_session()
        st.rerun()

    st.subheader("History")
    sessions = list_sessions()
    visible_sessions = [session for session in sessions if session["title"] != "New Chat"]
    for session in visible_sessions:
        label = session["title"] or "Untitled chat"
        if st.button(
            label,
            key=f"session-{session['id']}",
            use_container_width=True,
            type="primary" if session["id"] == st.session_state.session_id else "secondary",
        ):
            st.session_state.session_id = session["id"]
            st.rerun()

    st.divider()
    messages_for_export = get_messages(st.session_state.session_id)
    export_text = "# Nexora Chat Export\n\n"
    for item in messages_for_export:
        export_text += f"### {item['role'].upper()}:\n{item['message']}\n\n---\n\n"
    st.download_button(
        "Download chat (.md)",
        data=export_text,
        file_name=f"nexora-chat-{st.session_state.session_id[:6]}.md",
        mime="text/markdown",
        use_container_width=True,
        disabled=not messages_for_export,
    )
    if st.button("Clear history", use_container_width=True):
        with get_connection() as connection:
            connection.execute("DELETE FROM messages")
            connection.execute("DELETE FROM sessions")
        st.session_state.session_id = create_session()
        st.rerun()

st.title("How can I help you today?")
st.caption("Ask a question, attach a file, or request an image.")

for item in get_messages(st.session_state.session_id):
    with st.chat_message(item["role"]):
        if item["file_path"]:
            file_path = Path(item["file_path"])
            if file_path.exists() and file_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                st.image(file_path, width=280)
            else:
                st.caption(f"Attachment: {file_path.name}")
        st.markdown(item["message"])

with st.expander("Starter prompts"):
    starter_prompts = [
        "Explain quantum computing in simple terms",
        "Write a Python script to scrape a website",
        "Help me debug my machine learning pipeline code",
        "Create a Pandas and Matplotlib data analysis template",
    ]
    selected_prompt = st.selectbox("Choose a prompt", [""] + starter_prompts, label_visibility="collapsed")
    if selected_prompt and st.button("Use starter prompt"):
        st.session_state.pending_prompt = selected_prompt
        st.rerun()

web_search = st.toggle("Web search grounding", help="Reserved for a future Gemini grounding integration.")
uploaded_file = st.file_uploader("Attach a file", type=None)
pending_prompt = st.session_state.pop("pending_prompt", None)
message = st.chat_input("Write a message...") or pending_prompt

if message:
    saved_path = save_upload(uploaded_file) if uploaded_file else None
    save_message(st.session_state.session_id, "user", message, saved_path)
    with st.chat_message("user"):
        if uploaded_file:
            st.caption(f"Attachment: {uploaded_file.name}")
        st.markdown(message)

    with st.chat_message("assistant"):
        if web_search:
            st.caption("Web search grounding is enabled in the interface; the current model call does not use it yet.")
        response = generate_response(message, get_client())
        rendered_response = st.write_stream(response_chunks(response))
    save_message(st.session_state.session_id, "assistant", rendered_response)
    st.rerun()
