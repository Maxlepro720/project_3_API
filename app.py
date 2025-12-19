from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
import json
from flask_cors import CORS
import threading
import time
from datetime import datetime, timedelta, timezone

# --- CONSTANTES DE LENGTH LIMIT ---
MAX_SESSION_CODE_LENGTH = 14
MAX_PLAYERS_PER_SESSION = 5 
# ---------------------------------
# --- VALEURS PAR DÉFAUT (À DÉFINIR AU SOMMET DE VOTRE FICHIER PYTHON) ---
DEFAULT_GRADE = "Poussière"
DEFAULT_SCORE = 0
DEFAULT_CREDIT = 0

app = Flask(__name__)
CORS(app, origins=["https://clickerbutmultiplayer.xo.je"])

# ------------------------------------
# 🔥 CORS FIX GLOBAL POUR TOUTES ROUTES
# ------------------------------------
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = 'https://clickerbutmultiplayer.xo.je'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    response = jsonify({'status': 'OK'})
    response.headers['Access-Control-Allow-Origin'] = 'https://clickerbutmultiplayer.xo.je'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response, 200

# NOTE : Assurez-vous que ces variables d'environnement sont bien définies
# Les variables d'environnement sont nécessaires pour que Supabase fonctionne.
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Variables d'environnement SUPABASE_URL ou SUPABASE_KEY manquantes")

# Initialisation du client Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Nom de votre table de sauvegarde Skull Arena
TABLE_NAME_Skull_Arena = "Skull_Arena_DataBase"
# Nom de votre table de sauvegarde Astro Dodge
TABLE_NAME_ASTRO_DODGE = "Astro_Dodge"
TABLE_NAME_STICKMAN_RUNNER = "Stickman_Runner"

# ----------------------------------------------------------------------
# --- UTILITIES ---
# ----------------------------------------------------------------------

def generate_session_code(length=5):
    """Génère un code de session aléatoire de la longueur spécifiée."""
    if length > MAX_SESSION_CODE_LENGTH:
        length = MAX_SESSION_CODE_LENGTH
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(length))
# ----------------------------------------------------------------------
# --- UTILITIES SUPPLÉMENTAIRES ---
# ----------------------------------------------------------------------
def build_cors_preflight_response():
    response = app.make_response("")
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
    return response

def initialize_upgrades_json(upgrades_raw):
    """
    Transforme les données d'upgrades en dictionnaire utilisable.
    Si la donnée est None ou invalide, retourne un dictionnaire vide.
    Chaque upgrade doit avoir au moins "bought" et "multiplier".
    """
    if not upgrades_raw:
        return {}
    
    if isinstance(upgrades_raw, str):
        try:
            upgrades = json.loads(upgrades_raw)
        except json.JSONDecodeError:
            upgrades = {}
    elif isinstance(upgrades_raw, dict):
        upgrades = upgrades_raw
    else:
        upgrades = {}

    # Assurer la structure minimale pour chaque upgrade
    for key, val in upgrades.items():
        if not isinstance(val, dict):
            upgrades[key] = {"bought": 0, "multiplier": 1.15}
        else:
            upgrades[key].setdefault("bought", 0)
            upgrades[key].setdefault("multiplier", 1.15)

    return upgrades

def get_players_list(session_data):
    """Gère la désérialisation de la liste de joueurs de Supabase."""
    players_raw = session_data.get("Players")
    if isinstance(players_raw, str):
        try:
            return json.loads(players_raw) if players_raw.strip() else []
        except json.JSONDecodeError:
            return []
    elif isinstance(players_raw, list):
        return players_raw
    return []

def rename_session_logic(player_id, old_code, new_code):
    """Logique pour renommer une session si l'utilisateur est le créateur."""
    # 1. Vérification des paramètres
    if not old_code or not new_code or not player_id:
        return {"status": "error", "message": "Paramètres manquants"}, 400
    
    # 2. Vérification si le nom change
    new_code = new_code.strip()[:MAX_SESSION_CODE_LENGTH] 
    if old_code == new_code:
        return {"status": "error", "message": "Le nouveau code est identique au code actuel."}, 409

    # 3. Vérification que le joueur est bien le créateur de la session 'old_code'
    current_session_query = supabase.table("Sessions") \
        .select("Code, Creator") \
        .eq("Code", old_code) \
        .eq("Creator", player_id) \
        .execute()
        
    if not current_session_query.data:
        return {"status": "error", "message": "Session non trouvée ou vous n'êtes pas le créateur."}, 403

    # 4. Vérification de l'unicité du nouveau code
    check_new_code_query = supabase.table("Sessions") \
        .select("Code") \
        .eq("Code", new_code) \
        .execute()
        
    if check_new_code_query.data:
        return {"status": "error", "message": f"Ce nom de session '{new_code}' est déjà utilisé."}, 409

    # 5. Mettre à jour le code de la session
    try:
        supabase.table("Sessions") \
            .update({"Code": new_code}) \
            .eq("Code", old_code) \
            .eq("Creator", player_id) \
            .execute()
        
        print(f"[RENAME] Session {old_code} renommée en {new_code} par {player_id}")
        return {
            "status": "success", 
            "message": f"Session renommée en '{new_code}'",
            "new_code": new_code
        }, 200
    except Exception as e:
        print(f"[RENAME ERROR] {e}")
        return {"status": "error", "message": str(e)}, 500

