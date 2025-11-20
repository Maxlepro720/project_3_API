from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
import json
from flask_cors import CORS
# --- IMPORTS POUR LE THREADING ET LE TEMPS ---
import threading
import time
from datetime import datetime, timedelta, timezone
# ---------------------------------------------

# --- CONSTANTE DE LÉNGTH LIMIT ---
MAX_SESSION_CODE_LENGTH = 14
# ---------------------------------

app = Flask(__name__)
CORS(app)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    # SUPABASE_URL = "VOTRE_URL_SUPABASE" 
    # SUPABASE_KEY = "VOTRE_CLE_SUPABASE"
    raise RuntimeError("Variables d'environnement SUPABASE_URL ou SUPABASE_KEY manquantes")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ----------------------------------------------------------------------
# --- HOOK DE MISE À JOUR D'ACTIVITÉ (S'exécute avant chaque requête) ---
# ----------------------------------------------------------------------
@app.before_request
def update_last_seen():
    """
    Met à jour la colonne 'last_seen' et s'assure que le joueur est 'online'.
    """
    player_id = None
    
    try:
        if request.method in ["POST", "PUT"]:
            # Utilise get_json(silent=True) pour éviter l'erreur si le corps n'est pas JSON
            data = request.get_json(silent=True)
            if data:
                # Tente de trouver l'ID dans le corps JSON
                player_id = (data.get("id") or data.get("player_id") or data.get("username"))
        elif request.method == "GET":
            # Tente de trouver l'ID dans les arguments de l'URL
            player_id = (request.args.get("id") or request.args.get("user") or request.args.get("username"))
            
        if player_id:
            player_id = player_id.strip() # S'assurer de nettoyer après l'extraction
            if player_id: # Vérifie si l'ID n'est pas vide après le strip
                # Met à jour last_seen ET s'assure que le statut est "🟢 online"
                supabase.table("Player").update({
                    "last_seen": "now()",
                    "Status": "🟢 online" 
                }).eq("ID", player_id).execute()
                
    except Exception as e:
        # print(f"[BEFORE_REQUEST_ERROR] {e}") # Décommenter pour debug
        pass

# ----------------------------------------------------------------------
# --- TÂCHE D'ARRIÈRE-PLAN POUR LA VÉRIFICATION D'INACTIVITÉ ---
# ----------------------------------------------------------------------
def check_player_activity():
    """
    Vérifie périodiquement les joueurs inactifs (plus de 15 secondes) et les met 'offline'.
    """
    print("[SCHEDULER] Le vérificateur d'activité est démarré.")
    while True:
        try:
            # Calcule le temps de coupure (il y a 15 secondes) en UTC
            cutoff_time = (datetime.now(timezone.utc) - timedelta(seconds=15)).isoformat()
            
            # Mise à jour des joueurs inactifs : Status = online ET last_seen est trop vieux
            response = supabase.table("Player") \
                .update({"Status": "🔴 offline"}) \
                .eq("Status", "🟢 online") \
                .lt("last_seen", cutoff_time) \
                .execute()

            if response.data and len(response.data) > 0:
                print(f"[SCHEDULER] {len(response.data)} joueur(s) mis hors ligne pour inactivité.")

        except Exception as e:
            print(f"[SCHEDULER_ERROR] Erreur lors de la vérification d'activité: {e}")
        
        # Attend 10 secondes avant la prochaine vérification pour ne pas surcharger la base de données
        time.sleep(10)


