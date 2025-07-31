import os
from flask import Flask, render_template
from flask_login import LoginManager

login_manager = LoginManager()
login_manager.login_view = 'auth.login'

def create_app():
    app = Flask(__name__)
    app.secret_key = os.urandom(24)

    # 1) Configura o diretório de uploads
    base_dir = os.path.abspath(os.path.dirname(__file__))         # …/Validação/app
    uploads  = os.path.join(os.path.dirname(base_dir), 'uploads') # …/Validação/uploads
    os.makedirs(uploads, exist_ok=True)
    app.config['UPLOAD_FOLDER'] = uploads

    # 2) Inicializa o LoginManager
    login_manager.init_app(app)

    # 3) Handler customizado para acessos não autorizados
    @login_manager.unauthorized_handler
    def unauthorized():
        return render_template('unauthorized.html'), 401

    # 4) Registra o blueprint de autenticação (prefixo definido em auth.py)
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    # 5) Registra o blueprint principal
    from app.views import bp as main_bp
    app.register_blueprint(main_bp)

    return app
