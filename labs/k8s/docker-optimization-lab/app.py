from flask import Flask
from cryptography.fernet import Fernet
import os

app = Flask(__name__)
KEY = os.environ.get("APP_KEY", Fernet.generate_key().decode())
cipher = Fernet(KEY.encode())

@app.route("/")
def index():
    token = cipher.encrypt(b"hello from docker").decode()
    return f"signed token: {token}\n"
# comment
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)