def generate_session_code(length=12):
    """Génère un code de session aléatoire de la longueur spécifiée (max 14)."""
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
    # Ajout de 'last_seen' à la création
    supabase.table("Player").insert({
        "ID": username, 
        "Password": hashed_pw, 
        "Status": "🔴 offline",
        "last_seen": "now()" # Initialisation de last_seen
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
        # La session n'existe pas, on la crée
        session_code = generate_session_code()
        supabase.table("Sessions").insert({
            "Code": session_code, 
            "Creator": username, 
            "Players": [], 
            "poires": 0, 
            "By_Click": 1
        }).execute()
        
    # Met à jour le statut ET last_seen
    supabase.table("Player").update({"Status": "🟢 online", "last_seen": "now()"}).eq("ID", username).execute()
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
            try: players = json.loads(players)
            except: players = []

        if player_id in players:
            return jsonify({"status": "error", "message": "Déjà dans la session"}), 400
        if len(players) >= 5:
            return jsonify({"status": "error", "message": "La session est pleine (max 5 joueurs)"}), 400

        players.append(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
        print(f"[JOIN] {player_id} a rejoint {code}.")

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
        
        # Le hook @before_request mettra automatiquement à jour last_seen et le statut quand le joueur revient à sa session perso

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

        # Met le joueur offline
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
            
        return jsonify({"status": "success", "message": f"{username} est offline et retiré des sessions"}), 200
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- POIRE CLICK (Nécessite 'id' pour la vérification d'activité) ---
@app.route("/poire", methods=["POST"])
def poire():
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    click = (data.get("click") or 0)
    player_id = (data.get("id") or "").strip() # ID nécessaire pour le hook @before_request
    
    if not session_code or not player_id:
        return jsonify({"status": "error", "message": "Session ou ID joueur manquant"}), 400
    
    try:
        response = supabase.table("Sessions").select("*").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]
        by_click = session.get("By_Click", 1)
        poires2add = by_click * int(click)
        current_poires = session.get("poires", 0)

        new_total = current_poires + poires2add
        # Mise à jour des poires
        supabase.table("Sessions").update({"poires": new_total}).eq("Code", session_code).execute()
        # Mise à jour du click (peut-être inutile mais conservé)
        supabase.table("Sessions").update({"Click": click}).eq("Code", session_code).execute()
        
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
            try: players = json.loads(players_raw)
            except: players = [players_raw]
        else: players = players_raw

        if username == creator:
            other_players = [p for p in players if p != creator]
            return jsonify({"status": "success", "player": other_players}), 200
        else:
            return jsonify({"status": "success", "player": creator}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- CREATE SESSION ---
@app.route("/create", methods=["POST"])
def create_session():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    
    if not player_id:
        return jsonify({"status": "error", "message": "ID utilisateur manquant"}), 400

    try:
        # Simplification: on vérifie seulement si le joueur est créateur d'une session
        existing_session = supabase.table("Sessions").select("Code").eq("Creator", player_id).execute()
        
        if existing_session.data:
             current_session_code = existing_session.data[0]["Code"]
             return jsonify({
                 "status": "error", 
                 "message": f"Vous êtes déjà créateur de la session '{current_session_code}'. Quittez-la d'abord ou rejoignez-la.",
                 "session_name": current_session_code
             }), 409

        # Vérification si le joueur est un simple joueur dans une autre session
        # Note: Cette vérification est coûteuse et non optimale pour une grande base de données.
        # Idéalement, la colonne Players devrait être une table séparée pour les jointures.
        # Pour rester proche du code original:
        response = supabase.table("Sessions").select("Code, Players").execute()
        for session in response.data or []:
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
                     "message": f"Vous êtes déjà joueur dans la session '{current_session_code}'. Quittez-la d'abord.",
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


# --- VERIFY SESSION (Priorité Joueur > Créateur) ---
@app.route("/verify_session", methods=["GET"])
def verify_session():
    player_id = request.args.get("id", "").strip()
    if not player_id:
        return jsonify({"status": "error", "message": "ID manquant"}), 400
    try:
        # Tente de trouver la session où l'utilisateur est Créateur
        creator_session_response = supabase.table("Sessions").select("*").eq("Creator", player_id).limit(1).execute()
        if creator_session_response.data:
            final_session = creator_session_response.data[0]
        else:
            # Tente de trouver la session où l'utilisateur est Joueur (recherche dans l'array 'Players')
            # C'est une opération lente sans index GIN, mais nous conservons la structure du code original
            player_session_response = supabase.table("Sessions").select("*").execute()
            final_session = None
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

            return jsonify({
                "status": "success",
                "session_code": final_session.get("Code"),
                "creator": final_session.get("Creator"),
                "players": final_players 
            }), 200
            
        return jsonify({"status": "error", "message": "Joueur non trouvé dans aucune session"}), 404
    except Exception as e:
        print(f"[VERIFY ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# --- CHANGE SESSION ---
@app.route("/change_session", methods=["POST"])
def change_session():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    new_session_name_raw = (data.get("new_session_name") or "").strip()
    
    if not player_id or not new_session_name_raw:
        return jsonify({"status": "error", "message": "ID ou nouveau nom manquant"}), 400
    
    try:
        # 1. Troncation du nouveau nom si nécessaire
        original_name = new_session_name_raw
        new_session_name = new_session_name_raw[:MAX_SESSION_CODE_LENGTH]
        
        was_truncated = len(original_name) > MAX_SESSION_CODE_LENGTH
        
        # 2. Vérification de la session actuelle du créateur
        session_response = supabase.table("Sessions").select("*").eq("Creator", player_id).execute()
        if not session_response.data:
            # Vérifie si le joueur est juste joueur dans une session
            # Note: C'est coûteux, la vérification ci-dessus est suffisante pour un changement de code
            # puisque seul le créateur peut changer le code.
            return jsonify({"status": "error", "message": "Aucune session trouvée pour ce joueur (ou vous n'en êtes pas le créateur)"}), 404
        
        session = session_response.data[0]
        old_session_code = session["Code"]
        
        # 3. Vérification de l'unicité du nouveau nom tronqué
        if new_session_name == old_session_code:
            return jsonify({"status": "error", "message": "Le nouveau nom est identique au code actuel."}), 409
        
        existing = supabase.table("Sessions").select("*").eq("Code", new_session_name).execute()
        if existing.data:
            return jsonify({"status": "error", "message": f"Ce nom de session '{new_session_name}' est déjà utilisé"}), 409

        # 4. Mise à jour du code
        supabase.table("Sessions").update({"Code": new_session_name}).eq("Code", old_session_code).execute()
        
        message = f"Session changée de '{old_session_code}' à '{new_session_name}'"
        if was_truncated:
            message += f" (Note: le nom original a été tronqué à {MAX_SESSION_CODE_LENGTH} caractères)."
            
        print(f"[CHANGE] Session {old_session_code} changée en {new_session_name} par {player_id}.")
        
        return jsonify({
            "status": "success", 
            "message": message, 
            "new_code": new_session_name
        }), 200
        
    except Exception as e:
        print(f"[CHANGE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ----------------------------------------------------------------------
# --- DÉMARRAGE DU SERVEUR ---
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # DÉMARRAGE DU THREAD D'ARRIÈRE-PLAN pour vérifier l'inactivité
    activity_thread = threading.Thread(target=check_player_activity, daemon=True)
    activity_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur démarré sur le port {port}")
    app.run(host="0.0.0.0", port=port)
