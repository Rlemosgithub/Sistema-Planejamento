# Controle de Horas Trabalhadas

Aplicação Flask + Jinja2 para controle e análise de horas a partir de planilhas Excel.

## 🚀 Deploy Automático (GitHub → Heroku)

1. Configure no GitHub os *Secrets*:
   - `HEROKU_API_KEY`
   - `HEROKU_APP_NAME`
   - `HEROKU_EMAIL`
2. Dê um push na branch `main`.
3. O GitHub Actions vai construir e publicar sua app no Heroku.
4. Acesse `https://<HEROKU_APP_NAME>.herokuapp.com`.

## 🚗 Teste local

```bash
# Crie e ative um virtualenv
python -m venv venv
source venv/bin/activate    # Linux/macOS
venv\Scripts\activate     # Windows

# Instale dependências
pip install -r requirements.txt

# Copie .env.example para .env e ajuste
cp .env.example .env

# Execute localmente
python run.py
```

## Endpoints

- `/upload` → Enviar planilhas
- `/` → Dashboard
- `/validation` → Aba de Validação
