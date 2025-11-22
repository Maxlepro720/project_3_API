from flask import Flask, request, jsonify
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash
import os
import random
import json
from flask_cors import CORS
# from datetime import datetime, timedelta, timezone # Non utilisé pour l'instant, mais bon à conserver si besoin

# --- CONSTANTE DE LÉNGTH LIMIT ---
MAX_SESSION_CODE_LENGTH = 14
MAX_PLAYERS_PER_SESSION = 5 # Ajouté pour la cohérence
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

def generate_session_code(length=5): # J'ai réduit la longueur par défaut pour des codes plus courts
    """Génère un code de session aléatoire de la longueur spécifiée."""
    if length > MAX_SESSION_CODE_LENGTH:
        length = MAX_SESSION_CODE_LENGTH
        
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    # S'assurer qu'il est unique (cela nécessiterait une boucle et une vérification DB,
    # mais pour simplifier on garde la version simple ici)
    return "".join(random.choice(chars) for _ in range(length))

def get_players_list(session_data):
    """Gère la désérialisation potentielle de la liste de joueurs de Supabase."""
    players_raw = session_data.get("Players")
    if isinstance(players_raw, str):
        try:
            return json.loads(players_raw)
        except json.JSONDecodeError:
            return []
    elif isinstance(players_raw, list):
        return players_raw
    return []

# ----------------------------------------------------------------------
# --- LOGIC & ROUTES FLASK ---
# ----------------------------------------------------------------------

@app.route("/")
def home():
    return "Serveur Flask en ligne"

# --- SIGNUP ---
# (Reste inchangé, fonctionne correctement)
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

# --- LOGIN (CORRIGÉ : Assure la session personnelle du Créateur) ---
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

    # Utilise l'ID comme code de session personnelle par défaut (si non définie via /cha)
    # Dans votre logique client, la session perso est créée au chargement via /create
    # Ici, nous nous assurons simplement que le joueur est actif
    
    supabase.table("Player").update({"Status": "🟢 online"}).eq("ID", username).execute()
    
    # Pour le client, le code de session est récupéré via /verify_session après le login.
    # On retourne un code par défaut ou on s'attend à ce que le client fasse l'appel suivant.
    # Pour être compatible avec l'appel client, on ne renvoie pas de code ici, 
    # car l'init du client appelle /loadMySession qui appelle /getPlayerSessionInfo (qui appelle /verify_session)
    print(f"[LOGIN] {username} connecté.")
    return jsonify({"status": "success", "message": f"Connexion réussie pour {username}"}), 200


