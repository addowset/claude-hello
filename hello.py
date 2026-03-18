import webbrowser
import threading
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/greet", methods=["POST"])
def greet():
    data = request.get_json()
    name = data.get("name", "").strip()

    if len(name.split()) < 2:
        return jsonify({"status": "need_full_name"})

    return jsonify({"status": "ok", "message": f"Hi, {name}!"})

def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    threading.Timer(1, open_browser).start()
    app.run(debug=False)
