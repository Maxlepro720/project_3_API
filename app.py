from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
from datetime import datetime, timedelta
import threading
import time
import gc
import json
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

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

    existing = supabase.table("Player").select("*").eq("ID", username).execute()
    if existing.data:
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    hashed_pw = generate_password_hash(password)
    supabase.table("Player").insert({"ID": username, "Password": hashed_pw, "Status": "🔴 offline"}).execute()
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

    user = supabase.table("Player").select("*").eq("ID", username).execute()
    if not user.data:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    user_data = user.data[0]
    if not check_password_hash(user_data["Password"], password):
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    session_code = generate_session_code()
    existing_session = supabase.table("Sessions").select("*").eq("Creator", username).execute()
    if existing_session.data:
        supabase.table("Sessions").update({"Code": session_code}).eq("Creator", username).execute()
        print(f"[LOGIN] Session mise à jour pour {username}")
    else:
        supabase.table("Sessions").insert({"Code": session_code, "Creator": username, "Players": []}).execute()
        print(f"[LOGIN] Nouvelle session pour {username}")

    supabase.table("Player").update({"Status": "🟢 online"}).eq("ID", username).execute()
    return jsonify({"status": "success", "code": session_code}), 200

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
            return jsonify({"status": "success", "code": sessions[0]["Code"]}), 200
        else:
            return jsonify({"status": "error", "message": "Aucune session trouvée"}), 404
    except Exception as e:
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
        players = session.get("Players") or []

        if isinstance(players, str):
            try:
                players = json.loads(players)
            except:
                players = []

        if player_id in players:
            return jsonify({"status": "error", "message": "Déjà dans la session"}), 400

        if len(players) >= 5:
            return jsonify({"status": "error", "message": "La session est pleine (max 5 joueurs)"}), 400

        players.append(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()

        return jsonify({"status": "success", "message": f"{player_id} a rejoint la session", "players": players}), 200
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
        if isinstance(players, str):
            try:
                players = json.loads(players)
            except:
                players = []

        if player_id not in players:
            return jsonify({"status": "error", "message": "Vous n’êtes pas dans cette session"}), 400

        players.remove(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
        return jsonify({"status": "success", "message": f"{player_id} a quitté la session", "players": players}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- LOGOUT ---
@app.route("/logout", methods=["POST"])
def logout():
    data = request.get_json(force=True)
    username = (data.get("id") or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "ID manquant"}), 400
    try:
        user = supabase.table("Player").select("*").eq("ID", username).execute()
        if not user.data:
            return jsonify({"status": "error", "message": "Utilisateur introuvable"}), 404

        supabase.table("Player").update({"Status": "🔴 offline"}).eq("ID", username).execute()
        response = supabase.table("Sessions").select("*").execute()
        for session in response.data or []:
            players_raw = session.get("Players") or []
            if isinstance(players_raw, str):
                try:
                    players = json.loads(players_raw)
                except:
                    players = [players_raw]
            else:
                players = players_raw
            if username in players:
                players.remove(username)
                supabase.table("Sessions").update({"Players": players}).eq("Code", session['Code']).execute()
        return jsonify({"status": "success", "message": f"{username} est offline et retiré des sessions"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- POIRE CLICK ---
@app.route("/poire", methods=["POST"])
def poire():
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    click = (data.get("click") or 0)
    if not session_code:
        return jsonify({"status": "error", "message": "Session manquante"}), 400
    try:
        response = supabase.table("Sessions").select("*").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]
        by_click = session.get("By_Click", 1)
        poires2add = by_click * int(click)
        current_poires = session.get("poires", 0)

        new_total = current_poires + poires2add
        supabase.table("Sessions").update({"poires": new_total}).eq("Code", session_code).execute()
        return jsonify({"status": "success", "added": poires2add, "poires": new_total}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- GET POIRES ---
@app.route("/get_poires", methods=["GET"])
def get_poires():
    session_code = request.args.get("session", "").strip()
    if not session_code:
        return jsonify({"status": "error", "message": "Code de session manquant"}), 400
    try:
        session_data = supabase.table("Sessions").select("poires").eq("Code", session_code).execute()
        if not session_data.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404
        poires = session_data.data[0].get("poires", 0)
        return jsonify({"status": "success", "poires": poires}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- GET PLAYER ---
@app.route("/get_player", methods=["GET"])
def get_player():
    username = request.args.get("username", "").strip()
    session_code = request.args.get("session_code", "").strip()
    if not username or not session_code:
        return jsonify({"status": "error", "message": "Paramètres manquants"}), 400
    try:
        response = supabase.table("Sessions").select("*").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]
        players_raw = session.get("Players") or []
        creator = session.get("Creator")

        if isinstance(players_raw, str):
            try:
                players = json.loads(players_raw)
            except:
                players = [players_raw]
        else:
            players = players_raw

        if username == creator:
            other_players = [p for p in players if p != creator]
            return jsonify({"status": "success", "player": other_players}), 200
        else:
            return jsonify({"status": "success", "player": creator}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- VERIFY SESSION ---
@app.route("/verify_session", methods=["GET"])
def verify_session():
    player_id = request.args.get("id", "").strip()
    if not player_id:
        return jsonify({"status": "error", "message": "ID manquant"}), 400
    try:
        response = supabase.table("Sessions").select("*").execute()
        sessions = response.data or []
        for session in sessions:
            players_raw = session.get("Players") or []
            if isinstance(players_raw, str):
                try:
                    players = json.loads(players_raw)
                except:
                    players = [players_raw]
            else:
                players = players_raw
            if player_id in players or session.get("Creator") == player_id:
                return jsonify({
                    "status": "success",
                    "session_code": session.get("Code"),
                    "creator": session.get("Creator"),
                    "players": players
                }), 200
        return jsonify({"status": "error", "message": "Joueur non trouvé dans aucune session"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- CHANGE SESSION ---
@app.route("/change_session", methods=["POST"])
def change_session():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    new_session_name = (data.get("new_session_name") or "").strip()
    if not player_id or not new_session_name:
        return jsonify({"status": "error", "message": "ID ou nouveau nom manquant"}), 400
    try:
        existing = supabase.table("Sessions").select("*").eq("Code", new_session_name).execute()
        if existing.data:
            return jsonify({"status": "error", "message": "Ce nom de session est déjà utilisé"}), 409
        sessions = supabase.table("Sessions").select("*").execute().data or []
        session = None
        for s in sessions:
            players_raw = s.get("Players") or []
            if isinstance(players_raw, str):
                try:
                    players = json.loads(players_raw)
                except:
                    players = [players_raw]
            else:
                players = players_raw
            if s.get("Creator") == player_id or player_id in players:
                session = s
                break
        if not session:
            return jsonify({"status": "error", "message": "Aucune session trouvée pour ce joueur"}), 404
        old_session_code = session["Code"]
        supabase.table("Sessions").update({"Code": new_session_name}).eq("Code", old_session_code).execute()
        return jsonify({"status": "success", "message": f"Session changée de '{old_session_code}' à '{new_session_name}'", "new_code": new_session_name}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- Cleanup loop ---
cleanup_thread = threading.Thread(target=run_cleanup_loop, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur démarré sur le port {port}")
    app.run(host="0.0.0.0", port=port)
