from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
import json
from flask_cors import CORS
# Note: threading, time, datetime, timedelta, timezone ne sont plus utilisés dans ce script mais conservés pour les imports
import threading
import time
from datetime import datetime, timedelta, timezone 

MAX_SESSION_CODE_LENGTH = 14

app = Flask(__name__)
CORS(app)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Variables d'environnement SUPABASE_URL ou SUPABASE_KEY manquantes")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------------------------------------------------------------
# --- UTILITIES ---
# ----------------------------------------------------------------------

def generate_session_code(length=12):
    if length > MAX_SESSION_CODE_LENGTH:
        length = MAX_SESSION_CODE_LENGTH
        
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(length))

# ----------------------------------------------------------------------
# --- ROUTES FLASK ---
# ----------------------------------------------------------------------

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
    supabase.table("Player").insert({
        "ID": username, 
        "Password": hashed_pw, 
        "Status": "🔴 offline",
    }).execute()
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

    user = supabase.table("Player").select("Password").eq("ID", username).execute()
    if not user.data:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    user_data = user.data[0]
    if not check_password_hash(user_data["Password"], password):
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    existing_session = supabase.table("Sessions").select("Code").eq("Creator", username).execute()
    if existing_session.data:
        session_code = existing_session.data[0]["Code"]
    else:
        session_code = generate_session_code()
        supabase.table("Sessions").insert({
            "Code": session_code, 
            "Creator": username, 
            "Players": [], 
            "poires": 0, 
            "By_Click": 1
        }).execute()
        
    supabase.table("Player").update({"Status": "🟢 online"}).eq("ID", username).execute()
    print(f"[LOGIN] {username} connecté, session: {session_code}")
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
        print(f"[SESSION INFO ERROR] {e}")
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
            try: players = json.loads(players)
            except: players = []

        if player_id in players:
            return jsonify({"status": "error", "message": "Déjà dans la session"}), 400
        if len(players) >= 5:
            return jsonify({"status": "error", "message": "La session est pleine (max 5 joueurs)"}), 400

        players.append(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
        print(f"[JOIN] {player_id} a rejoint {code}.")

        # Note: La réponse doit inclure "players" pour correspondre à votre format d'origine
        return jsonify({"status": "success", "message": f"{player_id} a rejoint la session", "players": players}), 200
    except Exception as e:
        print(f"[JOIN ERROR] {e}")
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
            try: players = json.loads(players)
            except: players = []
            
        if player_id not in players:
            return jsonify({"status": "error", "message": "Vous n’êtes pas dans cette session"}), 400

        players.remove(player_id)
        
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
        
        new_personal_code = ""
        existing_personal = supabase.table("Sessions").select("Code").eq("Creator", player_id).execute()
        
        if existing_personal.data:
            new_personal_code = existing_personal.data[0]["Code"]
            
        print(f"[LEAVE] {player_id} a quitté {code}.")
        
        return jsonify({
            "status": "success", 
            "message": f"{player_id} a quitté la session", 
            "players": players,
            "personal_session_code": new_personal_code 
        }), 200
    except Exception as e:
        print(f"[LEAVE ERROR] {e}")
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
            session_code = session.get("Code")
            players_raw = session.get("Players") or []
            
            if isinstance(players_raw, str):
                try: players = json.loads(players_raw)
                except: players = [players_raw]
            else: players = players_raw
            
            if username in players:
                players.remove(username)
                supabase.table("Sessions").update({"Players": players}).eq("Code", session_code).execute()
            
        print(f"[LOGOUT] {username} déconnecté et retiré des sessions.")
        return jsonify({"status": "success", "message": f"{username} est offline et retiré des sessions"}), 200
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- POIRE CLICK (CORRIGÉ POUR ÉVITER L'ERREUR 500 SQL) ---
@app.route("/poire", methods=["POST"])
def poire():
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    click = (data.get("click") or 0)
    player_id = (data.get("id") or "").strip() 
    
    if not session_code or not player_id:
        return jsonify({"status": "error", "message": "Session ou ID joueur manquant"}), 400
    
    try:
        # LECTURE DE LA VALEUR ACTUELLE (CORRIGE L'ERREUR 500)
        response = supabase.table("Sessions").select("*").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]
        by_click = session.get("By_Click", 1)
        poires2add = by_click * int(click)
        current_poires = session.get("poires", 0)

        new_total = current_poires + poires2add
        
        # ÉCRITURE DE LA NOUVELLE VALEUR NUMÉRIQUE (CORRIGE L'ERREUR SQL)
        supabase.table("Sessions").update({"poires": new_total}).eq("Code", session_code).execute()
        # Mise à jour du click (conservé si nécessaire par votre client)
        # Note: 'Click' n'existe pas par défaut dans la table Sessions, vérifiez si cette ligne est nécessaire.
        # supabase.table("Sessions").update({"Click": click}).eq("Code", session_code).execute()
        
        # Récupération de la valeur finale (pour plus de précision)
        new_total_response = supabase.table("Sessions").select("poires").eq("Code", session_code).execute()
        new_total_final = new_total_response.data[0].get("poires", new_total) if new_total_response.data else new_total

        print(f"[POIRE] {player_id} a ajouté {poires2add} poires à la session {session_code}. Total: {new_total_final}")
        return jsonify({"status": "success", "added": poires2add, "poires": new_total_final}), 200
    except Exception as e:
        print(f"[POIRE ERROR] {e}")
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
        print(f"[GET POIRES ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- VERIFY PLAYER IN SESSION (CORRECTION DU 404) ---
# Le nom de la route est changé pour correspondre à la requête client que vous utilisez
@app.route("/verify_player_in_session", methods=["GET"]) 
def verify_player_in_session():
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
            try: players = json.loads(players_raw)
            except: players = [players_raw]
        else: players = players_raw
        
        # Vérifie si le joueur est effectivement dans la session (créateur ou joueur)
        is_in_session = (username == creator) or (username in players)

        if not is_in_session:
            return jsonify({"status": "error", "message": "Joueur non membre de cette session"}), 403

        # Si l'utilisateur est le créateur, retourne la liste des joueurs (excluant lui-même)
        if username == creator:
            # Note: Si le créateur n'est pas dans la liste 'Players', on l'ajoute temporairement pour la vérification
            other_players = [p for p in players if p != creator]
            return jsonify({"status": "success", "player": other_players, "creator": creator}), 200
        # Si l'utilisateur est un joueur, retourne le nom du créateur
        else:
            return jsonify({"status": "success", "player": creator, "creator": creator}), 200
            
    except Exception as e:
        print(f"[VERIFY PLAYER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- CREATE SESSION ---
@app.route("/create", methods=["POST"])
def create_session():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    
    if not player_id:
        return jsonify({"status": "error", "message": "ID utilisateur manquant"}), 400

    try:
        # Vérification si le joueur est créateur d'une session ou joueur dans une autre session
        creator_session = supabase.table("Sessions").select("Code").eq("Creator", player_id).execute()
        
        if creator_session.data:
            current_session_code = creator_session.data[0]["Code"]
            return jsonify({
                "status": "error", 
                "message": f"Vous êtes déjà créateur de la session '{current_session_code}'.",
                "session_name": current_session_code
            }), 409

        player_in_other_session = supabase.table("Sessions").select("Code, Players").execute()
        for session in player_in_other_session.data or []:
            players_raw = session.get("Players") or []
            players = []
            if isinstance(players_raw, str):
                try: players = json.loads(players_raw)
                except: players = []
            else: players = players_raw
            
            if player_id in players:
                current_session_code = session.get("Code")
                return jsonify({
                    "status": "error", 
                    "message": f"Vous êtes déjà joueur dans la session '{current_session_code}'.",
                    "session_name": current_session_code
                }), 409

        session_code = generate_session_code()
        
        new_session_data = {
            "Code": session_code,
            "Creator": player_id,
            "Players": [],
            "poires": 0,
            "By_Click": 1, 
        }

        supabase.table("Sessions").insert(new_session_data).execute()
        print(f"[CREATE] Nouvelle session {session_code} créée par {player_id}")
        
        return jsonify({"status": "success", "session_name": session_code}), 201
        
    except Exception as e:
        print(f"[CREATE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# --- VERIFY SESSION ---
@app.route("/verify_session", methods=["GET"])
def verify_session():
    player_id = request.args.get("id", "").strip()
    if not player_id:
        return jsonify({"status": "error", "message": "ID manquant"}), 400
    try:
        final_session = None
        
        creator_session_response = supabase.table("Sessions").select("*").eq("Creator", player_id).limit(1).execute()
        if creator_session_response.data:
            final_session = creator_session_response.data[0]
        else:
            player_session_response = supabase.table("Sessions").select("*").execute()
            for session in player_session_response.data or []:
                players_raw = session.get("Players") or []
                if isinstance(players_raw, str):
                    try: players = json.loads(players_raw)
                    except: players = []
                else: players = players_raw
                
                if player_id in players:
                    final_session = session
                    break
                    
        if final_session:
            final_players_raw = final_session.get("Players") or []
            if isinstance(final_players_raw, str):
                try: final_players = json.loads(final_players_raw)
                except: final_players = []
            else: final_players = final_players_raw

            print(f"[VERIFY] {player_id} trouvé dans la session {final_session.get('Code')}")
            return jsonify({
                "status": "success",
                "session_code": final_session.get("Code"),
                "creator": final_session.get("Creator"),
                "players": final_players 
            }), 200
            
        print(f"[VERIFY] {player_id} non trouvé dans aucune session.")
        return jsonify({"status": "error", "message": "Joueur non trouvé dans aucune session"}), 404
    except Exception as e:
        print(f"[VERIFY ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- CHANGE SESSION (Correction du 404/CORS) ---
@app.route("/change_session", methods=["POST"])
def change_session():
    # Cette route appelle simplement la logique de join_session
    return join_session() 

# ----------------------------------------------------------------------
# --- DÉMARRAGE DU SERVEUR ---
# ----------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur démarré sur le port {port}")
    app.run(host="0.0.0.0", port=port)
