from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
from datetime import datetime, timedelta
import threading
import time


app = Flask(__name__)

# 🔹 Récupération des variables d'environnement
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# 🔹 Création du client Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 🔹 Nom de la table
TABLE_NAME = "Storage_ID_Password"

def generate_session_code(length=12):
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    code = "".join(random.choice(chars) for _ in range(length))
    return code

def verify_expiration(supabase_client, table="Sessions", expiration_minutes=60):
    """
    Vérifie toutes les sessions de la table et supprime celles dont
    la colonne 'Expiration' est plus ancienne que expiration_minutes.
    """
    try:
        # Lire toutes les lignes
        response = supabase_client.table(table).select("*").execute()
        rows = response.data
    except Exception as e:
        print(f"Erreur lors de la récupération des sessions : {e}")
        return

    now = datetime.utcnow()

    for row in rows:
        expiration_value = row.get("Expiration")
        if not expiration_value:
            continue  # pas de date, on ignore

        try:
            # Convertir en datetime si nécessaire
            if isinstance(expiration_value, str):
                expiration_time = datetime.fromisoformat(expiration_value)
            elif isinstance(expiration_value, datetime):
                expiration_time = expiration_value
            else:
                print(f"Format inattendu pour la date : {expiration_value}")
                continue

            # Vérifier si la session est expirée
            if now - expiration_time > timedelta(minutes=expiration_minutes):
                supabase_client.table(table).delete().eq("Code", row["Code"]).execute()
                print(f"Session {row['Code']} supprimée (expirée)")

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
# 🔹 Login
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    # Vérifier l'utilisateur
    user = supabase.table(TABLE_NAME).select("*").eq("ID", username).execute()
    if not user.data or len(user.data) == 0:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    user_data = user.data[0]
    if not check_password_hash(user_data["Password"], password):
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    # Générer un nouveau code de session
    Sessions_Code = generate_session_code()
    expiration_time = datetime.utcnow().isoformat()

    # Vérifier si l'utilisateur a déjà une session
    existing_session = supabase.table("Sessions").select("*").eq("Creator", username).execute()

    if existing_session.data and len(existing_session.data) > 0:
        # Mettre à jour le code et l'expiration
        supabase.table("Sessions").update({
            "Code": Sessions_Code,
            "Expiration": expiration_time
        }).eq("Creator", username).execute()
    else:
        # Créer une nouvelle session
        supabase.table("Sessions").insert({
            "Code": Sessions_Code,
            "Expiration": expiration_time,
            "Creator": username
        }).execute()

    message = f"Connexion réussie, Code de Session : {Sessions_Code}"
    return jsonify({"status": "success", "message": message}), 200

@app.route("/session", methods=["GET"])
def my_session():
    username = request.args.get("user")  # on passe l'id de l'utilisateur dans l'URL

    if not username:
        return jsonify({"status": "error", "message": "ID utilisateur manquant"}), 400

    try:
        response = supabase.table("Sessions").select("*").eq("Creator", username).execute()
        sessions = response.data

        if sessions and len(sessions) > 0:
            # On renvoie uniquement le code de session
            return jsonify({"status": "success", "code": sessions[0]["Code"]}), 200
        else:
            return jsonify({"status": "error", "message": "Aucune session trouvée"}), 404

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/check_session", methods=["GET"])
def check_session():
    """Vérifie si un code de session existe dans la base Supabase"""
    code = request.args.get("code")

    if not code:
        return jsonify({"status": "error", "message": "Code manquant"}), 400

    try:
        # Vérifie dans la table Sessions si le code existe
        response = supabase.table("Sessions").select("*").eq("Code", code).execute()
        sessions = response.data

        if sessions and len(sessions) > 0:
            return jsonify({"exists": True, "creator": sessions[0].get("Creator")}), 200
        else:
            return jsonify({"exists": False}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500




threading.Thread(target=run_cleanup_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port)
