from flask import Flask
import os
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    from .views import bp
    app.register_blueprint(bp)
    return app
