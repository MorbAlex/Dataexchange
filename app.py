import os
from dotenv import load_dotenv
from flask import Flask
from db import init_db
from routes import bp

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
app.register_blueprint(bp)

init_db()

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "8000"))
    app.run(host=host, port=port, debug=True)
