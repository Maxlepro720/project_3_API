from flask import Flask, request, jsonify
import hashlib

app = Flask(__name__)

# Chargement des utilisateurs avec mots de passe hachés
users = {}
try:
    with open("passwords.txt", "r", encoding="utf-8") as fpass:
        for ligne in fpass:
            ligne = ligne.strip()
            if ligne:
                user_id, hashed_pw = ligne.split(":", 1)  # ligne = "user1:<hash>"
                users[user_id] = hashed_pw
except FileNotFoundError:
    pass  # si le fichier n'existe pas encore

def hash_password(password: str) -> str:
    """Hash en SHA-256 et retourne la chaîne hexadécimale"""
    return hashlib.sha256(password.encode()).hexdigest()

def save_user(user_id: str, hashed_pw: str):
    """Ajoute un utilisateur dans passwords.txt"""
    with open("passwords.txt", "a", encoding="utf-8") as f:
        f.write(f"{user_id}:{hashed_pw}\n")

@app.route("/")
def home():
    return "Bienvenue sur le serveur 🚀"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return jsonify({"status": "info", "message": "Envoyez vos identifiants avec POST"}), 200

    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Données manquantes"}), 400

    user_id = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()
    app.logger.info(f"user id: {user_id} / password: {password}")

    if not user_id or not password:
        return jsonify({"status": "error", "message": "ID ou mot de passe manquant"}), 400

    hashed_input = hash_password(password)
    app.logger.info(f"user id: {user_id} / hashed password: {hashed_input}")

    if user_id in users and users[user_id] == hashed_input:
        return jsonify({"status": "success", "message": "Connexion réussie"}), 200
    else:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

# 🔹 Nouveau endpoint signup
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    user_id = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not user_id or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    if user_id in users:
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    hashed_pw = hash_password(password)
    save_user(user_id, hashed_pw)
    users[user_id] = hashed_pw  # mise à jour en mémoire

    app.logger.info(f"Nouvel utilisateur ajouté: {user_id}")
    return jsonify({"status": "success", "message": f"Utilisateur {user_id} ajouté"}), 201

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