# ----------------------------------------------------------------------
# --- HOOK DE MISE À JOUR D'ACTIVITÉ (S'exécute avant chaque requête) ---
# ----------------------------------------------------------------------
@app.before_request
def update_last_seen():
    """Met à jour le statut du joueur à 'online'."""
    player_id = None
    
    try:
        if request.method in ["POST", "PUT"]:
            data = request.get_json(silent=True)
            if data:
                player_id = (data.get("id") or data.get("player_id") or data.get("username"))
        elif request.method == "GET":
            player_id = (request.args.get("id") or request.args.get("user") or request.args.get("username"))
            
        if player_id:
            player_id = player_id.strip() 
            if player_id:
                supabase.table("Player").update({
                    "Status": "🟢 online" 
                }).eq("ID", player_id).execute()
                
    except Exception:
        pass

# ----------------------------------------------------------------------
# --- TÂCHE D'ARRIÈRE-PLAN POUR LA VÉRIFICATION D'INACTIVITÉ ---
# ----------------------------------------------------------------------
def check_player_activity():
    """Vérifie périodiquement les joueurs inactifs."""
    print("[SCHEDULER] Le vérificateur d'activité est démarré.")
    while True:
        try:
            # Cette fonction pourrait être développée pour mettre les joueurs offline après N secondes d'inactivité
            pass 
        except Exception as e:
            print(f"[SCHEDULER_ERROR] Erreur lors de la vérification d'activité: {e}")
        time.sleep(10)

# ----------------------------------------------------------------------
# --- ROUTES FLASK ---
# ----------------------------------------------------------------------

@app.route("/")
def home():
    return "Serveur Flask en ligne"

## --- AUTHENTIFICATION ---

@app.route("/signup", methods=["POST", "OPTIONS"])
def signup():
    if request.method == "OPTIONS":
        return build_cors_preflight_response()

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
        "personnel_upgrade": 1.0
    }).execute()
    print(f"[SIGNUP] {username} créé")

    response = jsonify({"status": "success", "message": f"Utilisateur {username} ajouté"})
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response, 201


