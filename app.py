from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)

# 🔹 Récupération des variables d'environnement
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 🔹 Création du client Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🔹 Nom de la table
TABLE_NAME = "Storage_ID_Password"

@app.route("/")
def home():
    return "Bienvenue sur le serveur 🚀"

# 🔹 Signup
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    username = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    # Vérifier si l'utilisateur existe déjà
    existing = supabase.table(TABLE_NAME).select("*").eq("ID", username).execute()
    if existing.data and len(existing.data) > 0:
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    # Hash du mot de passe
    hashed_pw = generate_password_hash(password)

    # Insérer dans Supabase
    supabase.table(TABLE_NAME).insert({
        "ID": username,
        "Password": hashed_pw
    }).execute()

    return jsonify({"status": "success", "message": f"Utilisateur {username} ajouté"}), 201

# 🔹 Login
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    # Récupérer l'utilisateur
    user = supabase.table(TABLE_NAME).select("*").eq("ID", username).execute()
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
