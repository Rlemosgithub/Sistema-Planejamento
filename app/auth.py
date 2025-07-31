import os
import json
from functools import wraps

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    abort
)
from flask_login import (
    login_user,
    logout_user,
    login_required,
    UserMixin,
    current_user
)
from werkzeug.security import check_password_hash

from app import login_manager

bp = Blueprint('auth', __name__, url_prefix='/auth')

# --- Classe de Usuário para Flask-Login ---
class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = str(id)
        self.username = username
        self.role = role

# --- Carrega lista de usuários de users.json ---
def load_users():
    # tenta primeiro em UPLOAD_FOLDER
    upload_dir = current_app.config.get('UPLOAD_FOLDER', '')
    path = os.path.join(upload_dir, 'users.json')
    # se não existir lá, busca na raiz do projeto (um nível acima de app/)
    if not os.path.exists(path):
        path = os.path.abspath(
            os.path.join(current_app.root_path, '..', 'users.json')
        )
    with open(path, encoding='utf-8') as f:
        return json.load(f)

# --- User loader do Flask-Login ---
@login_manager.user_loader
def load_user(user_id):
    users = load_users()
    u = next((x for x in users if str(x['id']) == user_id), None)
    if not u:
        return None
    return User(u['id'], u['username'], u['role'])

# --- Rota de login ---
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            users = load_users()
        except Exception as e:
            flash(f"Erro ao ler usuários: {e}", 'danger')
            return render_template('login.html')

        u = next((x for x in users if x['username'] == username), None)
        if not u:
            flash('Usuário ou senha inválidos', 'danger')
            return render_template('login.html')

        stored = u.get('password', '')
        # tenta hash Werkzeug
        if stored.startswith('pbkdf2:'):
            valid = check_password_hash(stored, password)
        else:
            # permite texto puro para testes
            valid = (password == stored)

        if not valid:
            flash('Usuário ou senha inválidos', 'danger')
            return render_template('login.html')

        user = User(u['id'], u['username'], u['role'])
        login_user(user)
        flash('Login efetuado com sucesso', 'success')
        return redirect(url_for('main.dashboard'))

    return render_template('login.html')

# --- Rota de logout ---
@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Desconectado', 'info')
    return redirect(url_for('auth.login'))

# --- Decorator para roles ---
def roles_required(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return wrapper
