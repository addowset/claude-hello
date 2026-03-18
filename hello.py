import webbrowser
import threading
import json
import os
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

NAMES_FILE = os.path.join(os.path.dirname(__file__), "names.json")

def load_names():
    if os.path.exists(NAMES_FILE):
        with open(NAMES_FILE, "r") as f:
            return json.load(f)
    return []

def save_name(name):
    names = load_names()
    normalised = name.lower()
    if normalised not in [n.lower() for n in names]:
        names.append(name)
        with open(NAMES_FILE, "w") as f:
            json.dump(names, f, indent=2)
    return names

def is_returning(name):
    names = load_names()
    return name.lower() in [n.lower() for n in names]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/greet", methods=["POST"])
def greet():
    data = request.get_json()
    name = data.get("name", "").strip()

    if len(name.split()) < 2:
        return jsonify({"status": "need_full_name"})

    if is_returning(name):
        return jsonify({"status": "returning", "name": name})

    save_name(name)
    return jsonify({"status": "ok", "message": f"Hi, {name}!"})

def open_browser():
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    threading.Timer(1, open_browser).start()
    app.run(debug=False)
