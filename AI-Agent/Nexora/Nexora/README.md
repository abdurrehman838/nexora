# Nexora

Nexora is a Streamlit AI assistant powered by Google Gemini.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-key"
streamlit run streamlit_app.py
```

The app opens at `http://localhost:8501`.

## Deploy with Streamlit Community Cloud

1. Push this repository to GitHub.
2. Create a new app at [share.streamlit.io](https://share.streamlit.io).
3. Select `streamlit_app.py` as the main file.
4. Add this secret in the app settings under **Secrets**:

```toml
GEMINI_API_KEY = "your-key"
```

Optional settings:

```toml
GEMINI_MODEL = "gemini-2.5-flash"
```

SQLite and uploaded files use the app filesystem. Streamlit Community Cloud storage is ephemeral, so use an external database and object storage if chat history or attachments must survive redeployments.
