import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'chave-ultra-secreta'
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
