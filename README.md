CRIAR O AMBIENTE:
.\venv\Scripts\Activate.ps1

RODAR APLICACAO:
python app.py

DESATIVAR AMBIENTE:
deactivate


Passo a passo no outro computador:
git clone https://github.com/seu-repo.git
cd projeto
python -m venv venv
source .\venv\Scripts\Activate.ps1
pip install -r requirements.txt


Criar o .env:

cp .env.example .env
# editar o .env com dados locais


Criar o banco automaticamente:

flask db upgrade


Rodar o projeto:

flask run

flask seed