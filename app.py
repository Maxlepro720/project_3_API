from flask import Flask, request, jsonify
from supabase import create_client, Client
import os

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route("/")
def home():
    return "Bienvenue sur le serveur 🚀"

# Signup
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    user_id = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not user_id or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    try:
        # Supabase crée l'utilisateur et hash le mot de passe automatiquement
        response = supabase.auth.sign_up(
            {
                "email": user_id,  # on utilise email comme identifiant
                "password": password
            }
        )
        if response.user:
            return jsonify({"status": "success", "message": f"Utilisateur {user_id} ajouté"}), 201
        else:
            return jsonify({"status": "error", "message": response.error.message}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Login
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    user_id = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not user_id or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    try:
        response = supabase.auth.sign_in_with_password({
            "email": user_id,
            "password": password
        })

        if response.user:
            return jsonify({"status": "success", "message": "Connexion réussie"}), 200
        else:
            return jsonify({"status": "error", "message": response.error.message}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