@app.route("/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS":
        return build_cors_preflight_response()

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
    if not existing_session.data:
        session_code = generate_session_code()
        supabase.table("Sessions").insert({
            "Code": session_code, 
            "Creator": username, 
            "Players": [],  
            "poires": 0, 
            "By_Click": 1.0
        }).execute()
        print(f"[LOGIN] Session personnelle {session_code} créée pour {username}")
    else:
        session_code = existing_session.data[0]["Code"]
        session_data = supabase.table("Sessions").select("Players").eq("Code", session_code).limit(1).execute().data[0]
        players = get_players_list(session_data)
        if username in players:
            players.remove(username)
            supabase.table("Sessions").update({"Players": players}).eq("Code", session_code).execute()
            print(f"[LOGIN] {username} retiré de la liste de joueurs de sa session personnelle")

    print(f"[LOGIN] {username} connecté.")
    response = jsonify({"status": "success", "message": f"Connexion réussie pour {username}"})
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response, 200

@app.route("/logout", methods=["POST", "OPTIONS"])
def logout():
    if request.method == "OPTIONS":
        return build_cors_preflight_response()

    data = request.get_json(force=True)
    username = (data.get("id") or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "ID manquant"}), 400
    try:
        user = supabase.table("Player").select("*").eq("ID", username).execute()
        if not user.data:
            return jsonify({"status": "error", "message": "Utilisateur introuvable"}), 404

        supabase.table("Player").update({"Status": "🔴 offline"}).eq("ID", username).execute()
        response = supabase.table("Sessions").select("Code, Players").execute()
        for session in response.data or []:
            session_code = session.get("Code")
            players = get_players_list(session)
            if username in players:
                players.remove(username)
                supabase.table("Sessions").update({"Players": players}).eq("Code", session_code).execute()

        print(f"[LOGOUT] {username} déconnecté")
        response = jsonify({"status": "success", "message": f"{username} est offline et retiré des sessions"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response, 200
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


## --- GESTION DE SESSION ---

@app.route("/create", methods=["POST", "OPTIONS"])
def create_session():
    if request.method == "OPTIONS":
        return build_cors_preflight_response()

    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    if not player_id:
        return jsonify({"status": "error", "message": "ID utilisateur manquant"}), 400

    try:
        existing_session_response = supabase.table("Sessions").select("Code").eq("Creator", player_id).limit(1).execute()
        if existing_session_response.data:
            session_code = existing_session_response.data[0]["Code"]
            print(f"[CREATE] Session personnelle existante pour {player_id}: {session_code}")
            response = jsonify({
                "status": "success", 
                "message": "Session personnelle existante chargée.",
                "session_name": session_code
            })
            response.headers.add("Access-Control-Allow-Origin", "*")
            return response, 200

        session_code = generate_session_code(length=5)
        new_session_data = {
            "Code": session_code,
            "Creator": player_id,
            "Players": [],
            "poires": 0,
            "By_Click": 1.0
        }
        supabase.table("Sessions").insert(new_session_data).execute()
        print(f"[CREATE] Nouvelle session {session_code} créée par {player_id}")
        response = jsonify({"status": "success", "session_name": session_code})
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response, 201
    except Exception as e:
        print(f"[CREATE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
        players = get_players_list(session)
        creator = session.get("Creator")
        
        if player_id == creator:
            return jsonify({"status": "error", "message": "Vous êtes le créateur de cette session."}), 400
        if player_id in players:
            return jsonify({"status": "error", "message": "Déjà dans la session"}), 400
        if len(players) >= MAX_PLAYERS_PER_SESSION:
            return jsonify({"status": "error", "message": f"La session est pleine (max {MAX_PLAYERS_PER_SESSION} joueurs)"}), 400
            
        all_sessions = supabase.table("Sessions").select("Code, Players, Creator").execute().data or []
        for s in all_sessions:
            if s.get("Creator") == player_id or s.get("Code") == code: 
                continue 
            
            current_players = get_players_list(s)
            if player_id in current_players:
                current_players.remove(player_id)
                supabase.table("Sessions").update({"Players": current_players}).eq("Code", s.get("Code")).execute()
                print(f"[JOIN CLEANUP] {player_id} retiré de l'ancienne session {s.get('Code')}.")
        
        players.append(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
        print(f"[JOIN] {player_id} a rejoint {code}.")

        return jsonify({"status": "success", "message": f"{player_id} a rejoint la session", "players": players}), 200
    except Exception as e:
        print(f"[JOIN ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
        players = get_players_list(session)
        creator = session.get("Creator")

        if player_id == creator:
            return jsonify({"status": "error", "message": "Le créateur ne peut pas quitter sa propre session, il doit la fermer ou se déconnecter."}), 403
            
        if player_id not in players:
            return jsonify({"status": "error", "message": "Vous n’êtes pas dans cette session"}), 400
        
        # 1. Retirer le joueur de la session de groupe
        players.remove(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
        print(f"[LEAVE] {player_id} a quitté {code}.")
        
        # 2. Récupérer le code de sa session personnelle 
        personal_session_response = supabase.table("Sessions").select("Code").eq("Creator", player_id).limit(1).execute()
        new_personal_code = personal_session_response.data[0]["Code"] if personal_session_response.data else None
        
        return jsonify({
            "status": "success", 
            "message": f"{player_id} a quitté la session", 
            "players": players, 
            "personal_session_code": new_personal_code
        }), 200
    except Exception as e:
        print(f"[LEAVE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/change_session", methods=["POST"])
def change_session_route():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    old_code = (data.get("old_code") or "").strip() 
    new_code = (data.get("new_code") or "").strip() 

    result, status_code = rename_session_logic(player_id, old_code, new_code)
    return jsonify(result), status_code

## --- NOUVELLES ROUTES D'AMÉLIORATION (COÛT DYNAMIQUE) ---

@app.route("/get_session_multiplier", methods=["GET"])
def get_session_multiplier():
    """Récupère le multiplicateur By_Click (float) d'une session."""
    session_code = request.args.get("session", "").strip()
    
    if not session_code:
        return jsonify({"status": "error", "message": "Code de session manquant"}), 400
        
    try:
        response = supabase.table("Sessions").select("By_Click").eq("Code", session_code).execute()
        
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404
            
        # S'assure de renvoyer une valeur float
        multiplier = float(response.data[0].get("By_Click", 1.0))
        
        return jsonify({"status": "success", "session_code": session_code, "by_click_multiplier": multiplier}), 200
        
    except Exception as e:
        print(f"[GET SESSION MULTI ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/get_personnel_boost", methods=["GET"])
def get_personnel_boost():
    """Récupère le boost personnel (float) d'un joueur."""
    player_id = request.args.get("id", "").strip()
    
    if not player_id:
        return jsonify({"status": "error", "message": "ID joueur manquant"}), 400
        
    try:
        response = supabase.table("Player").select("personnel_upgrade").eq("ID", player_id).execute()
        
        if not response.data:
            return jsonify({"status": "error", "message": "Joueur introuvable"}), 404
            
        # S'assure de renvoyer une valeur float
        boost = float(response.data[0].get("personnel_upgrade", 1.0))
        
        return jsonify({"status": "success", "player_id": player_id, "personnel_boost": boost}), 200
        
    except Exception as e:
        print(f"[GET PERSONAL BOOST ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ----------------------------------------------------------------------
# --- ROUTES D'AMÉLIORATION (COÛT DYNAMIQUE) CORRIGÉES ---
# ----------------------------------------------------------------------

from decimal import Decimal
from flask import request, jsonify

# ------------------- ROUTE UPGRADES PRICE -------------------
# ------------------- ROUTE UPGRADES PRICE -------------------
# ------------------- ROUTE UPGRADE PRICE / BY_CLICK -------------------
@app.route("/upgrades_price", methods=["POST"])
def upgrades_price():
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    base_prices = data.get("base_prices") or {}

    if not session_code or not base_prices:
        return jsonify({"status": "error", "message": "Paramètres manquants"}), 400

    try:
        # Récupérer upgrades stockés pour la session
        response = supabase.table("Sessions").select("upgrades").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        upgrades = response.data[0].get("upgrades") or {}
        prices = {}
        MAX_BOUGHT = 10000

        # Calcul des prix
        for name, info in upgrades.items():
            bought = min(info.get("bought", 0), MAX_BOUGHT)
            multiplier = float(info.get("multiplier", 1.15))
            base_price = float(base_prices.get(name, 100))
            prices[name] = round(base_price * (multiplier ** bought), 2)

        # Calcul By_Click : add puis multiply
        by_click = 1.0
        for name, info in upgrades.items():
            if info.get("type") == "add":
                by_click += info.get("boost", 0) * info.get("bought", 0)
        for name, info in upgrades.items():
            if info.get("type") == "multiply":
                boost = info.get("boost", 1)
                bought = info.get("bought", 0)
                by_click = by_click * (boost ** bought) if by_click > 0 else boost ** bought

        # S'assurer que by_click >= 1
        by_click = max(by_click, 1.0)

        # Mise à jour en base
        supabase.table("Sessions").update({"By_Click": by_click}).eq("Code", session_code).execute()

        return jsonify({"status": "success", "upgrades_price": prices, "by_click": by_click}), 200

    except Exception as e:
        print(f"[ERROR upgrades_price] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500




# ------------------- ROUTE UPGRADE MULTIPLY -------------------
@app.route("/upgrade_multiply", methods=["POST"])
def upgrade_multiply_session():
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    upgrade_name = (data.get("upgrade_name") or "").strip()
    price = data.get("price")
    quantity = data.get("quantity")

    if not session_code or price is None or quantity is None or not upgrade_name:
        return jsonify({"status": "error", "message": "Paramètres manquants"}), 400

    try:
        price = float(price)
        quantity = int(quantity)
        TOTAL_COST = price * quantity

        response = supabase.table("Sessions").select("poires, upgrades").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session_data = response.data[0]
        current_poires = float(session_data.get("poires", 0))
        upgrades = initialize_upgrades_json(session_data.get("upgrades"))

        if current_poires < TOTAL_COST:
            return jsonify({"status": "error", "message": f"Fonds insuffisants. Coût: {TOTAL_COST}"}), 400

        # Mise à jour du nombre acheté
        upgrades[upgrade_name]["bought"] += quantity
        new_poires = current_poires - TOTAL_COST

        supabase.table("Sessions").update({
            "poires": int(round(new_poires)),
            "upgrades": upgrades
        }).eq("Code", session_code).execute()

        return jsonify({"status": "success", "upgrades": upgrades, "poires": new_poires}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ------------------- ROUTE UPGRADE ADD -------------------
@app.route("/upgrade_add", methods=["POST"])
def upgrade_add_session():
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    upgrade_name = (data.get("upgrade_name") or "").strip()
    price = data.get("price")
    quantity = data.get("quantity")

    if not session_code or price is None or quantity is None or not upgrade_name:
        return jsonify({"status": "error", "message": "Paramètres manquants"}), 400

    try:
        price = float(price)
        quantity = int(quantity)
        TOTAL_COST = price * quantity

        response = supabase.table("Sessions").select("poires, upgrades").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session_data = response.data[0]
        current_poires = float(session_data.get("poires", 0))
        upgrades = initialize_upgrades_json(session_data.get("upgrades"))

        if current_poires < TOTAL_COST:
            return jsonify({"status": "error", "message": f"Fonds insuffisants. Coût: {TOTAL_COST}"}), 400

        # Mise à jour du nombre acheté
        upgrades[upgrade_name]["bought"] += quantity
        new_poires = current_poires - TOTAL_COST

        supabase.table("Sessions").update({
            "poires": int(round(new_poires)),
            "upgrades": upgrades
        }).eq("Code", session_code).execute()

        return jsonify({"status": "success", "upgrades": upgrades, "poires": new_poires}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/personnel_boost", methods=["POST"])
def personnel_boost():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    boost_value = data.get("boost")
    price = data.get("price")
    quantity = data.get("quantity")

    if not player_id or boost_value is None or price is None or quantity is None:
        return jsonify({"status": "error", "message": "Paramètres manquants"}), 400

    try:
        boost_value = float(boost_value)
        price = float(price)
        quantity = int(quantity)
        TOTAL_COST = price * quantity

        session_response = supabase.table("Sessions").select("Code, poires").eq("Creator", player_id).limit(1).execute()
        if session_response.data:
            final_session = session_response.data[0]
        else:
            all_sessions = supabase.table("Sessions").select("Code, Players, poires").execute().data or []
            final_session = next((s for s in all_sessions if player_id in get_players_list(s)), None)

        if not final_session:
            return jsonify({"status": "error", "message": "Joueur non trouvé dans session active"}), 404

        session_code = final_session.get("Code")
        current_poires = float(final_session.get("poires", 0))

        if current_poires < TOTAL_COST:
            return jsonify({"status": "error", "message": f"Fonds insuffisants. Coût: {TOTAL_COST}"}), 400

        player_response = supabase.table("Player").select("personnel_upgrade").eq("ID", player_id).execute()
        current_boost = float(player_response.data[0].get("personnel_upgrade", 1.0)) if player_response.data else 1.0

        new_boost = current_boost + boost_value * quantity
        new_poires = current_poires - TOTAL_COST

        supabase.table("Player").update({"personnel_upgrade": new_boost}).eq("ID", player_id).execute()
        supabase.table("Sessions").update({"poires": int(round(new_poires))}).eq("Code", session_code).execute()

        return jsonify({"status": "success", "new_personal_boost": new_boost, "session_poires": new_poires}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



## --- INFORMATIONS & DONNÉES ---

@app.route("/verify_session", methods=["GET"])
def verify_session():
    player_id = request.args.get("id", "").strip()
    if not player_id:
        return jsonify({"status": "error", "message": "ID manquant"}), 400

    try:
        final_session = None

        # --- 1) Vérifier d'abord si le joueur est JOUEUR dans une session ---
        all_sessions = supabase.table("Sessions").select("*").execute()

        for session in all_sessions.data or []:
            players = get_players_list(session)
            if player_id in players:
                final_session = session
                break

        # --- 2) Si aucune session trouvée en tant que joueur → vérifier s'il est CREATEUR ---
        if not final_session:
            creator_query = supabase.table("Sessions") \
                .select("*") \
                .eq("Creator", player_id) \
                .limit(1) \
                .execute()
            if creator_query.data:
                final_session = creator_query.data[0]

        # --- 3) Si aucune session trouvée du tout ---
        if not final_session:
            print(f"[VERIFY] {player_id} non trouvé dans aucune session.")
            return jsonify({"status": "error", "message": "Joueur non trouvé dans aucune session"}), 404

        # --- 4) Construire la liste finale des joueurs ---
        final_players = get_players_list(final_session)
        creator = final_session.get("Creator")

        # Ajouter le créateur dans la liste des joueurs
        if creator not in final_players:
            final_players.append(creator)

        return jsonify({
            "status": "success",
            "session_code": final_session.get("Code"),
            "creator": creator,
            "players": final_players
        }), 200

    except Exception as e:
        print(f"[VERIFY ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



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
        creator = session.get("Creator")
        players_in_db = get_players_list(session)
        
        unique_active_players = set(players_in_db)
        unique_active_players.add(creator)
        
        if username not in unique_active_players:
            return jsonify({"status": "error", "message": "Joueur non membre de cette session"}), 403

        return jsonify({
            "status": "success",
            "session_code": session_code,
            "creator": creator,
            "players": list(unique_active_players) 
        }), 200
    except Exception as e:
        print(f"[VERIFY PLAYER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/poire", methods=["POST"])
def poire():
    """
    Calcule et met à jour le score (entier) en utilisant les boosts (float).
    poires2add = round(click * Session.By_Click * Player.personnel_upgrade)
    """
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    click = (data.get("click") or 0)
    player_id = (data.get("id") or "").strip() 
    
    if not session_code or not player_id:
        return jsonify({"status": "error", "message": "Session, Click ou ID joueur manquant"}), 400
        
    try:
        click = int(click)
        
        # 1. Récupérer By_Click (float) de la session
        session_response = supabase.table("Sessions").select("poires, By_Click").eq("Code", session_code).execute()
        if not session_response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session_data = session_response.data[0]
        current_poires = session_data.get("poires", 0)
        session_by_click = float(session_data.get("By_Click", 1.0))
        
        # 2. Récupérer personnel_upgrade (float) du joueur
        player_response = supabase.table("Player").select("personnel_upgrade").eq("ID", player_id).execute()
        if not player_response.data:
             player_boost = 1.0
        else:
             player_boost = float(player_response.data[0].get("personnel_upgrade", 1.0))

        # 3. Calculer les poires à ajouter (float intermédiaire)
        raw_poires_to_add = click * session_by_click * player_boost
        
        # 4. ARRONDISSEMENT du score à l'entier le plus proche
        poires2add = int(round(raw_poires_to_add))
        
        # 5. Mise à jour de la nouvelle valeur via fonction stockée, fallback si échec
        try:
            supabase.rpc("add_poires", {"val": poires2add, "session_code": session_code}).execute()
            new_total = current_poires + poires2add
        except Exception as e:
            # fallback update classique
            new_total = current_poires + poires2add
            supabase.table("Sessions").update({"poires": new_total}).eq("Code", session_code).execute()

        print(f"[POIRE] {player_id} a ajouté {poires2add} poires à la session {session_code}. Total: {new_total}.")
        return jsonify({"status": "success", "added": poires2add, "poires": new_total}), 200
    except ValueError:
        return jsonify({"status": "error", "message": "La valeur 'click' doit être un nombre entier."}), 400
    except Exception as e:
        print(f"[POIRE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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

#------------------------------------------------
#SKULL     ARENA 
#------------------------------------------------

@app.route('/skull_arena_update_data', methods=['POST'])
def skull_arena_update_data():
    """
    [Skull_Arena_ServerSave] Met à jour les données du joueur (crânes, meilleure vague, niveaux d'amélioration).
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400

    try:
        new_best_vague = int(data.get('best_wave', 0))
        
        # 1. Fetcher la meilleure vague actuelle pour ne pas l'écraser
        current_data_query = supabase.table(TABLE_NAME_Skull_Arena).select('"Best_Vague"').eq('username', username).limit(1).execute()
        current_data = current_data_query.data[0] if current_data_query.data else None
        
        current_best_vague = current_data.get('Best_Vague', 0) if current_data else 0
        final_best_vague = max(current_best_vague, new_best_vague)
        
        # 2. Préparer le payload avec les niveaux et les crânes
        payload = {
            "username": username,
            "Best_Vague": final_best_vague, 
            "Crane": int(data.get('skulls', 0)),
            "UP_Degat": int(data.get('up_damage', 0)),
            "UP_Portée": int(data.get('up_range', 0)),
            "UP_Vitesse": int(data.get('up_speed', 0)),
            "UP_Cadence": int(data.get('up_fire', 0))
        }
        
        # 3. Effectuer l'UPSERT
        response = supabase.table(TABLE_NAME_Skull_Arena).upsert(payload, on_conflict="username").execute()
        
        if response.data:
             return jsonify({"status": "success", "message": "Sauvegarde Skull Arena réussie"}), 200
        else:
             return jsonify({"status": "error", "message": "Échec de l'UPSERT Skull Arena"}), 500

    except Exception as e:
        print(f"[SAVE SKULL ARENA ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ------------------- ROUTE DE CHARGEMENT -------------------
@app.route('/skull_arena_get_data', methods=['POST'])
def skull_arena_get_data():
    """
    [Skull_Arena_ServerLoad] Récupère les données d'un joueur, ou retourne les valeurs par défaut.
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400

    try:
        columns = '"Crane", "Best_Vague", "UP_Degat", "UP_Portée", "UP_Vitesse", "UP_Cadence"'
        response = supabase.table(TABLE_NAME_Skull_Arena).select(columns).eq('username', username).limit(1).execute()
        
        if not response.data:
            # Réponse d'initialisation pour un nouveau joueur
            return jsonify({
                "status": "not_found", 
                "message": "Données Skull Arena introuvables. Initialisation...",
                "data": {
                    "skulls": 0,
                    "best_wave": 0,
                    "levels": {"damage": 0, "range": 0, "speed": 0, "fire": 0}
                }
            }), 200 


        row = response.data[0]
        
        # Mappe et renvoie les données
        return jsonify({
            "status": "success",
            "message": "Données Skull Arena chargées",
            "data": {
                "skulls": int(row.get('Crane', 0)),
                "best_wave": int(row.get('Best_Vague', 0)),
                "levels": {
                    "damage": int(row.get('UP_Degat', 0)),
                    "range": int(row.get('UP_Portée', 0)),
                    "speed": int(row.get('UP_Vitesse', 0)),
                    "fire": int(row.get('UP_Cadence', 0))
                }
            }
        }), 200

    except Exception as e:
        print(f"[LOAD SKULL ARENA ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/skull_arena_get_leaderboard', methods=['GET'])
def skull_arena_get_leaderboard():
    """
    Récupère les 10 meilleurs scores (Best_Vague) du classement global.
    """
    try:
        # Requête Supabase:
        # 1. Sélectionne 'username' et 'Best_Vague'
        # 2. Trie par 'Best_Vague' en ordre décroissant (DESC)
        # 3. Limite les résultats aux 10 premiers (LIMIT 10)
        response = supabase.table(TABLE_NAME_Skull_Arena) \
            .select("username, Best_Vague") \
            .order("Best_Vague", desc=True) \
            .limit(10) \
            .execute()
        
        # Le format de données de Supabase est une liste de dictionnaires:
        # [{'username': 'Name1', 'Best_Vague': 1000}, ...]
        
        # Mappage pour correspondre au format attendu par le client JS
        formatted_data = []
        for row in response.data:
            formatted_data.append({
                "name": row.get('username'),
                "wave": int(row.get('Best_Vague', 0)) # Assurer que c'est un entier
            })

        return jsonify({
            "status": "success",
            "message": "Classement global chargé.",
            "data": formatted_data
        }), 200

    except Exception as e:
        print(f"[LOAD LEADERBOARD ERROR] {e}")
        return jsonify({
            "status": "error", 
            "message": "Échec de la récupération du classement: " + str(e)
        }), 500

# ----------------------------------------------------------------------
# --- ROUTES ASTRO DODGE (Sauvegarde & Score) ---
# ----------------------------------------------------------------------

@app.route('/astro/save_data', methods=['POST'])
def save_astro_data():
    """
    Sauvegarde ou met à jour les données du joueur (Score, Pièces, Voitures débloquées).
    Voiture: stocke la chaîne des noms de voitures débloquées (ex: "Standard,Rapide,Titan").
    """
    if request.method == 'OPTIONS':
        return build_cors_preflight_response()
    
    data = request.get_json(silent=True)
    if not data or 'username' not in data:
        return jsonify({"status": "error", "message": "Nom d'utilisateur manquant."}), 400

    username = data['username'].strip()
    
    update_data = {}
    
    new_score = data.get('PR_Score')
    new_coins = data.get('Coins')
    # Le champ Voiture doit contenir la CHAÎNE COMPLÈTE des voitures débloquées.
    unlocked_cars_string = data.get('Voiture') 
    
    # 1. Tenter de récupérer les données actuelles
    try:
        current_data_query = supabase.table(TABLE_NAME_ASTRO_DODGE)\
            .select("PR_Score, Coins")\
            .eq("username", username)\
            .execute()
        
        current_data = current_data_query.data[0] if current_data_query.data else None
        
        # 2. Logique de mise à jour du Score (High Score)
        if new_score is not None:
            new_score = int(new_score)
            current_score = current_data['PR_Score'] if current_data and current_data['PR_Score'] is not None else 0
            
            # Mise à jour du score seulement s'il est meilleur, ou si c'est une nouvelle entrée
            if new_score > current_score or current_data is None:
                update_data["PR_Score"] = new_score
                if current_data is None:
                    print(f"[ASTRO] Nouvel utilisateur créé avec score: {new_score}")
                else:
                    print(f"[ASTRO] Nouveau PR Score pour {username}: {new_score}")


        # 3. Logique de mise à jour des Pièces (total)
        if new_coins is not None:
             update_data["Coins"] = int(new_coins)
        
        # 4. Mise à jour des Voitures débloquées (si fournie)
        # On enregistre la chaîne de caractères telle qu'envoyée par le client
        if unlocked_cars_string is not None:
            update_data["Voiture"] = str(unlocked_cars_string)

        # 5. Effectuer l'opération d'upsert (insert ou update)
        if current_data is None:
            # Insertion (création de l'utilisateur)
            insert_data = {"username": username, **update_data}
            
            # Assurer les valeurs par défaut
            insert_data.setdefault("PR_Score", 0) 
            insert_data.setdefault("Coins", 0)
            # Par défaut, seule la "Standard" est débloquée
            insert_data.setdefault("Voiture", "Standard") 
            
            supabase.table(TABLE_NAME_ASTRO_DODGE).insert([insert_data]).execute()
            message = "Nouvel utilisateur Astro Dodge créé et données sauvegardées."
        elif update_data:
            # Mise à jour (si au moins une donnée a changé)
            supabase.table(TABLE_NAME_ASTRO_DODGE)\
                .update(update_data)\
                .eq("username", username)\
                .execute()
            message = "Données Astro Dodge mises à jour."
        else:
            message = "Aucune donnée à mettre à jour."
            return jsonify({"status": "success", "message": message}), 200

        return jsonify({"status": "success", "message": message, "updated_data": update_data}), 200

    except Exception as e:
        print(f"[ASTRO SAVE ERROR] {e}")
        return jsonify({"status": "error", "message": f"Erreur de base de données lors de la sauvegarde: {str(e)}"}), 500

@app.route('/astro/load_data/<username>', methods=['GET'])
def load_astro_data(username):
    """
    Charge les données de sauvegarde du joueur Astro Dodge.
    """
    if request.method == 'OPTIONS':
        return build_cors_preflight_response()
    
    if not username:
        return jsonify({"status": "error", "message": "Nom d'utilisateur manquant."}), 400

    username = username.strip()

    try:
        # Récupère toutes les colonnes pour l'utilisateur
        result = supabase.table(TABLE_NAME_ASTRO_DODGE)\
            .select("*")\
            .eq("username", username)\
            .single()\
            .execute()
            
        data = result.data

        return jsonify({"status": "success", "data": data}), 200

    except Exception:
        # Si single() échoue, c'est probablement parce que l'utilisateur n'existe pas.
        # On retourne un profil par défaut.
        default_data = {
            "username": username,
            "PR_Score": 0,
            "Coins": 0,
            # Correction: Par défaut, seule la voiture "Standard" est débloquée
            "Voiture": "Standard" 
        }
        return jsonify({"status": "not_found", "message": "Utilisateur non trouvé, profil par défaut retourné.", "data": default_data}), 200


@app.route('/astro/leaderboard', methods=['GET'])
def get_astro_leaderboard():
    """
    Calcule et retourne le tableau des scores (Leaderboard) basé sur le PR_Score.
    CORRECTION: Limité au TOP 5.
    """
    if request.method == 'OPTIONS':
        return build_cors_preflight_response()
    
    try:
        # CORRECTION APPLIQUÉE: Limiter au top 5
        result = supabase.table(TABLE_NAME_ASTRO_DODGE)\
            .select("username, PR_Score")\
            .order("PR_Score", desc=True)\
            .limit(5)\
            .execute()
            
        leaderboard = result.data

        return jsonify({"status": "success", "leaderboard": leaderboard}), 200

    except Exception as e:
        print(f"[ASTRO LEADERBOARD ERROR] {e}")
        return jsonify({"status": "error", "message": f"Erreur lors de la récupération du classement: {str(e)}"}), 500

@app.route(f"/{TABLE_NAME_STICKMAN_RUNNER}/load_data/<username>", methods=['GET', 'OPTIONS'])
def load_stickman_runner_data(username):
    if request.method == 'OPTIONS':
        # Gestion du CORS preflight
        return options_handler(f"/{TABLE_NAME_STICKMAN_RUNNER}/load_data/{username}") 

    try:
        # Tenter de charger l'utilisateur
        result = supabase.table(TABLE_NAME_STICKMAN_RUNNER).select("*").eq("username", username).limit(1).execute()
        user_data = result.data[0] if result.data else None

        if not user_data:
            # Si non trouvé, créer l'utilisateur (UPSERT)
            new_user_data = {
                "username": username,
                "best_score": DEFAULT_SCORE,
                "credit": DEFAULT_CREDIT,
                "grade": DEFAULT_GRADE
            }
            supabase.table(TABLE_NAME_STICKMAN_RUNNER).insert(new_user_data).execute()
            user_data = new_user_data # Retourner les données par défaut

        data_to_return = {
            "username": user_data.get("username"),
            "best_score": user_data.get("best_score", DEFAULT_SCORE),
            "credit": user_data.get("credit", DEFAULT_CREDIT),
            "grade": user_data.get("grade")
        }

        response = jsonify({"status": "success", "data": data_to_return})
        return response, 200

    except Exception as e:
        print(f"[LOAD_DATA ERROR] {e}")
        return jsonify({"status": "error", "message": f"Server Error during load: {str(e)}"}), 500


# 2. SAVE (Sauvegarde des données)
@app.route(f"/{TABLE_NAME_STICKMAN_RUNNER}/save_data", methods=['POST', 'OPTIONS'])
def save_stickman_runner_data():
    if request.method == 'OPTIONS':
        return options_handler(f"/{TABLE_NAME_STICKMAN_RUNNER}/save_data")

    try:
        data = request.get_json(force=True)
        username = (data.get('username') or "").strip()
        new_best_score = int(data.get('best_score', 0))
        new_credit = int(data.get('credit', 0))
        new_grade = (data.get('grade') or DEFAULT_GRADE).strip()

        if not username:
            return jsonify({"status": "error", "message": "Username missing"}), 400

        # 1. Charger les données existantes pour vérifier le score
        current_data_result = supabase.table(TABLE_NAME_STICKMAN_RUNNER).select("best_score").eq("username", username).limit(1).execute()
        
        if not current_data_result.data:
            return jsonify({"status": "error", "message": "User not found"}), 404
        
        current_best_score = current_data_result.data[0].get("best_score", 0)

        update_payload = {
            "credit": new_credit,
            "grade": new_grade,
        }
        
        # Mettre à jour le best_score seulement si le nouveau est meilleur
        if new_best_score > current_best_score:
            update_payload["best_score"] = new_best_score
            
        # 2. Effectuer la mise à jour
        supabase.table(TABLE_NAME_STICKMAN_RUNNER).update(update_payload).eq("username", username).execute()

        response = jsonify({"status": "success", "message": "Data updated"})
        return response, 200

    except Exception as e:
        print(f"[SAVE_DATA ERROR] {e}")
        return jsonify({"status": "error", "message": f"Server Error during save: {str(e)}"}), 500


# 3. LEADERBOARD (Classement)
@app.route(f"/{TABLE_NAME_STICKMAN_RUNNER}/leaderboard", methods=['GET', 'OPTIONS'])
def get_stickman_runner_leaderboard():
    if request.method == 'OPTIONS':
        return options_handler(f"/{TABLE_NAME_STICKMAN_RUNNER}/leaderboard")
    
    try:
        # Récupère le top 10 par best_score décroissant
        result = supabase.table(TABLE_NAME_STICKMAN_RUNNER) \
            .select("username, best_score, grade") \
            .order("best_score", desc=True) \
            .limit(10) \
            .execute()
            
        leaderboard_data = result.data or []

        response = jsonify({
            "status": "success",
            "leaderboard": leaderboard_data
        })
        return response, 200

    except Exception as e:
        print(f"[LEADERBOARD ERROR] {e}")
        return jsonify({"status": "error", "message": f"Server Error during leaderboard: {str(e)}"}), 500
# ----------------------------------------------------------------------
# --- DÉMARRAGE DU SERVEUR ---
# ----------------------------------------------------------------------
if __name__ == "__main__":
    activity_thread = threading.Thread(target=check_player_activity, daemon=True)
    activity_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur démarré sur le port {port}")
    app.run(host="0.0.0.0", port=port)
