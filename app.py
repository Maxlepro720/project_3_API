from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from flask_cors import CORS
from decimal import Decimal # Conservé, peut être utile si des décimaux sont nécessaires plus tard
import uuid
from supabase import PostgrestAPIError
import chess

# ---------------------------------
# --- VALEURS PAR DÉFAUT (À DÉFINIR AU SOMMET DE VOTRE FICHIER PYTHON) ---
DEFAULT_GRADE = "Poussière"
DEFAULT_SCORE = 0
DEFAULT_CREDIT = 0

app = Flask(__name__)
# J'ai conservé l'origine CORS spécifique de votre code initial
CORS(app, origins=["*"])

# ------------------------------------
# 🔥 CORS FIX GLOBAL POUR TOUTES ROUTES
# ------------------------------------
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'  # toutes origines
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/<path:path>', methods=['OPTIONS'])
def options_handler(path):
    response = jsonify({'status': 'OK'})
    response.headers['Access-Control-Allow-Origin'] = '*'  # toutes origines
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response, 200

# NOTE : Assurez-vous que ces variables d'environnement sont bien définies
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Variables d'environnement SUPABASE_URL ou SUPABASE_KEY manquantes")

# Initialisation du client Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Nom de vos tables de sauvegarde (CORRIGÉ pour correspondre EXACTEMENT au schéma)
# J'ai conservé vos noms de variables, mais je les utilise maintenant
# avec les noms exacts de votre schéma
TABLE_NAME_Player = "Player" # Ajouté pour clarté
TABLE_NAME_Skull_Arena = "Skull_Arena_DataBase"
TABLE_NAME_ASTRO_DODGE = "Astro_Dodge"
TABLE_NAME_STICKMAN_RUNNER = "Stickman_Runner"
TABLE_NAME_CHESS = "chess"

INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# ----------------------------------------------------------------------
# --- UTILITIES ---
# ----------------------------------------------------------------------
def build_cors_preflight_response():
    response = app.make_response("")
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
    return response

# ----------------------------------------------------------------------
# --- HOOK DE MISE À JOUR D'ACTIVITÉ (S'exécute avant chaque requête) ---
# ----------------------------------------------------------------------
@app.before_request
def update_last_seen():
    """Met à jour le statut du joueur à 'online' et l'horodatage Last_Seen."""

    admin_routes = ['/get_all_players_status', '/get_all_ban', '/do_ban', '/remove_sanction', '/get_ban']
        
    if request.path in admin_routes:
        return

    if request.args.get('admin') == 'true':
        return
        
    player_id = None
    
    try:
        if request.method in ["POST", "PUT"]:
            data = request.get_json(silent=True) 
            if data:
                player_id = (data.get("id") or data.get("player_id") or data.get("username"))
                
        elif request.method == "GET":
            player_id = (request.args.get("id") or request.args.get("user") or request.args.get("username"))
            
    except Exception as e:
        print(f"[Alerte Request Parsing] Erreur lors de l'analyse de la requête: {e}")
        return
        
    if player_id:
        player_id = str(player_id).strip()
        
        if player_id:
            try:
                # Écrit Status et last_seen dans la table Player.
                # Noms de colonnes : "Status", "last_seen" (minuscules dans le schéma)
                # Le nom de la colonne d'ID est "ID"
                supabase.table(TABLE_NAME_Player).update({ 
                    "Status": "🟢 online", 
                    "last_seen": datetime.now(timezone.utc).isoformat() 
                }).eq("ID", player_id).execute()
                
            except Exception as e:
                # C'est important pour les logs, mais cela ne doit pas bloquer la requête
                print(f"=========================================================")
                print(f"[ERREUR Last_Seen] Échec de la mise à jour pour ID: {player_id}")
                print(f"Détail de l'erreur Supabase: {e}")
                print(f"=========================================================")
