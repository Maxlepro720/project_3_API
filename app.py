from flask import Flask, request, jsonify
import hashlib

app = Flask(__name__)

# Chargement des utilisateurs avec mots de passe hachés
users = {}
with open("passwords.txt", "r", encoding="utf-8") as fpass:
    for ligne in fpass:
        ligne = ligne.strip()
        if ligne:
            user_id, hashed_pw = ligne.split(":", 1)  # ligne = "user1:<hash>"
            users[user_id] = hashed_pw

def hash_password(password: str) -> str:
    """Hash en SHA-256 et retourne la chaîne hexadécimale"""
    return hashlib.sha256(password.encode()).hexdigest()

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

    user_id = data.get("id")
    password = data.get("password")
    app.logger.info("user id : ",user_id,"/ password : ", password)

    if not user_id or not password:
        return jsonify({"status": "error", "message": "ID ou mot de passe manquant"}), 400

    hashed_input = hash_password(password)  # hachage avant vérification

    if user_id in users and users[user_id] == hashed_input:
        return jsonify({"status": "success", "message": "Connexion réussie"}), 200
    else:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

