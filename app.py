import os
import uvicorn
from server import app

# Hugging Face Spaces default port is 7860, standard cloud port is $PORT or 8000
port = int(os.environ.get("PORT", 7860))

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