# ----------------------------------------------------------------------
# --- TÂCHE D'ARRIÈRE-PLAN POUR LA VÉRIFICATION D'INACTIVITÉ ---
# ----------------------------------------------------------------------
@app.before_request
def check_player_activity():
    try:
        
        inactivity_limit = datetime.now(timezone.utc) - timedelta(seconds=15)
        inactivity_limit_iso = inactivity_limit.isoformat()

        # Met tous les joueurs 'online' qui n'ont pas bougé depuis 15s à 'offline'
        # Noms de colonnes : "last_seen", "Status" (conformes au schéma Player)
        supabase.table(TABLE_NAME_Player).update({
            "Status": "🔴 offline"
        }).lt(
            "last_seen", inactivity_limit_iso
        ).eq(
            "Status", "🟢 online"
        ).execute()
    except Exception as e:
        print(f"Erreur inattendue dans le thread d'activité: {e}")
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

    # Table Player, Colonne ID
    existing = supabase.table(TABLE_NAME_Player).select("*").eq("ID", username).execute()
    if existing.data:
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    hashed_pw = generate_password_hash(password)
    
    # Insertion dans la table Player. Colonnes : "ID", "Password", "Status"
    supabase.table(TABLE_NAME_Player).insert({
        "ID": username, 
        "Password": hashed_pw, 
        "Status": "🔴 offline"
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

    # Table Player. Colonne ID, Colonne Password
    user = supabase.table(TABLE_NAME_Player).select("Password").eq("ID", username).execute()
    if not user.data:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    user_data = user.data[0]
    if not check_password_hash(user_data["Password"], password):
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

    # Logique de connexion simple conservée
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
        # Table Player. Colonne ID
        user = supabase.table(TABLE_NAME_Player).select("*").eq("ID", username).execute()
        if not user.data:
            return jsonify({"status": "error", "message": "Utilisateur introuvable"}), 404

        # Met à jour le statut à offline. Colonnes : "Status", "ID"
        supabase.table(TABLE_NAME_Player).update({"Status": "🔴 offline"}).eq("ID", username).execute()
        
        print(f"[LOGOUT] {username} déconnecté")
        response = jsonify({"status": "success", "message": f"{username} est offline"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response, 200
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

#-------------------------------------------------
#  Route stay alive(laisse server eveiller)
#-------------------------------------------------
@app.route('/stay_alive', methods=['GET'])
def stay_alive():
    return jsonify({"status": "Server is alive", "message": "Keep-alive successful"}), 200

#     gestion amitié ----------------------------------------------

@app.route('/friends_control', methods=['POST'])
def friends_control():
    data = request.get_json(force=True)
    action_to_do = (data.get('action') or "").strip()
    username = (data.get('username') or "").strip()
    personne = (data.get('personne') or "").strip()
    if not action_to_do:
        return jsonify({"status": "error", "message": "action manquant"}), 400
    if not username:
        return jsonify({"status": "error", "message": "Nom d'utilisateur manquant"}), 400
    try:
        if action_to_do == 'get_friends_list':
            response = supabase.table('Player') \
                .select('friends') \
                .eq('ID', username) \
                .execute()

            result = response.data
            friends_list = []
            if result and len(result) > 0:
                friends_list = result[0].get('friends', [])
                
            return jsonify({"status": "success", "friends": friends_list }), 200
            
    
    except Exception as e:
        print(f"erreur dans route friends_control {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        


# ------------------------------------------------
# SKULL ARENA (ROUTES DE GESTION DE JEU)
# ------------------------------------------------
@app.route('/skull_arena_update_data', methods=['POST'])
def skull_arena_update_data():
    """ [Skull_Arena_ServerSave] Met à jour les données du joueur (crânes, meilleure vague, niveaux d'amélioration).
    Table : Skull_Arena_DataBase, Colonnes : username, "Best_Vague", "Crane", "UP_Degat", "UP_Portée", "UP_Vitesse", "UP_Cadence"
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        new_best_vague = int(data.get('best_wave', 0))
        
        # 1. Fetcher la meilleure vague actuelle pour ne pas l'écraser (COLONNE CORRIGÉE : "Best_Vague")
        current_data_query = supabase.table(TABLE_NAME_Skull_Arena).select('"Best_Vague"').eq('username', username).limit(1).execute()
        current_data = current_data_query.data[0] if current_data_query.data else None
        current_best_vague = current_data.get('Best_Vague', 0) if current_data else 0
        final_best_vague = max(current_best_vague, new_best_vague)
        
        # 2. Préparer le payload (COLONNES CORRIGÉES : "Best_Vague", "Crane", "UP_Degat", "UP_Portée", "UP_Vitesse", "UP_Cadence")
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

@app.route('/skull_arena_get_data', methods=['POST'])
def skull_arena_get_data():
    """ [Skull_Arena_ServerLoad] Récupère les données d'un joueur.
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        # COLONNES CORRIGÉES : Noms exacts de la table Skull_Arena_DataBase
        columns = '"Crane", "Best_Vague", "UP_Degat", "UP_Portée", "UP_Vitesse", "UP_Cadence"'
        response = supabase.table(TABLE_NAME_Skull_Arena).select(columns).eq('username', username).limit(1).execute()
        
        if not response.data:
            return jsonify({
                "status": "not_found", 
                "message": "Données Skull Arena introuvables. Initialisation...",
                "data": {"skulls": 0, "best_wave": 0, "levels": {"damage": 0, "range": 0, "speed": 0, "fire": 0}}
            }), 200
        
        row = response.data[0]
        # CLÉS DE RÉPONSE CORRIGÉES
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
    """ Récupère les 10 meilleurs scores (Best_Vague) du classement global.
    """
    try:
        # COLONNE CORRIGÉE : "Best_Vague"
        response = supabase.table(TABLE_NAME_Skull_Arena) \
            .select("username, Best_Vague") \
            .order("Best_Vague", desc=True) \
            .limit(10) \
            .execute()
            
        formatted_data = []
        for row in response.data:
            formatted_data.append({
                "name": row.get('username'),
                "wave": int(row.get('Best_Vague', 0)) # CLÉ DE RÉPONSE CORRIGÉE
            })

        return jsonify({
            "status": "success", 
            "message": "Classement global Skull Arena chargé.", 
            "data": formatted_data
        }), 200
        
    except Exception as e:
        print(f"[LEADERBOARD SKULL ARENA ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------------------------------------------
# ASTRO DODGE (ROUTES DE GESTION DE JEU)
# ------------------------------------------------
@app.route('/astro_dodge_update_data', methods=['POST'])
def astro_dodge_update_data():
    """ [Astro_Dodge_ServerSave] Met à jour le meilleur score, le crédit et les vaisseaux débloqués du joueur.
    Table : Astro_Dodge, Colonnes : username, "PR_Score", "Coins", "Voiture"
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        new_score = int(data.get('score', 0))
        # CORRECTION 3: Récupération de la chaîne de voitures
        new_voiture_string = (data.get('Voiture') or "Standard").strip()
        
        # 1. Fetcher le meilleur score actuel (la logique de comparaison reste intacte)
        current_data_query = supabase.table(TABLE_NAME_ASTRO_DODGE).select('"PR_Score"').eq('username', username).limit(1).execute()
        current_data = current_data_query.data[0] if current_data_query.data else None
        current_best_score = current_data.get('PR_Score', 0) if current_data else 0
        final_best_score = max(current_best_score, new_score)
        
        # 2. Préparer le payload
        payload = {
            "username": username,
            "PR_Score": final_best_score,
            "Coins": int(data.get('credit', 0)),
            # CORRECTION 4: Ajout de la clé "Voiture" au payload de l'upsert
            "Voiture": new_voiture_string 
        }
        
        # 3. Effectuer l'UPSERT
        response = supabase.table(TABLE_NAME_ASTRO_DODGE).upsert(payload, on_conflict="username").execute()
        if response.data:
            return jsonify({"status": "success", "message": "Sauvegarde Astro Dodge réussie"}), 200
        else:
            return jsonify({"status": "error", "message": "Échec de l'UPSERT Astro Dodge"}), 500
    except Exception as e:
        print(f"[SAVE ASTRO DODGE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/astro_dodge_get_data', methods=['POST'])
def astro_dodge_get_data():
    """ [Astro_Dodge_ServerLoad] Récupère les données d'un joueur, y compris les vaisseaux débloqués.
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        # CORRECTION 1: Ajout de "Voiture" à la sélection des colonnes
        columns = '"PR_Score", "Coins", "Voiture"' 
        response = supabase.table(TABLE_NAME_ASTRO_DODGE).select(columns).eq('username', username).limit(1).execute()
        
        if not response.data:
            return jsonify({
                "status": "not_found", 
                "message": "Données Astro Dodge introuvables. Initialisation...",
                # J'initialise 'Voiture' ici aussi, par sécurité, même si le client a un fallback
                "data": {"score": 0, "credit": 0, "Voiture": "Standard"} 
            }), 200
            
        row = response.data[0]
        # CLÉS DE RÉPONSE CORRIGÉES
        return jsonify({
            "status": "success", 
            "message": "Données Astro Dodge chargées",
            "data": {
                "score": int(row.get('PR_Score', 0)),
                "credit": int(row.get('Coins', 0)),
                # CORRECTION 2: Ajout de la clé "Voiture" dans la réponse
                "Voiture": row.get('Voiture', 'Standard') 
            }
        }), 200
    except Exception as e:
        print(f"[LOAD ASTRO DODGE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/astro_dodge_get_leaderboard', methods=['GET'])
def astro_dodge_get_leaderboard():
    """ Récupère les 10 meilleurs scores ("PR_Score") du classement global.
    """
    try:
        # COLONNE CORRIGÉE : "PR_Score"
        response = supabase.table(TABLE_NAME_ASTRO_DODGE) \
            .select("username, PR_Score") \
            .order("PR_Score", desc=True) \
            .limit(10) \
            .execute()
            
        formatted_data = []
        for row in response.data:
            formatted_data.append({
                "name": row.get('username'),
                "score": int(row.get('PR_Score', 0)) # CLÉ DE RÉPONSE CORRIGÉE
            })

        return jsonify({
            "status": "success", 
            "message": "Classement global Astro Dodge chargé.", 
            "data": formatted_data
        }), 200
        
    except Exception as e:
        print(f"[LEADERBOARD ASTRO DODGE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------------------------------------------
# STICKMAN RUNNER (ROUTES DE GESTION DE JEU)
# ------------------------------------------------
@app.route('/stickman_runner_update_data', methods=['POST'])
def stickman_runner_update_data():
    """ [Stickman_Runner_ServerSave] Met à jour la meilleure distance, le crédit et le grade du joueur.
    Table : Stickman_Runner, Colonnes : username, best_score, credit, grade
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        # CORRECTION 1 : Le client envoie 'best_score', pas 'distance'.
        new_distance = int(data.get('best_score', 0)) 
        new_credit = int(data.get('credit', 0))
        # CORRECTION 2 : Récupérer le grade envoyé par le client (string)
        new_grade = (data.get('grade') or "").strip()

        # 1. Fetcher la meilleure distance actuelle
        current_data_query = supabase.table(TABLE_NAME_STICKMAN_RUNNER).select('best_score').eq('username', username).limit(1).execute()
        current_data = current_data_query.data[0] if current_data_query.data else None
        current_best_distance = current_data.get('best_score', 0) if current_data else 0
        final_best_distance = max(current_best_distance, new_distance)

        # 2. Préparer le payload (Ajout de 'grade')
        payload = {
            "username": username,
            "best_score": final_best_distance,
            "credit": new_credit, 
            "grade": new_grade # NOUVEAU : Sauvegarde du grade
        }
        
        # 3. Effectuer l'UPSERT
        response = supabase.table(TABLE_NAME_STICKMAN_RUNNER).upsert(payload, on_conflict="username").execute()
        
        if response.data:
            return jsonify({"status": "success", "message": "Sauvegarde Stickman Runner réussie"}), 200
        else:
            return jsonify({"status": "error", "message": "Échec de l'UPSERT Stickman Runner"}), 500
            
    except Exception as e:
        print(f"[SAVE STICKMAN RUNNER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/stickman_runner_get_data', methods=['POST'])
def stickman_runner_get_data():
    """ [Stickman_Runner_ServerLoad] Récupère les données d'un joueur.
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        # COLONNES CORRIGÉES : best_score, credit
        columns = 'best_score, credit, grade'
        response = supabase.table(TABLE_NAME_STICKMAN_RUNNER).select(columns).eq('username', username).limit(1).execute()

        if not response.data:
            return jsonify({
                "status": "not_found", 
                "message": "Données Stickman Runner introuvables. Initialisation...",
                "data": {"distance": 0, "credit": 0}
            }), 200

        row = response.data[0]
        # CLÉS DE RÉPONSE CORRIGÉES
        return jsonify({
            "status": "success", 
            "message": "Données stickman Runner chargées",
            "data": {
                "distance": int(row.get('best_score', 0)), # CORRIGÉ (votre schéma a 'best_score')
                "credit": int(row.get('credit', 0)), # CORRIGÉ (votre schéma a 'credit')
                "grade": row.get('grade','')
            }
        }), 200

    except Exception as e:
        print(f"[LOAD STICKMAN RUNNER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stickman_runner_get_leaderboard', methods=['GET'])
def stickman_runner_get_leaderboard():
    """ Récupère les 10 meilleures distances (best_score) et le grade du classement global.
    """
    try:
        # COLONNE CORRIGÉE : best_score, et AJOUT de 'grade'
        response = supabase.table(TABLE_NAME_STICKMAN_RUNNER) \
            .select("username, best_score, grade") \
            .order("best_score", desc=True) \
            .limit(10) \
            .execute()
            
        formatted_data = []
        for row in response.data:
            formatted_data.append({
                "name": row.get('username'),
                "distance": int(row.get('best_score', 0)), # CLÉ DE RÉPONSE CORRIGÉE
                "grade": row.get('grade') # AJOUT DE LA COLONNE 'grade'
            })

        return jsonify({
            "status": "success", 
            "message": "Classement global Stickman Runner chargé.", 
            "data": formatted_data
        }), 200
        
    except Exception as e:
        print(f"[LEADERBOARD STICKMAN RUNNER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
#----------------------------------
#--------------chess game----------
#----------------------------------
# 1. Matchmaking : Trouve ou crée une partie
# 1. Matchmaking : Trouve ou crée une partie
@app.route("/find_or_create_match", methods=["POST"])
def find_or_create_match():
    # --- CORRECTION DE L'AUTHENTIFICATION ---
    data = request.get_json(silent=True) or {}
    player_id = (data.get("username") or "").strip() 
    # ----------------------------------------

    if not player_id:
        return jsonify({"error": "Pseudo manquant dans la requête. Connexion requise."}), 401

    try:
        # 1. Chercher une partie en attente (où black_player_id est NULL)
        open_games = supabase.table(TABLE_NAME_CHESS) \
            .select("uuid, fen_state, white_player_id") \
            .is_("black_player_id", "null") \
            .neq("white_player_id", player_id) \
            .limit(1) \
            .execute()

        if open_games.data:
            # 2. Partie trouvée : Rejoindre en tant que Noir
            game_data = open_games.data[0]
            game_uuid = game_data['uuid']
            white_id = game_data['white_player_id']
            
            # Mise à jour de la partie (Retrait de la tentative de mise à jour de 'game_status')
            supabase.table(TABLE_NAME_CHESS) \
                .update({"black_player_id": player_id, "joueurs": f"{white_id},{player_id}"}) \
                .eq("uuid", game_uuid) \
                .execute()
                
            return jsonify({
                "status": "joined",
                "game_uuid": game_uuid,
                "player_color": "black",
                "fen": game_data['fen_state'],
                "opponent_id": white_id
            })

        else:
            # 3. Aucune partie ouverte : Créer une nouvelle partie en tant que Blanc
            new_game_uuid = str(uuid.uuid4())
            
            new_game = {
                "uuid": new_game_uuid,
                "fen_state": INITIAL_FEN,
                "white_player_id": player_id,
                "black_player_id": None, 
                "joueurs": player_id, 
                "moves_list": [] 
            }
            
            supabase.table(TABLE_NAME_CHESS).insert(new_game).execute()
            
            return jsonify({
                "status": "created",
                "game_uuid": new_game_uuid,
                "player_color": "white",
                "fen": INITIAL_FEN,
                "opponent_id": None
            })

    except PostgrestAPIError as e:
        print(f"Erreur Supabase lors du matchmaking: {e}")
        return jsonify({"error": f"Erreur Supabase: {e.message}"}), 500
    except Exception as e:
        print(f"Erreur inattendue lors du matchmaking: {e}")
        return jsonify({"error": "Erreur interne du serveur."}), 500

# 2. Envoyer Coup (Make Move)
# 2. Envoyer Coup (Make Move)
@app.route("/make_move", methods=["POST"])
def make_move():
    data = request.get_json(silent=True) or {}
    game_uuid = data.get("game_uuid")
    move_uci = data.get("move_uci") # Format UCI: 'e2e4', 'a7a8q', etc.
    
    # --- CORRECTION DE L'AUTHENTIFICATION ---
    player_id = (data.get("username") or "").strip() 
    # ----------------------------------------

    if not all([game_uuid, move_uci, player_id]):
        return jsonify({"error": "Données de mouvement ou identifiant de joueur manquant."}), 400

    try:
        # 1. Récupérer l'état actuel de la partie
        result = supabase.table(TABLE_NAME_CHESS) \
            .select("fen_state, white_player_id, black_player_id, moves_list") \
            .eq("uuid", game_uuid) \
            .single() \
            .execute()
            
        game_data = result.data
        current_fen = game_data['fen_state']
        moves_list = game_data.get('moves_list') if isinstance(game_data.get('moves_list'), list) else [] 

        # 2. Créer l'objet plateau 'python-chess'
        board = chess.Board(current_fen)
        
        # Vérifier si c'est le tour du joueur
        expected_player = game_data['white_player_id'] if board.turn == chess.WHITE else game_data['black_player_id']
        if expected_player != player_id:
            return jsonify({"error": "Ce n'est pas votre tour de jouer."}), 403

        # 3. Valider et effectuer le mouvement
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            return jsonify({"error": f"Coup UCI invalide: {move_uci}"}), 400

        if move not in board.legal_moves:
            return jsonify({"error": "Coup illégal."}), 400

        board.push(move)
        new_fen = board.fen()
        moves_list.append(move_uci)
        
        # 4. Déterminer le statut (pour la réponse client, pas pour la DB)
        game_status = "active"
        if board.is_checkmate():
            game_status = "checkmate"
        elif board.is_stalemate() or board.is_fivefold_repetition() or board.is_insufficient_material() or board.is_seventyfive_moves():
            game_status = "draw"

        update_data = {
            "fen_state": new_fen,
            "moves_list": moves_list,
            # game_status est retiré de la mise à jour DB
        }
        
        supabase.table(TABLE_NAME_CHESS).update(update_data).eq("uuid", game_uuid).execute()
        
        return jsonify({
            "success": True, 
            "new_fen": new_fen,
            "game_status": game_status # On renvoie le statut au client pour la gestion locale
        }), 200

    except PostgrestAPIError as e:
        print(f"Erreur Supabase lors de la gestion du coup: {e}")
        return jsonify({"error": f"Erreur Supabase: {e.message}"}), 500
    except Exception as e:
        print(f"Erreur inattendue lors du coup: {e}")
        return jsonify({"error": "Erreur interne du serveur."}), 500

# 3. Demander Coups de la Partie (Historique)
# NOTE : Cette route est un GET, elle n'avait pas besoin de correction d'authentification par cookies.
@app.route("/get_moves/<game_uuid>", methods=["GET"])
def get_moves(game_uuid):
    """
    Récupère la liste complète des coups joués pour une partie donnée.
    """
    try:
        result = supabase.table(TABLE_NAME_CHESS) \
            .select("moves_list") \
            .eq("uuid", game_uuid) \
            .single() \
            .execute()
            
        moves = result.data.get("moves_list", [])

        return jsonify({
            "game_uuid": game_uuid,
            "moves": moves
        })

    except PostgrestAPIError as e:
        if "0 rows" in str(e):
            return jsonify({"error": "Partie non trouvée."}), 404
        print(f"Erreur Supabase lors de la récupération des coups: {e}")
        return jsonify({"error": f"Erreur Supabase: {e.message}"}), 500
    except Exception as e:
        print(f"Erreur inattendue lors de la récupération des coups: {e}")
        return jsonify({"error": "Erreur interne du serveur."}), 500


# 4. Destruction de la Partie
@app.route("/destroy_match", methods=["POST"])
def destroy_match():
    data = request.get_json(silent=True) or {}
    game_uuid = data.get("game_uuid")
    
    # --- CORRECTION DE L'AUTHENTIFICATION ---
    player_id = (data.get("username") or "").strip()
    # ----------------------------------------
    
    if not player_id:
        return jsonify({"error": "Utilisateur non identifié."}), 401
    if not game_uuid:
        return jsonify({"error": "UUID de partie manquant."}), 400

    try:
        # 1. Vérification des droits (seuls les joueurs peuvent supprimer)
        result = supabase.table(TABLE_NAME_CHESS) \
            .select("uuid") \
            .eq("uuid", game_uuid) \
            .or_(f'white_player_id.eq."{player_id}",black_player_id.eq."{player_id}"') \
            .limit(1) \
            .execute()
            
        if not result.data:
            return jsonify({"error": "Partie non trouvée ou non autorisé à la supprimer."}), 403

        # 2. Suppression de la partie
        supabase.table(TABLE_NAME_CHESS) \
            .delete() \
            .eq("uuid", game_uuid) \
            .execute()
        
        return jsonify({"success": True, "message": f"Partie {game_uuid} supprimée."}), 200

    except PostgrestAPIError as e:
        print(f"Erreur Supabase lors de la destruction de partie: {e}")
        return jsonify({"error": f"Erreur Supabase: {e.message}"}), 500
    except Exception as e:
        print(f"Erreur inattendue lors de la destruction: {e}")
        return jsonify({"error": "Erreur interne du serveur."}), 500

# --- NOUVEAU : Récupère l'état d'une partie par son UUID (Pour le polling) ---
# --- NOUVEAU : Récupère l'état d'une partie par son UUID (Pour le polling) ---
@app.route('/get_game_state', methods=['GET', 'OPTIONS'])
def get_game_state():
    # CORS OPTIONS pre-flight
    if request.method == 'OPTIONS':
        return '', 200

    game_uuid = request.args.get('game_uuid')
    
    if not game_uuid:
        return jsonify({"status": "error", "message": "UUID de partie manquant."}), 400

    try:
        # Utilisation de TABLE_NAME_CHESS et sélection des colonnes existantes
        result = supabase.table(TABLE_NAME_CHESS)\
            .select("fen_state, white_player_id, black_player_id")\
            .eq("uuid", game_uuid)\
            .single()\
            .execute()
            
        game_data = result.data
        
        if not game_data:
            return jsonify({"status": "error", "message": "Partie non trouvée."}), 404

        # INFERENCE DU STATUT : La colonne game_status n'existe pas, on déduit le statut.
        # 'active' si l'adversaire (Noir) a rejoint. 'created' sinon.
        inferred_status = 'created'
        opponent_id = game_data.get('black_player_id')
        if opponent_id:
            inferred_status = 'active'
            
        response_data = {
            "status": "success",
            "game_status": inferred_status, # Le client l'utilise pour se débloquer
            "fen": game_data.get('fen_state'), 
            "player_white_id": game_data.get('white_player_id'), 
            "opponent_id": opponent_id 
        }

        return jsonify(response_data), 200

    except PostgrestAPIError as e:
        print(f"[GET GAME STATE ERROR] Supabase error: {e}")
        if "0 rows" in str(e):
             return jsonify({"status": "error", "message": "Partie non trouvée."}), 404
        return jsonify({"status": "error", "message": "Erreur lors de la récupération de l'état du jeu."}), 500
    except Exception as e:
        print(f"[GET GAME STATE ERROR] General error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/give_up_chess', methods=['POST'])
def give_up_chess():
    """
    Permet à un joueur d'abandonner une partie.
    Met à jour la colonne 'abandon' avec la couleur du joueur gagnant.
    """
    try:
        data = request.get_json()
        game_uuid = data.get('game_uuid')
        username = data.get('username')

        if not game_uuid or not username:
            return jsonify({"status": "error", "message": "game_uuid et username sont requis."}), 400

        # 1. Récupérer les données de la partie
        # On vérifie aussi si la partie n'a pas déjà un statut d'abandon
        game_data_response = supabase.table('chess').select('white_player_id, black_player_id, abandon').eq('uuid', game_uuid).single().execute()

        if not game_data_response.data:
            return jsonify({"status": "error", "message": "Partie non trouvée."}), 404
            
        game = game_data_response.data
        
        # 2. Vérifier si la partie est déjà terminée
        if game.get('abandon'):
            # CORRECTION DE LA SYNTAXE PYTHON DANS LA F-STRING
            winner_id = game['black_player_id'] if game.get('abandon') == 'white' else game['white_player_id']
            return jsonify({"status": "error", "message": f"La partie est déjà terminée par abandon du joueur {winner_id}."}), 409

        white_player = game['white_player_id']
        black_player = game['black_player_id']
        
        # 3. Déterminer la couleur du joueur qui abandonne et du gagnant
        if username == white_player:
            winner_color = 'black'
            loser_id = white_player
        elif username == black_player:
            winner_color = 'white'
            loser_id = black_player
        else:
            return jsonify({"status": "error", "message": "L'utilisateur n'est pas un joueur de cette partie."}), 403

        # 4. Mettre à jour la colonne 'abandon' avec la couleur du gagnant
        update_data = {
            'abandon': winner_color,
        }

        update_response = supabase.table('chess').update(update_data).eq('uuid', game_uuid).execute()

        if update_response.data:
            return jsonify({
                "status": "success", 
                "message": f"{loser_id} a abandonné. Le joueur {winner_color} gagne par abandon.",
                "abandon_status": winner_color,
                "winner_color": winner_color,
            }), 200
        else:
            return jsonify({"status": "error", "message": "Erreur lors de la mise à jour de la base de données. Partie non trouvée ou non modifiée."}), 409

    except PostgrestAPIError as e:
        print(f"[GIVE UP ERROR] Supabase error: {e}")
        return jsonify({"status": "error", "message": f"Erreur de base de données: {e.message}"}), 500
    except Exception as e:
        print(f"[GIVE UP ERROR] General error: {e}")
        return jsonify({"status": "error", "message": f"Erreur interne du serveur: {str(e)}"}), 500

@app.route('/get_give_up_chess', methods=['GET'])
def get_give_up_chess():
    """
    Vérifie si un abandon a eu lieu pour une partie donnée.
    """
    try:
        game_uuid = request.args.get('game_uuid')

        if not game_uuid:
            return jsonify({"status": "error", "message": "game_uuid est requis."}), 400

        # Récupérer la valeur de la colonne 'abandon'
        game_data_response = supabase.table('chess').select('abandon').eq('uuid', game_uuid).single().execute()

        if not game_data_response.data:
            return jsonify({"status": "error", "message": "Partie non trouvée."}), 404
            
        abandon_status = game_data_response.data.get('abandon')

        if abandon_status:
            # Si 'abandon' contient une couleur (white ou black), l'abandon a eu lieu.
            return jsonify({
                "status": "abandoned", 
                "winner_color": abandon_status,
                "message": f"La partie est terminée. Le joueur {abandon_status} gagne par abandon."
            }), 200
        else:
            # La colonne est NULL, pas d'abandon.
            return jsonify({
                "status": "active", 
                "message": "La partie est toujours en cours. Aucun abandon détecté."
            }), 200

    except PostgrestAPIError as e:
        print(f"[GET GIVE UP ERROR] Supabase error: {e}")
        return jsonify({"status": "error", "message": f"Erreur de base de données: {e.message}"}), 500
    except Exception as e:
        print(f"[GET GIVE UP ERROR] General error: {e}")
        return jsonify({"status": "error", "message": f"Erreur interne du serveur: {str(e)}"}), 500
        
#------------------------------------------ Jeu de Casino -------------------------------


@app.route('/Casino_update_data', methods=['POST'])
def casino_update_data():
    
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        new_money = int(data.get('money', 0))
        success = data.get('success', {})

        payload = {
            "username": username,
            "money": new_money,
            "success": success 
        }
        
        # 3. Effectuer l'UPSERT
        response = supabase.table("Casino").upsert(payload, on_conflict="username").execute()
        
        if response.data:
            return jsonify({"status": "success", "message": "Sauvegarde Casino réussie"}), 200
        else:
            return jsonify({"status": "error", "message": "Échec de l'UPSERT Casino"}), 500
            
    except Exception as e:
        print(f"[SAVE STICKMAN RUNNER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/Casino_get_data', methods=['POST'])
def casino_get_data():
    
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
    
        columns = 'money, success'
        response = supabase.table("Casino").select(columns).eq('username', username).limit(1).execute()

        if not response.data:
            return jsonify({
                "status": "not_found", 
                "message": "Données Casino introuvables. Initialisation...",
                "data": {"money": 0, "success": {} }
            }), 200

        row = response.data[0]

        return jsonify({
            "status": "success", 
            "message": "Données Casino chargées",
            "data": {
                "money": int(row.get('money', 0)),
                "success": row.get('success', {} )
            }
        }), 200

    except Exception as e:
        print(f"[LOAD Casino ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/gun_merge_update_data', methods=['POST'])
def gun_merge_update_data():

    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    save_data = data.get('save')

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400

    if not save_data:
        return jsonify({"status": "error", "message": "Save manquant"}), 400

    try:

        payload = {
            "username": username,
            "save": save_data
        }

        # UPSERT = crée si existe pas
        response = supabase.table("Gun_Merge")\
            .upsert(payload, on_conflict="username")\
            .execute()

        if response.data:
            return jsonify({
                "status": "success",
                "message": "Save Gun Merge sauvegardé"
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Erreur sauvegarde"
            }), 500

    except Exception as e:
        print(f"[SAVE GUN MERGE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/gun_merge_get_data', methods=['POST'])
def gun_merge_get_data():

    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400

    try:

        response = supabase.table("Gun_Merge")\
            .select("save")\
            .eq("username", username)\
            .limit(1)\
            .execute()

        # Si aucun save → créer ligne automatiquement
        if not response.data:

            default_save = {
                "xp": 0,
                "money": 1,
                "buyPrice": 1,
                "inventory": [None, None, None, None, None],
                "currentLevel": 1
            }

            supabase.table("Gun_Merge").insert({
                "username": username,
                "save": default_save
            }).execute()

            return jsonify({
                "status": "success",
                "data": default_save
            }), 200


        return jsonify({
            "status": "success",
            "data": response.data[0]["save"]
        }), 200


    except Exception as e:
        print(f"[LOAD GUN MERGE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


#-----------------------------------
#------------------gestion admin----
#-----------------------------------


@app.route('/get_all_players_status', methods=['GET', 'OPTIONS'])
def get_all_players_status():
    """
    Récupère tous les joueurs et les trie :
    1. Tous les joueurs "🟢 online".
    2. Tous les joueurs "🔴 offline", triés par 'last_seen' du plus récent au plus ancien.
    """
    if request.method == "OPTIONS":
        return build_cors_preflight_response()

    try:
        # 1. Récupérer tous les joueurs avec les colonnes nécessaires
        # Colonnes de la table Player : ID, Status, last_seen
        response = supabase.table(TABLE_NAME_Player).select("ID, Status, last_seen").execute()
        all_players = response.data

        online_players = []
        offline_players = []

        # 2. Séparer les joueurs en ligne et hors ligne
        for player in all_players:
            player_data = {
                "id": player.get("ID"),
                "status": player.get("Status", "🔴 offline"),
                "last_seen": player.get("last_seen")
            }
            if player_data["status"] == "🟢 online":
                online_players.append(player_data)
            else:
                offline_players.append(player_data)

        # 3. Trier les joueurs hors ligne par 'last_seen' (du plus récent au plus ancien)
        # Convertit la chaîne last_seen en objet datetime pour un tri correct, gère les None
        def sort_key(player):
            last_seen_str = player.get("last_seen")
            if last_seen_str:
                try:
                    # Assurez-vous que le format est correct (Supabase utilise l'ISO 8601)
                    return datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
                except ValueError:
                    return datetime.min.replace(tzinfo=timezone.utc) # Date très ancienne pour les erreurs
            return datetime.min.replace(tzinfo=timezone.utc) # Date très ancienne pour les joueurs sans last_seen

        # Tri inverse (descendant) pour le plus récent d'abord
        offline_players.sort(key=sort_key, reverse=True)

        # 4. Combiner la liste (Online d'abord, puis Offline triés)
        final_list = online_players + offline_players

        # 5. Renvoyer la liste
        response = jsonify({
            "status": "success",
            "message": f"Liste de {len(final_list)} joueurs récupérée.",
            "data": final_list
        })
        # Ajout des headers CORS dans le handler OPTIONS, mais aussi ici pour le GET
        response.headers.add("Access-Control-Allow-Origin", "https://clickerbutmultiplayer.xo.je")
        return response, 200

    except Exception as e:
        print(f"[GET ALL PLAYERS ERROR] {e}")
        response = jsonify({"status": "error", "message": str(e)})
        response.headers.add("Access-Control-Allow-Origin", "https://clickerbutmultiplayer.xo.je")
        return response, 500

#recuperer le counter du nombre de chaque jeux

@app.route('/get_play_counter', methods=['GET'])
def get_play_counter():
    """
    Récupère le nom et le nombre de parties pour chaque jeu.
    Table : Play_Count, Colonnes : name, counter
    """
    try:
        # Récupération des données depuis Supabase
        # On sélectionne uniquement les colonnes nécessaires : 'name' et 'counter'
        response = supabase.table("Play_Count").select("name, counter").execute()

        if not response.data:
            return jsonify({
                "status": "success", 
                "message": "Aucune donnée trouvée.", 
                "data": []
            }), 200

        # Renvoie les données au format JSON
        # Format : [{"name": "jeu1", "counter": 10}, {"name": "jeu2", "counter": 50}]
        return jsonify({
            "status": "success",
            "data": response.data
        }), 200

    except Exception as e:
        print(f"[ERROR Get_Play_Counter] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/add1to_count', methods=['GET'])
def add1to_count():
    """
    Incrémente le compteur d'un jeu de +1.
    Usage : /add1to_count?name=Skull Arena
    """
    game_name = request.args.get('name')
    
    if not game_name:
        return jsonify({"status": "error", "message": "Le paramètre 'name' est requis."}), 400

    try:
        # 1. On récupère la valeur actuelle du compteur pour ce jeu
        response = supabase.table("Play_Count").select("counter").eq("name", game_name).execute()

        if response.data and len(response.data) > 0:
            current_count = response.data[0]['counter'] or 0
            new_count = current_count + 1

            # 2. On met à jour avec la nouvelle valeur
            supabase.table("Play_Count").update({"counter": new_count}).eq("name", game_name).execute()

            return jsonify({
                "status": "success",
                "game": game_name,
                "new_counter": new_count
            }), 200
        else:
            return jsonify({"status": "error", "message": f"Jeu '{game_name}' non trouvé dans la table."}), 404

    except Exception as e:
        print(f"[ERROR add1to_count] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# -------------- gestion des version -------------------

@app.route('/get_latest_version', methods=['GET'])
def get_latest_version():
    """Récupère la dernière mise à jour (version, title, description)"""
    try:
        # On trie par Version descendante et on limite à 1 pour avoir la plus récente
        response = supabase.table("Last_Maj") \
            .select("Version, Title, Description") \
            .order("Version", desc=True) \
            .limit(1) \
            .execute()

        if response.data:
            return jsonify({
                "status": "success",
                "data": response.data[0]
            }), 200
        else:
            return jsonify({"status": "error", "message": "Aucune mise à jour trouvée"}), 404
            
    except Exception as e:
        print(f"[ERROR get_latest_version] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/add_version', methods=['GET'])
def add_version():
    """Crée une nouvelle ligne dans Last_Maj via des paramètres GET"""
    version = request.args.get('version')
    title = request.args.get('title')
    description = request.args.get('description')

    if not version:
        return jsonify({"status": "error", "message": "Le paramètre 'version' est obligatoire"}), 400

    try:
        payload = {
            "Version": int(version),
            "Title": title,
            "Description": description
        }
        
        # Insertion dans la table Supabase [cite: 186, 243]
        response = supabase.table("Last_Maj").insert(payload).execute()
        
        return jsonify({
            "status": "success", 
            "message": "Nouvelle version ajoutée",
            "data": response.data
        }), 201

    except Exception as e:
        print(f"[ERROR add_version] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/get_all_versions', methods=['GET'])
def get_all_versions():
    """Récupère toutes les lignes de la table Last_Maj, triées par version."""
    try:
        # On sélectionne toutes les colonnes et on trie par Version (la plus récente en premier)
        # On utilise le nom exact de la table "Last_Maj" tel que défini dans votre schéma [cite: 116]
        response = supabase.table("Last_Maj").select("*").order("Version", desc=True).execute()

        if not response.data:
            return jsonify({
                "status": "success", 
                "message": "Aucune mise à jour enregistrée.", 
                "data": []
            }), 200

        # Renvoie les données au format JSON, similaire à la gestion des compteurs [cite: 118]
        return jsonify({
            "status": "success",
            "data": response.data
        }), 200

    except Exception as e:
        print(f"[ERROR get_all_versions] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

#--------------- gestion sanctions ---------------------
@app.route('/do_ban', methods=['POST'])
def do_ban():
    data = request.get_json(force=True)
    player_id = (data.get('id') or "").strip()
    
    if not player_id:
        return jsonify({"status": "error", "message": "ID du joueur manquant"}), 400
    
    try:
        # Met à jour la colonne 'Sanction' avec la valeur 'ban'
        response = supabase.table(TABLE_NAME_Player).update({
            "Sanction": "ban"
        }).eq("ID", player_id).execute()
        
        if response.data:
            return jsonify({"status": "success", "message": f"Joueur {player_id} banni"}), 200
        else:
            return jsonify({"status": "error", "message": "Joueur non trouvé"}), 404
            
    except Exception as e:
        print(f"[BAN ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/remove_sanction', methods=['POST'])
def remove_sanction():
    data = request.get_json(force=True)
    player_id = (data.get('id') or "").strip()
    
    if not player_id:
        return jsonify({"status": "error", "message": "ID du joueur manquant"}), 400
    
    try:
        # Retire la sanction en mettant la colonne à None (null dans la DB)
        response = supabase.table(TABLE_NAME_Player).update({
            "Sanction": None
        }).eq("ID", player_id).execute()
        
        if response.data:
            return jsonify({"status": "success", "message": f"Sanction retirée pour {player_id}"}), 200
        else:
            return jsonify({"status": "error", "message": "Joueur non trouvé"}), 404
            
    except Exception as e:
        print(f"[REMOVE SANCTION ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_all_ban', methods=['GET'])
def get_all_ban():
    """
    Récupère la liste de tous les joueurs ayant une sanction active[cite: 106].
    """
    try:
        # On filtre les joueurs dont la colonne Sanction n'est pas vide (is not null)
        response = supabase.table(TABLE_NAME_Player) \
            .select("ID, Sanction") \
            .not_.is_("Sanction", "null") \
            .execute()

        return jsonify({
            "status": "success",
            "count": len(response.data),
            "data": response.data
        }), 200

    except Exception as e:
        print(f"[GET ALL BAN ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_ban', methods=['GET'])
def get_ban():
    """
    Vérifie si un joueur spécifique est banni via son ID[cite: 5].
    """
    player_id = request.args.get('id') 
    
    if not player_id:
        return jsonify({"status": "error", "message": "Le paramètre 'id' est requis."}), 400

    try:
        # On cherche le joueur par son ID [cite: 8, 12]
        response = supabase.table(TABLE_NAME_Player) \
            .select("ID, Sanction") \
            .eq("ID", player_id) \
            .single() \
            .execute()

        if not response.data:
            return jsonify({"status": "error", "message": "Joueur non trouvé."}), 404

        sanction = response.data.get("Sanction")
        is_banned = (sanction == "ban")

        return jsonify({
            "status": "success",
            "player_id": player_id,
            "is_banned": is_banned,
            "sanction_detail": sanction
        }), 200

    except Exception as e:
        print(f"[GET BAN ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
#-------------------------------------- CCCCCAAAAAAASSSSSSIIIIINNNNOOOOOOOO -----------------------


@app.route('/get_casino_data', methods=['GET'])
def get_casino_data():
    username = request.args.get('username')
    
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400

    try:
        response = supabase.table("Casino") \
            .select("money, success") \
            .eq("username", username) \
            .execute()

        # Si l'utilisateur n'existe pas, on le crée
        if not response.data:
            new_data = {
                "username": username,
                "money": 0,
                "success": []
            }

            supabase.table("Casino").insert(new_data).execute()

            return jsonify({
                "status": "success",
                "data": {
                    "money": 0,
                    "success": []
                }
            }), 200

        # Si l'utilisateur existe
        return jsonify({
            "status": "success",
            "data": response.data[0]
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/update_casino_money', methods=['POST'])
def update_casino_money():
    data = request.get_json(force=True)
    username = data.get('username')
    new_money = data.get('money')

    if username is None or new_money is None:
        return jsonify({"status": "error", "message": "Données incomplètes"}), 400

    try:
        response = supabase.table("Casino") \
            .update({"money": new_money}) \
            .eq("username", username) \
            .execute()

        return jsonify({"status": "success", "message": "Argent mis à jour"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/update_casino_success', methods=['POST'])
def update_casino_success():
    data = request.get_json(force=True)
    username = data.get('username')
    new_success = data.get('success') # Doit être un dictionnaire Python/JSON

    if username is None or new_success is None:
        return jsonify({"status": "error", "message": "Données incomplètes"}), 400

    try:
        # Supabase gère la conversion dict -> jsonb automatiquement
        response = supabase.table("Casino") \
            .update({"success": new_success}) \
            .eq("username", username) \
            .execute()

        return jsonify({"status": "success", "message": "Succès mis à jour"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

#----------------gestion de time et des FDPiece --------------------


@app.route('/get_time_FDPrice', methods=['POST'])
def get_time_FDPrice():
    try:
        data = request.get_json(force=True)
        username = (data.get('username') or "").strip()

        if not username:
            return jsonify({"status": "error", "message": "Username manquant"}), 400

        response = supabase.table("FDPiece") \
            .select("Time, FDPiece") \
            .eq("username", username) \
            .limit(1) \
            .execute()

        # Si le joueur n'existe pas → création
        if not response.data:
            init_payload = {
                "username": username,
                "Time": 0,
                "FDPiece": 0
            }
            supabase.table("FDPiece").insert(init_payload).execute()

            return jsonify({
                "status": "created",
                "Time": 0,
                "FDPiece": 0
            }), 200

        row = response.data[0]

        return jsonify({
            "status": "success",
            "Time": int(row.get("Time", 0)),
            "FDPiece": int(row.get("FDPiece", 0))
        }), 200

    except PostgrestAPIError as e:
        print(f"[GET FDPiece ERROR] {e}")
        return jsonify({"status": "error", "message": e.message}), 500
    except Exception as e:
        print(f"[GET FDPiece ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/send_time', methods=['POST'])
def send_time():
    try:
        data = request.get_json(force=True)
        username = (data.get('username') or "").strip()
        time_value = int(data.get('Time', 0))

        if not username:
            return jsonify({"status": "error", "message": "Username manquant"}), 400

        payload = {
            "username": username,
            "Time": time_value
        }

        supabase.table("FDPiece") \
            .upsert(payload, on_conflict="username") \
            .execute()

        return jsonify({"status": "success", "message": "Time sauvegardé"}), 200

    except PostgrestAPIError as e:
        print(f"[SEND TIME ERROR] {e}")
        return jsonify({"status": "error", "message": e.message}), 500
    except Exception as e:
        print(f"[SEND TIME ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/send_FDPrice', methods=['POST'])
def send_FDPrice():
    try:
        data = request.get_json(force=True)
        username = (data.get('username') or "").strip()
        fd_change = int(data.get('FDPiece', 0))  # peut être positif ou négatif

        if not username:
            return jsonify({"status": "error", "message": "Username manquant"}), 400

        # Récupérer la valeur actuelle
        response = supabase.table("FDPiece").select("FDPiece").eq("username", username).single().execute()
        current_fd = 0
        if response.data and "FDPiece" in response.data:
            current_fd = int(response.data["FDPiece"])

        # Vérifier si l'utilisateur a assez de FDPriece pour un achat
        if fd_change < 0 and current_fd < abs(fd_change):
            return jsonify({"status": "error", "message": "FDPiece insuffisant"}), 400

        # Calculer la nouvelle valeur
        new_fd = current_fd + fd_change

        # Mettre à jour dans la table
        payload = {
            "username": username,
            "FDPiece": new_fd
        }
        supabase.table("FDPiece").upsert(payload, on_conflict="username").execute()

        return jsonify({"status": "success", "FDPiece": new_fd, "message": "FDPiece mis à jour"}), 200

    except PostgrestAPIError as e:
        print(f"[SEND FDPrice ERROR] {e}")
        return jsonify({"status": "error", "message": e.message}), 500
    except Exception as e:
        print(f"[SEND FDPrice ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================
# GET Evo Pass
# ==========================
@app.route('/get_evo_pass', methods=['POST'])
def get_evo_pass():
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()

    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400

    try:
        response = supabase.table("FDPiece").select("Pass").eq("username", username).single().execute()
        if not response.data:
            return jsonify({"status": "not_found", "message": "Utilisateur introuvable"}), 404

        pass_value = response.data.get("Pass", 0)
        return jsonify({"status": "success", "Pass": pass_value}), 200

    except Exception as e:
        print(f"[GET EVO PASS ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/set_evo_pass', methods=['POST'])
def set_evo_pass():
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    new_pass_value = data.get("Pass")

    if not username or new_pass_value is None:
        return jsonify({"status": "error", "message": "Paramètres manquants"}), 400

    try:
        # Vérifie que l'utilisateur existe
        user_check = supabase.table("FDPiece").select("Pass").eq("username", username).single().execute()
        if not user_check.data:
            return jsonify({"status": "not_found", "message": "Utilisateur introuvable"}), 404

        # Met à jour la colonne Pass
        update_response = supabase.table("FDPiece").update({"Pass": int(new_pass_value)}).eq("username", username).execute()
        if update_response.data:
            return jsonify({"status": "success", "message": f"Pass mis à jour à {new_pass_value}"}), 200
        else:
            return jsonify({"status": "error", "message": "Échec de la mise à jour"}), 500

    except Exception as e:
        print(f"[SET EVO PASS ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------ gestion abonnement (basique, medium ou premium) -----------

@app.route('/set_sub', methods=['POST'])
def set_sub():
    try:
        data = request.get_json(force=True)
        username = (data.get('username') or "").strip()
        sub_level = (data.get('sub') or "").strip().lower()
        price = int(data.get('price', 0))

        if not username or sub_level not in ["basique", "medium", "premium"]:
            return jsonify({"status": "error", "message": "Paramètres invalides"}), 400

        # Récupérer FDPiece actuel
        response = supabase.table("FDPiece") \
            .select("FDPiece") \
            .eq("username", username) \
            .single() \
            .execute()

        if not response.data:
            return jsonify({"status": "not_found", "message": "Utilisateur introuvable"}), 404

        current_fd = int(response.data.get("FDPiece", 0))

        # 🔒 vérification argent suffisant (uniquement si un prix est demandé)
        if price > 0 and current_fd < price:
            return jsonify({"status": "error", "message": "FDPiece insuffisant"}), 403

        new_fd = current_fd - price

        # Mise à jour FDPiece + Abonnement
        supabase.table("FDPiece") \
            .update({
                "FDPiece": new_fd,
                "Abonnement": sub_level
            }) \
            .eq("username", username) \
            .execute()

        return jsonify({
            "status": "success",
            "Abonnement": sub_level,
            "FDPiece": new_fd
        }), 200

    except Exception as e:
        print(f"[SET SUB ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/get_sub', methods=['POST'])
def get_sub():
    try:
        data = request.get_json(force=True)
        username = (data.get('username') or "").strip()

        if not username:
            return jsonify({"status": "error", "message": "Username manquant"}), 400

        response = supabase.table("FDPiece") \
            .select("Abonnement") \
            .eq("username", username) \
            .single() \
            .execute()

        if not response.data:
            return jsonify({"status": "not_found", "message": "Utilisateur introuvable"}), 404

        abonnement = response.data.get("Abonnement")

        return jsonify({
            "status": "success",
            "Abonnement": abonnement
        }), 200

    except Exception as e:
        print(f"[GET SUB ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

#----------------pub / retour postback --------------------

@app.route('/stripe_webhook', methods=['POST'])
def stripe_webhook():
    # Stripe envoie des données en JSON
    payload = request.get_json()
    
    # Vérification sommaire de la structure de l'événement
    if not payload or 'type' not in payload:
        return "Invalid payload", 400

    # On cible l'événement de paiement réussi
    if payload['type'] == 'checkout.session.completed':
        session = payload['data']['object']
        
        # Stripe range les variables personnalisées dans 'metadata'
        # On extrait goal_id et virtual_amount
        goal_id = session.get('metadata', {}).get('client_reference_id')
        virtual_amount = session.get('metadata', {}).get('virtual_amount')

        if not goal_id or not virtual_amount:
            return "Missing metadata", 400

        try:
            montant = int(virtual_amount)

            # --- Votre logique Supabase inchangée ---
            player = supabase.table('FDPiece').select("FDPiece").eq("username", client_reference_id).execute()
            current_credits = player.data[0]["FDPiece"] if player.data else 0

            supabase.table('FDPiece').update({
                "FDPiece": current_credits + montant
            }).eq("username", client_reference_id).execute()
            # ---------------------------------------

            return "OK", 200
        except Exception as e:
            print(f"[Stripe Error] {e}")
            return "Error processing payment", 500

    return "Unhandled event type", 200


# ----------------------------------------------------------------------
# --- DÉMARRAGE DU SERVEUR ---
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Démarre le thread de vérification d'activité en arrière-plan
    activity_thread = threading.Thread(target=check_player_activity, daemon=True)
    activity_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    # '0.0.0.0' est utilisé pour écouter toutes les interfaces publiques
    app.run(host='0.0.0.0', port=port)
