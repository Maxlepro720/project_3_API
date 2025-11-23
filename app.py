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

# --- CONSTANTES DE LÉNGTH LIMIT ---
MAX_SESSION_CODE_LENGTH = 14
MAX_PLAYERS_PER_SESSION = 5 
# ---------------------------------

app = Flask(__name__)
CORS(app)

# NOTE : Assurez-vous que ces variables d'environnement sont bien définies
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Variables d'environnement SUPABASE_URL ou SUPABASE_KEY manquantes")

# Initialisation du client Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------------------------------------------------------------
# --- UTILITIES ---
# ----------------------------------------------------------------------

def generate_session_code(length=5):
    """Génère un code de session aléatoire de la longueur spécifiée."""
    if length > MAX_SESSION_CODE_LENGTH:
        length = MAX_SESSION_CODE_LENGTH
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(length))

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
        "personnel_upgrade": 1.0, # Float par défaut
    }).execute()
    print(f"[SIGNUP] {username} créé")

    return jsonify({"status": "success", "message": f"Utilisateur {username} ajouté"}), 201

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

    # Assure l'existence de la session personnelle
    existing_session = supabase.table("Sessions").select("Code").eq("Creator", username).execute()
    if not existing_session.data:
        session_code = generate_session_code()
        supabase.table("Sessions").insert({
            "Code": session_code, 
            "Creator": username, 
            "Players": [],  
            "poires": 0, 
            "By_Click": 1.0 # Float par défaut
        }).execute()
        print(f"[LOGIN] Session personnelle {session_code} créée pour {username} (Creator).")
    else:
        session_code = existing_session.data[0]["Code"]
        # Nettoyage: s'assurer qu'il n'est pas dans la liste Players 
        session_data = supabase.table("Sessions").select("Players").eq("Code", session_code).limit(1).execute().data[0]
        players = get_players_list(session_data)
        if username in players:
             players.remove(username)
             supabase.table("Sessions").update({"Players": players}).eq("Code", session_code).execute()
             print(f"[LOGIN] {username} retiré de la liste de joueurs de sa session personnelle (Créateur).")

    print(f"[LOGIN] {username} connecté.")
    return jsonify({"status": "success", "message": f"Connexion réussie pour {username}"}), 200

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

        # 1. Met le joueur offline
        supabase.table("Player").update({"Status": "🔴 offline"}).eq("ID", username).execute()

        # 2. Retire le joueur de toutes les listes "Players"
        response = supabase.table("Sessions").select("Code, Players").execute()
        for session in response.data or []:
            session_code = session.get("Code")
            players = get_players_list(session)
            
            if username in players:
                players.remove(username)
                supabase.table("Sessions").update({"Players": players}).eq("Code", session_code).execute()

        print(f"[LOGOUT] {username} déconnecté et retiré des listes de joueurs.")
        return jsonify({"status": "success", "message": f"{username} est offline et retiré des sessions"}), 200
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

## --- GESTION DE SESSION ---

@app.route("/create", methods=["POST"])
def create_session():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    
    if not player_id:
        return jsonify({"status": "error", "message": "ID utilisateur manquant"}), 400

    try:
        existing_session_response = supabase.table("Sessions").select("Code").eq("Creator", player_id).limit(1).execute()
        
        if existing_session_response.data:
            session_code = existing_session_response.data[0]["Code"]
            print(f"[CREATE] Session personnelle existante pour {player_id}: {session_code}")
            return jsonify({
                "status": "success", 
                "message": "Session personnelle existante chargée.",
                "session_name": session_code
            }), 200 
        
        session_code = generate_session_code(length=5) 
        
        new_session_data = {
            "Code": session_code,
            "Creator": player_id,
            "Players": [], 
            "poires": 0,
            "By_Click": 1.0, # Float par défaut
        }

        supabase.table("Sessions").insert(new_session_data).execute()
        print(f"[CREATE] Nouvelle session personnelle {session_code} créée par {player_id} (Creator)")
        
        return jsonify({"status": "success", "session_name": session_code}), 201
        
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

## --- NOUVELLES ROUTES D'AMÉLIORATION ---

@app.route("/upgrade_add", methods=["POST"])
def upgrade_add_session():
    """Ajoute une valeur (float) au By_Click (float) de la session."""
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    upgrade_value = data.get("upgrade")
    
    if not session_code or upgrade_value is None:
        return jsonify({"status": "error", "message": "Paramètres session ou upgrade manquants"}), 400
    
    try:
        upgrade_value = float(upgrade_value)
        
        response = supabase.table("Sessions").select("By_Click").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        current_by_click = response.data[0].get("By_Click", 1.0)
        new_by_click = float(current_by_click) + upgrade_value
        
        supabase.table("Sessions").update({"By_Click": new_by_click}).eq("Code", session_code).execute()

        print(f"[UPGRADE_ADD] Session {session_code}: By_Click passe de {current_by_click} à {new_by_click}.")
        return jsonify({"status": "success", "new_by_click": new_by_click}), 200
    except ValueError:
        return jsonify({"status": "error", "message": "La valeur 'upgrade' doit être un nombre flottant."}), 400
    except Exception as e:
        print(f"[UPGRADE_ADD ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/upgrade_multiply", methods=["POST"])
