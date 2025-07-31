import os
from flask import Flask, render_template
from flask_login import LoginManager
from app.config import Config

login_manager = LoginManager()
login_manager.login_view = 'auth.login'

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    login_manager.init_app(app)

    # 1) Configura o diretório de uploads
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # 2) Handler customizado para acessos não autorizados
    @login_manager.unauthorized_handler
    def unauthorized():
        return render_template('unauthorized.html'), 401

    # 3) Registra o blueprint de autenticação
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    # 4) Registra o blueprint principal
    from app.views import bp as main_bp
    app.register_blueprint(main_bp)

    return app
