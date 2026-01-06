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
            
            # Mise à jour de la partie
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
        
        # 4. Déterminer le statut et Mettre à jour la base de données
        game_status = "active"
        if board.is_checkmate():
            game_status = "checkmate"
        elif board.is_stalemate() or board.is_fivefold_repetition() or board.is_insufficient_material() or board.is_seventyfive_moves():
            game_status = "draw"

        update_data = {
            "fen_state": new_fen,
            "moves_list": moves_list,
        }
        
        supabase.table(TABLE_NAME_CHESS).update(update_data).eq("uuid", game_uuid).execute()
        
        return jsonify({
            "success": True, 
            "new_fen": new_fen,
            "game_status": game_status
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
            .or_(f"white_player_id.eq.{player_id}", f"black_player_id.eq.{player_id}") \
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