def upgrade_multiply_session():
    """Multiplie le By_Click (float) de la session par une valeur (float)."""
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    upgrade_multiplier = data.get("upgrade")
    
    if not session_code or upgrade_multiplier is None:
        return jsonify({"status": "error", "message": "Paramètres session ou upgrade manquants"}), 400
    
    try:
        upgrade_multiplier = float(upgrade_multiplier)
        if upgrade_multiplier <= 0:
            return jsonify({"status": "error", "message": "Le multiplicateur doit être supérieur à zéro."}), 400
        
        response = supabase.table("Sessions").select("By_Click").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        current_by_click = response.data[0].get("By_Click", 1.0)
        new_by_click = float(current_by_click) * upgrade_multiplier
        
        supabase.table("Sessions").update({"By_Click": new_by_click}).eq("Code", session_code).execute()

        print(f"[UPGRADE_MUL] Session {session_code}: By_Click passe de {current_by_click} à {new_by_click}.")
        return jsonify({"status": "success", "new_by_click": new_by_click}), 200
    except ValueError:
        return jsonify({"status": "error", "message": "Le multiplicateur 'upgrade' doit être un nombre flottant."}), 400
    except Exception as e:
        print(f"[UPGRADE_MUL ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route("/personnel_boost", methods=["POST"])
def personnel_boost():
    """Ajoute une valeur (float) au personnel_upgrade (float) du joueur."""
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    boost_value = data.get("boost")
    
    if not player_id or boost_value is None:
        return jsonify({"status": "error", "message": "Paramètres ID ou boost manquants"}), 400
    
    try:
        boost_value = float(boost_value)
        
        response = supabase.table("Player").select("personnel_upgrade").eq("ID", player_id).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Joueur introuvable"}), 404
            
        current_boost = response.data[0].get("personnel_upgrade", 1.0)
        new_boost = float(current_boost) + boost_value
        
        supabase.table("Player").update({"personnel_upgrade": new_boost}).eq("ID", player_id).execute()

        print(f"[PERSONAL_BOOST] {player_id}: boost passe de {current_boost} à {new_boost}.")
        return jsonify({"status": "success", "new_personal_boost": new_boost}), 200
    except ValueError:
        return jsonify({"status": "error", "message": "La valeur 'boost' doit être un nombre flottant."}), 400
    except Exception as e:
        print(f"[PERSONAL_BOOST ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

## --- INFORMATIONS & DONNÉES ---

@app.route("/verify_session", methods=["GET"])
def verify_session():
    # ... (inchangé)
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
                players = get_players_list(session)
                if player_id in players:
                    final_session = session
                    break

        if final_session:
            final_players = get_players_list(final_session)
            creator = final_session.get("Creator")
            
            final_players.append(creator)
            final_players = list(set(final_players))

            return jsonify({
                "status": "success",
                "session_code": final_session.get("Code"),
                "creator": creator,
                "players": final_players 
            }), 200

        print(f"[VERIFY] {player_id} non trouvé dans aucune session.")
        return jsonify({"status": "error", "message": "Joueur non trouvé dans aucune session"}), 404
    except Exception as e:
        print(f"[VERIFY ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/verify_player_in_session", methods=["GET"])
def verify_player_in_session():
    # ... (inchangé)
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
        # Le nombre de clics est l'input de base et peut être un entier.
        click = int(click)
        
        # 1. Récupérer By_Click (float) de la session
        session_response = supabase.table("Sessions").select("poires, By_Click").eq("Code", session_code).execute()
        if not session_response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session_data = session_response.data[0]
        current_poires = session_data.get("poires", 0)
        # Assure que la valeur de la DB est traitée comme float
        session_by_click = float(session_data.get("By_Click", 1.0))
        
        # 2. Récupérer personnel_upgrade (float) du joueur
        player_response = supabase.table("Player").select("personnel_upgrade").eq("ID", player_id).execute()
        if not player_response.data:
             player_boost = 1.0
        else:
             # Assure que la valeur de la DB est traitée comme float
             player_boost = float(player_response.data[0].get("personnel_upgrade", 1.0))

        # 3. Calculer les poires à ajouter (float intermédiaire)
        raw_poires_to_add = click * session_by_click * player_boost
        
        # 4. ARRONDISSEMENT du score à l'entier le plus proche
        poires2add = int(round(raw_poires_to_add))
        
        new_total = current_poires + poires2add
        
        # 5. Mise à jour de la nouvelle valeur (qui est un INT)
        supabase.table("Sessions").update({"poires": new_total}).eq("Code", session_code).execute()

        print(f"[POIRE] {player_id} a ajouté {poires2add} poires à la session {session_code}. Total: {new_total}. (Base: {click}, Session Boost: {session_by_click:.2f}, Perso Boost: {player_boost:.2f}, Raw: {raw_poires_to_add:.2f})")
        return jsonify({"status": "success", "added": poires2add, "poires": new_total}), 200
    except ValueError:
        return jsonify({"status": "error", "message": "La valeur 'click' doit être un nombre entier."}), 400
    except Exception as e:
        print(f"[POIRE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/get_poires", methods=["GET"])
def get_poires():
    data = request.args.get("session", "").strip()
    if not data:
        return jsonify({"status": "error", "message": "Code de session manquant"}), 400
    try:
        session_data = supabase.table("Sessions").select("poires").eq("Code", data).execute()
        if not session_data.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404
        # Le score "poires" est stocké en INT
        poires = session_data.data[0].get("poires", 0) 
        return jsonify({"status": "success", "poires": poires}), 200
    except Exception as e:
        print(f"[GET POIRES ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ----------------------------------------------------------------------
# --- DÉMARRAGE DU SERVEUR ---
# ----------------------------------------------------------------------
if __name__ == "__main__":
    activity_thread = threading.Thread(target=check_player_activity, daemon=True)
    activity_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur démarré sur le port {port}")
    app.run(host="0.0.0.0", port=port)
