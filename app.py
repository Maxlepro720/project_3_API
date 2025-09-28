from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
from random import *
from datetime import datetime, timedelta


app = Flask(__name__)

# 🔹 Récupération des variables d'environnement
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 🔹 Création du client Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🔹 Nom de la table
TABLE_NAME = "Storage_ID_Password"
Sessions_Code = ""
message = ""

def generate_session_code(length=12):
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    code = "".join(random.choice(chars) for _ in range(length))
    return code

def verify_expiration(supabase_client, table="Sessions", expiration_minutes=10):
    # Lire toutes les lignes
    response = supabase_client.table(table).select("*").execute()
    rows = response.data

    now = datetime.utcnow()

    for row in rows:
        expiration_str = row.get("Expiration")
        if expiration_str:
            try:
                # Convertir la chaîne en datetime
                expiration_time = datetime.fromisoformat(expiration_str)
                if now - expiration_time > timedelta(minutes=expiration_minutes):
                    # Supprimer la ligne expirée
                    supabase_client.table(table).delete().eq("session_id", row["session_id"]).execute()
                    print(f"Session {row['session_id']} supprimée (expirée)")
            except Exception as e:
                print(f"Erreur lors de la vérification de la ligne {row}: {e}")

def run_cleanup_loop():
    while True:
        verify_expiration(supabase)
        time.sleep(20)  # toutes les 20 secondes

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
        Sessions_Code = generate_session_code()
        message = f"Connexion réussie, Code de Session : {Sessions_Code}"
r       return jsonify({"status": "success", "message": message}), 200
    else:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

threading.Thread(target=run_cleanup_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
