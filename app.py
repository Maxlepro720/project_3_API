from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)

# Base de données Postgres ou SQLite pour tests
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///test.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 🔹 Table utilisateurs
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

# Création des tables si elles n'existent pas
@app.before_first_request
def create_tables():
    db.create_all()

@app.route("/")
def home():
    return "Bienvenue sur le serveur 🚀"

# 🔹 Signup
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    username = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"status": "error", "message": "Utilisateur déjà existant"}), 409

    user = User(
        username=username,
        password_hash=generate_password_hash(password)
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({"status": "success", "message": f"Utilisateur {username} ajouté"}), 201

# 🔹 Login
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = (data.get("id") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Champs manquants"}), 400

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        return jsonify({"status": "success", "message": "Connexion réussie"}), 200
    else:
        return jsonify({"status": "error", "message": "ID ou mot de passe incorrect"}), 401

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
