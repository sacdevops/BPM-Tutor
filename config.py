import os
from dotenv import load_dotenv

load_dotenv()

CAMPUS_KI_BASE_URL = os.getenv("CAMPUS_KI_BASE_URL", "https://chat.kiconnect.nrw/api")

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY not set in .env file")
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

AI_CONFIG = {
    "max_chat_history": 20,
}

LOG_LLM_IO = False
