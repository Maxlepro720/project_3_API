from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from flask_cors import CORS
from decimal import Decimal # Conservé, peut être utile si des décimaux sont nécessaires plus tard

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

# Nom de vos tables de sauvegarde
TABLE_NAME_Skull_Arena = "Skull_Arena_DataBase"
TABLE_NAME_ASTRO_DODGE = "Astro_Dodge"
TABLE_NAME_STICKMAN_RUNNER = "Stickman_Runner"

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
                # Écrit Last_Seen
                supabase.table("Player").update({ 
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
def check_player_activity():
    while True:
        try:
            time.sleep(15)

            inactivity_limit = datetime.now(timezone.utc) - timedelta(seconds=15)
            inactivity_limit_iso = inactivity_limit.isoformat()

            # Met tous les joueurs 'online' qui n'ont pas bougé depuis 15s à 'offline'
            supabase.table("Player").update({
                "Status": "🔴 offline"
            }).lt(
                "Last_Seen", inactivity_limit_iso
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

    existing = supabase.table("Player").select("*").eq("ID", username).execute()
    if existing.data:
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    hashed_pw = generate_password_hash(password)
    
    # Insertion dans la table Player sans le champ 'personnel_upgrade'
    supabase.table("Player").insert({
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

    user = supabase.table("Player").select("Password").eq("ID", username).execute()
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
        user = supabase.table("Player").select("*").eq("ID", username).execute()
        if not user.data:
            return jsonify({"status": "error", "message": "Utilisateur introuvable"}), 404

        # Met à jour le statut à offline
        supabase.table("Player").update({"Status": "🔴 offline"}).eq("ID", username).execute()
        
        print(f"[LOGOUT] {username} déconnecté")
        response = jsonify({"status": "success", "message": f"{username} est offline"})
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response, 200
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ------------------------------------------------
# SKULL ARENA (ROUTES DE GESTION DE JEU)
# ------------------------------------------------
@app.route('/skull_arena_update_data', methods=['POST'])
def skull_arena_update_data():
    """ [Skull_Arena_ServerSave] Met à jour les données du joueur (crânes, meilleure vague, niveaux d'amélioration).
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
        
        # 2. Préparer le payload
        payload = {
            "username": username,
            "Best_Vague": final_best_vague,
            "Crane": int(data.get('skulls', 0)),
            "UP_Degat": int(data.get('up_damage', 0)),
            "UP_Portée": int(data.get('up_range', 0)),
            "UP_Vitesse": int(data.get('up_speed', 0)),
            "UP_Cadence": int(data.get('up_fire', 0))
        }
        # 3. Effectuer l'UPSERT (Insert ou Update)
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
        columns = '"Crane", "Best_Vague", "UP_Degat", "UP_Portée", "UP_Vitesse", "UP_Cadence"'
        response = supabase.table(TABLE_NAME_Skull_Arena).select(columns).eq('username', username).limit(1).execute()
        
        if not response.data:
            return jsonify({
                "status": "not_found", 
                "message": "Données Skull Arena introuvables. Initialisation...",
                "data": {"skulls": 0, "best_wave": 0, "levels": {"damage": 0, "range": 0, "speed": 0, "fire": 0}}
            }), 200
        
        row = response.data[0]
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
        response = supabase.table(TABLE_NAME_Skull_Arena) \
            .select("username, Best_Vague") \
            .order("Best_Vague", desc=True) \
            .limit(10) \
            .execute()
            
        formatted_data = []
        for row in response.data:
            formatted_data.append({
                "name": row.get('username'),
                "wave": int(row.get('Best_Vague', 0))
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
    """ [Astro_Dodge_ServerSave] Met à jour le meilleur score et le crédit du joueur.
    (Assumes Supabase table 'Astro_Dodge' has columns: username, Best_Score, Credit)
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        new_score = int(data.get('score', 0))
        
        # 1. Fetcher le meilleur score actuel
        current_data_query = supabase.table(TABLE_NAME_ASTRO_DODGE).select('"Best_Score"').eq('username', username).limit(1).execute()
        current_data = current_data_query.data[0] if current_data_query.data else None
        current_best_score = current_data.get('Best_Score', 0) if current_data else 0
        final_best_score = max(current_best_score, new_score)
        
        # 2. Préparer le payload
        payload = {
            "username": username,
            "Best_Score": final_best_score,
            "Credit": int(data.get('credit', 0))
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
    """ [Astro_Dodge_ServerLoad] Récupère les données d'un joueur.
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        columns = '"Best_Score", "Credit"'
        response = supabase.table(TABLE_NAME_ASTRO_DODGE).select(columns).eq('username', username).limit(1).execute()
        
        if not response.data:
            return jsonify({
                "status": "not_found", 
                "message": "Données Astro Dodge introuvables. Initialisation...",
                "data": {"score": 0, "credit": 0}
            }), 200
        
        row = response.data[0]
        return jsonify({
            "status": "success", 
            "message": "Données Astro Dodge chargées",
            "data": {
                "score": int(row.get('Best_Score', 0)),
                "credit": int(row.get('Credit', 0))
            }
        }), 200
    except Exception as e:
        print(f"[LOAD ASTRO DODGE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/astro_dodge_get_leaderboard', methods=['GET'])
def astro_dodge_get_leaderboard():
    """ Récupère les 10 meilleurs scores (Best_Score) du classement global.
    """
    try:
        response = supabase.table(TABLE_NAME_ASTRO_DODGE) \
            .select("username, Best_Score") \
            .order("Best_Score", desc=True) \
            .limit(10) \
            .execute()
            
        formatted_data = []
        for row in response.data:
            formatted_data.append({
                "name": row.get('username'),
                "score": int(row.get('Best_Score', 0))
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
    """ [Stickman_Runner_ServerSave] Met à jour la meilleure distance et le crédit du joueur.
    (Assumes Supabase table 'Stickman_Runner' has columns: username, Best_Distance, Credit)
    """
    data = request.get_json(force=True)
    username = (data.get('username') or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "Username manquant"}), 400
    try:
        new_distance = int(data.get('distance', 0))
        
        # 1. Fetcher la meilleure distance actuelle
        current_data_query = supabase.table(TABLE_NAME_STICKMAN_RUNNER).select('"Best_Distance"').eq('username', username).limit(1).execute()
        current_data = current_data_query.data[0] if current_data_query.data else None
        current_best_distance = current_data.get('Best_Distance', 0) if current_data else 0
        final_best_distance = max(current_best_distance, new_distance)
        
        # 2. Préparer le payload
        payload = {
            "username": username,
            "Best_Distance": final_best_distance,
            "Credit": int(data.get('credit', 0))
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
        columns = '"Best_Distance", "Credit"'
        response = supabase.table(TABLE_NAME_STICKMAN_RUNNER).select(columns).eq('username', username).limit(1).execute()
        
        if not response.data:
            return jsonify({
                "status": "not_found", 
                "message": "Données Stickman Runner introuvables. Initialisation...",
                "data": {"distance": 0, "credit": 0}
            }), 200
        
        row = response.data[0]
        return jsonify({
            "status": "success", 
            "message": "Données Stickman Runner chargées",
            "data": {
                "distance": int(row.get('Best_Distance', 0)),
                "credit": int(row.get('Credit', 0))
            }
        }), 200
    except Exception as e:
        print(f"[LOAD STICKMAN RUNNER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stickman_runner_get_leaderboard', methods=['GET'])
def stickman_runner_get_leaderboard():
    """ Récupère les 10 meilleures distances (Best_Distance) du classement global.
    """
    try:
        response = supabase.table(TABLE_NAME_STICKMAN_RUNNER) \
            .select("username, Best_Distance") \
            .order("Best_Distance", desc=True) \
            .limit(10) \
            .execute()
            
        formatted_data = []
        for row in response.data:
            formatted_data.append({
                "name": row.get('username'),
                "distance": int(row.get('Best_Distance', 0))
            })

        return jsonify({
            "status": "success", 
            "message": "Classement global Stickman Runner chargé.", 
            "data": formatted_data
        }), 200
        
    except Exception as e:
        print(f"[LEADERBOARD STICKMAN RUNNER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


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
