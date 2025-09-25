from flask import Flask, request, jsonify

app = Flask(__name__)

users = {}
with open("passwords.txt", "r", encoding="utf-8") as fpass:
    for ligne in fpass:
        ligne = ligne.strip()
        if ligne:
            user_id, password = ligne.split(":", 1)  # sépare sur le premier :
            users[user_id] = password

@app.route("/")
def home():
    return "Bienvenue sur le serveur 🚀"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        # Optionnel : renvoyer un message pour tester dans le navigateur
        return jsonify({"status": "info", "message": "Envoyez vos identifiants avec POST"}), 200

    # POST : récupération du JSON
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Données manquantes"}), 400

    user_id = data.get("id")
    password = data.get("password")

    if not user_id or not password:
        return jsonify({"status": "error", "message": "ID ou mot de passe manquant"}), 400

    if user_id in users and users[user_id] == password:
        return jsonify({"status": "success", "message": "Connexion réussie"}), 200
    else:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
