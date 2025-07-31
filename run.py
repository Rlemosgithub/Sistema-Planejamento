import os
import sys

# 1) Descobre onde está este run.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2) Coloca esse diretório no sys.path, para que o 'app' seja encontrado
sys.path.insert(0, BASE_DIR)

# 3) Agora sim podemos importar create_app do pacote app
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=(os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
    )
