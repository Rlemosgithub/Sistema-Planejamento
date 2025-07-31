from flask import Flask, render_template, redirect, url_for, request
from flask_login import LoginManager, login_required, current_user

app = Flask(__name__)
app.secret_key = "troque-para-uma-chave-secreta"

login_manager = LoginManager()
login_manager.login_view = "login"            # rota de login
login_manager.init_app(app)

# quando o usuário não estiver logado e acessar @login_required
@login_manager.unauthorized_handler
def unauthorized_callback():
    return render_template("unauthorized.html"), 401

# --- Rotas de exemplo ---
@app.route("/")
def index():
    return "<a href='/protegido'>Ir para área protegida</a>"

@app.route("/protegido")
@login_required
def protegido():
    return "Esta é uma área protegida."

@app.route("/login")
def login():
    # só para simular, não faz autenticação de verdade
    return "<p>Implemente aqui seu formulário de login.</p>"

if __name__ == "__main__":
    app.run(debug=True)
