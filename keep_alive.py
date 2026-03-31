from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "🔫 Armería Bot — Online", 200

@app.route("/health")
def health():
    return {"status": "ok"}, 200

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
```

---

**`requirements.txt`**
```
discord.py>=2.3.2
libsql-experimental>=0.0.37
flask>=3.0.0
