# Controle de Horas Trabalhadas

Aplicação Flask + Jinja2 para controle e análise de horas a partir de planilhas Excel.

## Como usar

1. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate    # Linux/macOS
   venv\Scripts\activate     # Windows
   ```
2. Instale dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Defina variável de ambiente (opcional):
   ```bash
   export SECRET_KEY="sua_chave_secreta"
   ```
4. Execute:
   ```bash
   python run.py
   ```
5. Acesse:
   - `/upload` → Enviar planilhas
   - `/` → Dashboard
   - `/validation` → Aba de Validação
