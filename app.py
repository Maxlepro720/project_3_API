from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    username = data.get("id", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    # Vérifie si l'utilisateur existe déjà
    existing = supabase.table("ID").select("*").eq("id", username).execute()
    if existing.data and len(existing.data) > 0:
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    # Hash du mot de passe
    hashed_pw = generate_password_hash(password)

    # Insert dans Supabase
    supabase.table("users").insert({"id": username, "Password": hashed_pw}).execute()

    return jsonify({"status": "success", "message": f"Utilisateur {username} ajouté"}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("id", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    # Récupère l'utilisateur
    user = supabase.table("ID").select("*").eq("id", username).execute()
    if not user.data or len(user.data) == 0:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    user_data = user.data[0]
    if check_password_hash(user_data["Password"], password):
        return jsonify({"status": "success", "message": "Connexion réussie"}), 200
    else:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
