from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
from datetime import datetime, timedelta
import threading
import time
import gc

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Variables d'environnement manquantes")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def generate_session_code(length=12):
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(length))

def verify_expiration(supabase_client, table="Sessions", expiration_minutes=60):
    try:
        response = supabase_client.table(table).select("Code,Expiration").limit(100).execute()
        rows = response.data or []
    except Exception as e:
        print(f"[CLEANUP] Erreur récupération sessions : {e}")
        return

    now = datetime.utcnow()

    for row in rows:
        try:
            expiration_value = row.get("Expiration")
            if not expiration_value:
                continue
            if isinstance(expiration_value, str):
                expiration_time = datetime.fromisoformat(expiration_value)
            else:
                expiration_time = expiration_value
            if now - expiration_time > timedelta(minutes=expiration_minutes):
                supabase_client.table(table).delete().eq("Code", row["Code"]).execute()
                print(f"[CLEANUP] Session {row['Code']} supprimée")
        except Exception as e:
            print(f"[CLEANUP] Erreur sur {row}: {e}")
    gc.collect()

def run_cleanup_loop():
    while True:
        verify_expiration(supabase)
        time.sleep(180)

@app.route("/")
def home():
    return "Serveur Flask en ligne"

# --- SIGNUP ---
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True)
    username = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    # Table renommée ici → "Player"
    existing = supabase.table("Player").select("*").eq("ID", username).execute()
    if existing.data:
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    hashed_pw = generate_password_hash(password)
    supabase.table("Player").insert({"ID": username, "Password": hashed_pw}).execute()
    print(f"[SIGNUP] {username} créé")

    return jsonify({"status": "success", "message": f"Utilisateur {username} ajouté"}), 201

# --- LOGIN ---
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    # Table renommée ici → "Player"
    user = supabase.table("Player").select("*").eq("ID", username).execute()
    if not user.data:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    user_data = user.data[0]
    if not check_password_hash(user_data["Password"], password):
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    Sessions_Code = generate_session_code()
    expiration_time = datetime.utcnow().isoformat()

    existing_session = supabase.table("Sessions").select("*").eq("Creator", username).execute()
    if existing_session.data:
        supabase.table("Sessions").update({"Code": Sessions_Code, "Expiration": expiration_time}).eq("Creator", username).execute()
        print(f"[LOGIN] Session mise à jour pour {username}")
    else:
        supabase.table("Sessions").insert({"Code": Sessions_Code, "Expiration": expiration_time, "Creator": username}).execute()
        print(f"[LOGIN] Nouvelle session pour {username}")

    return jsonify({"status": "success", "code": Sessions_Code}), 200

# --- SESSION INFO ---
@app.route("/session", methods=["GET"])
def my_session():
    username = request.args.get("user")
    if not username:
        return jsonify({"status": "error", "message": "ID utilisateur manquant"}), 400
    try:
        response = supabase.table("Sessions").select("Code").eq("Creator", username).execute()
        sessions = response.data
        if sessions:
            print(f"[SESSION] Session trouvée pour {username}")
            return jsonify({"status": "success", "code": sessions[0]["Code"]}), 200
        else:
            return jsonify({"status": "error", "message": "Aucune session trouvée"}), 404
    except Exception as e:
        print(f"[SESSION] Erreur : {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- JOIN SESSION ---
@app.route("/join", methods=["POST"])
def join_session():
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip()
    player_id = (data.get("id") or "").strip()

    if not code or not player_id:
        return jsonify({"status": "error", "message": "Code ou ID manquant"}), 400

    try:
        response = supabase.table("Sessions").select("*").eq("Code", code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]

        if session["Creator"] == player_id:
            return jsonify({"status": "error", "message": "Vous êtes déjà le créateur de cette session"}), 400

        players = session.get("Players") or []
        if player_id in players:
            return jsonify({"status": "error", "message": "Vous avez déjà rejoint cette session"}), 400

        players.append(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()

        return jsonify({"status": "success", "message": f"Rejoint la session {code}", "session": session}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- LEAVE SESSION ---
@app.route("/leave", methods=["POST"])
def leave_session():
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip()
    player_id = (data.get("id") or "").strip()

    if not code or not player_id:
        return jsonify({"status": "error", "message": "Code ou ID manquant"}), 400

    try:
        response = supabase.table("Sessions").select("*").eq("Code", code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]
        players = session.get("Players") or []

        if player_id not in players:
            return jsonify({"status": "error", "message": "Vous n’êtes pas dans cette session"}), 400

        players.remove(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()

        return jsonify({"status": "success", "message": f"{player_id} a quitté la session"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


cleanup_thread = threading.Thread(target=run_cleanup_loop, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur démarré sur le port {port}")
    app.run(host="0.0.0.0", port=port)