# --- CREATE SESSION (Utilisé pour initialiser la session personnelle au chargement) ---
@app.route("/create", methods=["POST"])
def create_session():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    # Le client envoie un 'code' qui est souvent l'ID du joueur, mais nous générons un code unique pour la session personnelle
    # Note: Votre client envoie `body: JSON.stringify({ code: sessionCode, id: username })`
    # Nous ignorons `code` car l'ID est la clé pour trouver la session personnelle.

    if not player_id:
        return jsonify({"status": "error", "message": "ID utilisateur manquant"}), 400

    try:
        # 1. Vérification si le joueur est DÉJÀ créateur d'une session (session personnelle)
        existing_session_response = supabase.table("Sessions").select("Code").eq("Creator", player_id).limit(1).execute()
        
        if existing_session_response.data:
            session_code = existing_session_response.data[0]["Code"]
            # Réponse client attendue : { status: "success", session_name: code }
            print(f"[CREATE] Session personnelle existante pour {player_id}: {session_code}")
            return jsonify({
                "status": "success", 
                "message": "Session personnelle existante chargée.",
                "session_name": session_code
            }), 200

        # 2. Création d'une nouvelle session personnelle
        session_code = generate_session_code(length=5) # Nouveau code aléatoire
        
        new_session_data = {
            "Code": session_code,
            "Creator": player_id,
            "Players": [player_id], # Le créateur est automatiquement un joueur
            "poires": 0,
            "By_Click": 1, 
        }

        supabase.table("Sessions").insert(new_session_data).execute()
        print(f"[CREATE] Nouvelle session personnelle {session_code} créée par {player_id}")
        
        # Le client utilise "session_name" pour afficher le code
        return jsonify({"status": "success", "session_name": session_code}), 201
        
    except Exception as e:
        print(f"[CREATE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- JOIN SESSION (CORRIGÉ : Mise à jour de la liste de joueurs) ---
@app.route("/join", methods=["POST"])
def join_session():
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip()
    player_id = (data.get("id") or "").strip()
    
    if not code or not player_id:
        return jsonify({"status": "error", "message": "Code ou ID manquant"}), 400
        
    try:
        # 1. Vérifie si la session existe
        response = supabase.table("Sessions").select("*").eq("Code", code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]
        players = get_players_list(session)
        
        # 2. Vérifie les limites
        if player_id in players:
            return jsonify({"status": "error", "message": "Déjà dans la session"}), 400
        if len(players) >= MAX_PLAYERS_PER_SESSION:
            return jsonify({"status": "error", "message": f"La session est pleine (max {MAX_PLAYERS_PER_SESSION} joueurs)"}), 400
            
        # 3. Quitter toute autre session avant de rejoindre (Logique importante)
        # On suppose que le client a fait un /leave. Ici, nous retirons le joueur de toute autre session où il est joueur
        # (et n'est pas créateur, car un créateur ne peut pas quitter sa session personnelle)
        all_sessions = supabase.table("Sessions").select("*").execute().data or []
        for s in all_sessions:
            current_players = get_players_list(s)
            if player_id in current_players and s.get("Code") != code:
                current_players.remove(player_id)
                supabase.table("Sessions").update({"Players": current_players}).eq("Code", s.get("Code")).execute()
                print(f"[JOIN CLEANUP] {player_id} retiré de l'ancienne session {s.get('Code')}.")
        
        # 4. Ajout du joueur
        players.append(player_id)
        supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
        print(f"[JOIN] {player_id} a rejoint {code}.")

        return jsonify({"status": "success", "message": f"{player_id} a rejoint la session", "players": players}), 200
    except Exception as e:
        print(f"[JOIN ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- LEAVE SESSION (CORRIGÉ : Retirer le joueur de la liste et ne rien faire s'il est créateur) ---
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
        
        # Le Créateur ne peut pas "quitter" sa session, il la ferme (non implémenté ici) ou la renomme.
        if player_id == creator:
            return jsonify({"status": "error", "message": "Le créateur ne peut pas quitter sa propre session, il doit la fermer ou se déconnecter."}), 403

        if player_id not in players:
            # Même s'il n'est pas dans la liste, on le renvoie vers sa session personnelle
            pass
        else:
            players.remove(player_id)
            supabase.table("Sessions").update({"Players": players}).eq("Code", code).execute()
            print(f"[LEAVE] {player_id} a quitté {code}.")
            
        # Récupère le code de la session personnelle de l'utilisateur (celle où il est créateur)
        personal_session_response = supabase.table("Sessions").select("Code").eq("Creator", player_id).limit(1).execute()
        new_personal_code = personal_session_response.data[0]["Code"] if personal_session_response.data else None
        
        # Assure qu'il est réintégré à sa session personnelle
        if new_personal_code:
            personal_session_data = supabase.table("Sessions").select("*").eq("Code", new_personal_code).limit(1).execute().data[0]
            personal_players = get_players_list(personal_session_data)
            if player_id not in personal_players:
                personal_players.append(player_id)
                supabase.table("Sessions").update({"Players": personal_players}).eq("Code", new_personal_code).execute()
                
        return jsonify({
            "status": "success", 
            "message": f"{player_id} a quitté la session", 
            "personal_session_code": new_personal_code,
            "players": players # La liste mise à jour du groupe quitté
        }), 200
    except Exception as e:
        print(f"[LEAVE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- LOGOUT (CORRIGÉ : Retire le joueur de partout) ---
# (Reste inchangé, fonctionne correctement)
@app.route("/logout", methods=["POST"])
def logout():
    data = request.get_json(force=True)
    username = (data.get("id") or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "ID manquant"}), 400
    try:
        supabase.table("Player").update({"Status": "🔴 offline"}).eq("ID", username).execute()
        
        response = supabase.table("Sessions").select("Code, Players").execute()
        
        for session in response.data or []:
            session_code = session.get("Code")
            players = get_players_list(session)
            
            if username in players:
                players.remove(username)
                supabase.table("Sessions").update({"Players": players}).eq("Code", session_code).execute()
            
        print(f"[LOGOUT] {username} déconnecté et retiré des sessions.")
        return jsonify({"status": "success", "message": f"{username} est offline et retiré des sessions"}), 200
    except Exception as e:
        print(f"[LOGOUT ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- POIRE CLICK (Reste inchangé, fonctionne correctement) ---
@app.route("/poire", methods=["POST"])
def poire():
    data = request.get_json(force=True)
    session_code = (data.get("session") or "").strip()
    click = (data.get("click") or 0)
    player_id = (data.get("id") or "").strip() 
    
    if not session_code or not player_id:
        return jsonify({"status": "error", "message": "Session ou ID joueur manquant"}), 400
        
    try:
        response = supabase.table("Sessions").select("poires, By_Click").eq("Code", session_code).execute()
        if not response.data:
            return jsonify({"status": "error", "message": "Session introuvable"}), 404

        session = response.data[0]
        by_click = session.get("By_Click", 1)
        poires2add = by_click * int(click) 
        current_poires = session.get("poires", 0)

        new_total = current_poires + poires2add
        
        supabase.table("Sessions").update({"poires": new_total}).eq("Code", session_code).execute()
        
        print(f"[POIRE] {player_id} a ajouté {poires2add} poires à la session {session_code}. Total: {new_total}")
        return jsonify({"status": "success", "added": poires2add, "poires": new_total}), 200
    except Exception as e:
        print(f"[POIRE ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- GET POIRES (Reste inchangé, fonctionne correctement) ---
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

# --- VERIFY SESSION (CORRIGÉ : Trouve la session active du joueur, qu'il soit Créateur ou Joueur) ---
# Ceci est l'équivalent de getPlayerSessionInfo() sur le client
@app.route("/verify_session", methods=["GET"])
def verify_session():
    player_id = request.args.get("id", "").strip()
    if not player_id:
        return jsonify({"status": "error", "message": "ID manquant"}), 400
    try:
        final_session = None
        
        # 1. Tente de trouver la session où l'utilisateur est Créateur (Priorité)
        creator_session_response = supabase.table("Sessions").select("*").eq("Creator", player_id).limit(1).execute()
        if creator_session_response.data:
            final_session = creator_session_response.data[0]
        else:
            # 2. Tente de trouver la session où l'utilisateur est Joueur
            player_session_response = supabase.table("Sessions").select("*").execute()
            for session in player_session_response.data or []:
                players = get_players_list(session)
                if player_id in players:
                    final_session = session
                    break
                    
        if final_session:
            # Le client attend session_code et creator
            print(f"[VERIFY] {player_id} trouvé dans la session {final_session.get('Code')}")
            return jsonify({
                "status": "success",
                "session_code": final_session.get("Code"),
                "creator": final_session.get("Creator"),
            }), 200
            
        print(f"[VERIFY] {player_id} non trouvé dans aucune session.")
        return jsonify({"status": "error", "message": "Joueur non trouvé dans aucune session"}), 404
    except Exception as e:
        print(f"[VERIFY ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# --- VERIFY_PLAYER_IN_SESSION (Remplacement de /get_player pour la liste des joueurs) ---
# Ceci est l'équivalent de fetchPlayersInSession() sur le client
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
        
        # Création d'un ensemble pour vérifier l'unicité incluant le créateur
        unique_active_players = set(players_in_db)
        unique_active_players.add(creator)
        
        if username not in unique_active_players:
            return jsonify({"status": "error", "message": "Joueur non membre de cette session"}), 403

        # Le client attend l'array des joueurs (Players) et le Créateur
        return jsonify({
            "status": "success",
            "session_code": session_code,
            "creator": creator,
            "players": list(unique_active_players) # Retourne tous les joueurs uniques (Créateur inclus)
        }), 200
    except Exception as e:
        print(f"[VERIFY PLAYER ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# --- CHANGE SESSION (Renommage de la session personnelle) ---
@app.route("/change_session", methods=["POST"])
def change_session_route():
    data = request.get_json(force=True)
    player_id = (data.get("id") or "").strip()
    old_code = (data.get("old_code") or "").strip() # Code actuel de la session
    new_code = (data.get("new_code") or "").strip() # Nouveau code souhaité

    if not old_code or not new_code or not player_id:
        return jsonify({"status": "error", "message": "Paramètres manquants"}), 400
    
    if old_code == new_code:
        return jsonify({"status": "error", "message": "Le nouveau code doit être différent de l'ancien."}), 400

    # 1. Vérifier si le joueur est le créateur de la session actuelle
    current_session_query = supabase.table("Sessions").select("Code, Creator").eq("Code", old_code).eq("Creator", player_id).execute()
    if not current_session_query.data:
        # Peut-être n'est pas le créateur ou la session n'existe pas
        return jsonify({"status": "error", "message": "Session non trouvée ou vous n'êtes pas le créateur."}), 403

    # 2. Vérifier si le nouveau code est déjà pris
    check_new_code_query = supabase.table("Sessions").select("Code").eq("Code", new_code).execute()
    if check_new_code_query.data:
        return jsonify({"status": "error", "message": f"Le code de session '{new_code}' est déjà utilisé."}), 409

    # 3. Mettre à jour le code de la session (et l'ajouter à la table Player si nécessaire)
    try:
        supabase.table("Sessions").update({"Code": new_code}).eq("Code", old_code).eq("Creator", player_id).execute()
        # Note: Dans la logique du client, le joueur est censé être redirigé vers ce nouveau code.
        print(f"[RENAME] Session {old_code} renommée en {new_code} par {player_id}")
        return jsonify({
            "status": "success", 
            "message": f"Session renommée en '{new_code}'",
            "old_code": old_code, 
            "new_code": new_code
        }), 200
    except Exception as e:
        print(f"[RENAME ERROR] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ----------------------------------------------------------------------
# --- DÉMARRAGE DU SERVEUR ---
# ----------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Serveur démarré sur le port {port}")
    app.run(host="0.0.0.0", port=port)
