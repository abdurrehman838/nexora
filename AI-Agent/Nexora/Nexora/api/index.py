import sys
import os

# Add parent folder to sys.path so Python can find main.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import your actual FastAPI instance from main.py
from main import app
