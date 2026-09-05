import sys
import os

# Root directory ko path mein add karein taake main.py mil jaye
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from mangum import Mangum

# Vercel serverless handler
handler = Mangum(app)