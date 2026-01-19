from flask import Flask, render_template, request, redirect, url_for, flash, Blueprint, abort, jsonify, make_response
from werkzeug.security import check_password_hash, generate_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_required, login_user, logout_user, UserMixin, current_user
from config import Config
from datetime import datetime
from sqlalchemy import text
from functools import wraps
import pytz
from urllib.parse import quote
import pdfkit
import pandas as pd
from io import BytesIO
from io import BytesIO
from flask_migrate import Migrate
from dotenv import load_dotenv
load_dotenv()


# ---------------- TIMEZONE ------------------


tz = pytz.timezone("America/Sao_Paulo")


# ---------------- APP / CONFIG ------------------

app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ---------------- USER LOADER ------------------

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

# ---------------- MODELAGEM DO BANCO ------------------

class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    login = db.Column(db.String(50), unique=True, nullable=False)
    senha = db.Column(db.Text, nullable=False)
    perfil = db.Column(db.String(20), nullable=False)  # Atendimento / Operador
    # Se quiser usar current_user.nome, adicione o campo nome
    nome = db.Column(db.String(100), nullable=True)


class Abrigo(db.Model):
    __tablename__ = "abrigos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # Ativo / Inativo
    logradouro = db.Column(db.String(200))
    bairro = db.Column(db.String(120))
    cep = db.Column(db.String(20))
    cidade = db.Column(db.String(100))
    estado = db.Column(db.String(2))
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)


    def __repr__(self):
        return f"<Abrigo {self.nome}>"


class Atendimento(db.Model):
    __tablename__ = "atendimentos"

    id = db.Column(db.Integer, primary_key=True)
    solicitante = db.Column(db.String(255), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    abrigo_id = db.Column(db.Integer, db.ForeignKey("abrigos.id"), nullable=False)
    descricao = db.Column(db.String(1000), nullable=False)

    operador_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    operador_nome = db.Column(db.String(100), nullable=False)

    # Novas colunas
    criado_em = db.Column(db.DateTime, default=lambda: datetime.now(tz))
    finalizado_em = db.Column(db.DateTime)

    justificativa_cancelamento = db.Column(db.Text)
    conclusao = db.Column(db.Text)

    status = db.Column(db.String(20), default="Aberto", nullable=False)  # Novo campo de status
    editado_por = db.Column(db.String(100))  # quem editou por último, NULL se nunca editado
    ultima_atualizacao = db.Column(db.DateTime(timezone=True),default=lambda: datetime.now(pytz.timezone('America/Sao_Paulo')))

    abrigo = db.relationship("Abrigo")
    operador = db.relationship("Usuario", foreign_keys=[operador_id])

# ----------------- REGISTRAR LOG -----------

def registrar_log(acao, descricao=None, usuario=None):
    if usuario is None and current_user.is_authenticated:
        usuario = current_user

    log = LogSistema(
        usuario_id=usuario.id if usuario else None,
        usuario_login=usuario.login if usuario else "Sistema",
        acao=acao,
        descricao=descricao,
        rota=request.path if request else None,
        metodo=request.method if request else None,
        ip=request.remote_addr if request else None
    )

    db.session.add(log)
    db.session.commit()

class LogSistema(db.Model):
    __tablename__ = "logs_sistema"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    usuario_login = db.Column(db.String(50))
    acao = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text)
    rota = db.Column(db.String(200))
    metodo = db.Column(db.String(10))
    ip = db.Column(db.String(45))
    data_hora = db.Column(
        db.DateTime,
        default=lambda: datetime.now(pytz.timezone("America/Sao_Paulo"))
    )


# -----------------DECORADOR DE PERMISSÃO-----------
def requer_perfil(*perfis):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):

            if not current_user.is_authenticated:
                return redirect(url_for("login"))

            # Se admin, libera tudo
            if current_user.perfil == "Admin":
                return func(*args, **kwargs)

            # Se não for admin, verifica se o perfil dele está na lista
            if current_user.perfil not in perfis:
                abort(403)  # Acesso proibido

            return func(*args, **kwargs)
        return wrapper
    return decorator


# ---------------- ROTAS DE LOGIN ------------------

from flask import flash

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_digitado = request.form["login"]
        senha_digitada = request.form["senha"]

        # Busca pelo login apenas
        user = Usuario.query.filter_by(login=login_digitado).first()

        if user and check_password_hash(user.senha, senha_digitada):
            login_user(user)
            registrar_log("Login", f"Usuário {user.login} realizou login")
            return redirect(url_for("principal"))
        else:
            flash("Usuário ou senha incorretos!", "error")
            return redirect(url_for("login"))

    return render_template("login.html")


# app.py, na rota principal
@app.route("/principal")
@login_required
def principal():
    # Estatísticas...
    total_atendimentos = Atendimento.query.count()
    abertos = Atendimento.query.filter_by(status="Aberto").count()
    em_atendimento = Atendimento.query.filter_by(status="Em Atendimento").count()
    finalizados = Atendimento.query.filter_by(status="Atendido").count()
    cancelados = Atendimento.query.filter_by(status="Cancelado").count()

    # Últimos 5 atendimentos
    atendimentos_recentes = Atendimento.query.order_by(Atendimento.criado_em.desc()).limit(5).all()

    # CONVERTER abrigos para lista de dicionários simples
    abrigos = Abrigo.query.all()
    abrigos_json = [
        {
            "id": a.id,
            "nome": a.nome,
            "status": a.status,
            "latitude": a.latitude,
            "longitude": a.longitude,
            "logradouro": a.logradouro,
            "bairro": a.bairro,
            "cep": a.cep
        } for a in abrigos
    ]

    return render_template(
        "home.html",
        usuario=current_user,
        total_atendimentos=total_atendimentos,
        abertos=abertos,
        em_atendimento=em_atendimento,
        finalizados=finalizados,
        cancelados=cancelados,
        atendimentos_recentes=atendimentos_recentes,
        abrigos=abrigos_json   # 👈 usar a lista serializável
    )




# ---------------- ROTAS DE USUARIOS ------------------
@app.route("/config/usuarios")
@login_required
def listar_usuarios():
    usuarios = Usuario.query.all()
    return render_template("usuarios.html", usuarios=usuarios)


@app.route("/config/usuarios/add", methods=["GET", "POST"])
@login_required
def add_usuario():
    if request.method == "POST":
        login_digitado = request.form.get("login")
        senha_digitada = request.form.get("senha")
        perfil = request.form.get("perfil")
        nome = request.form.get("nome")

        if not all([login_digitado, senha_digitada, perfil]):
            flash("Preencha todos os campos obrigatórios!", "error")
            return redirect(url_for("add_usuario"))

        # Verifica login duplicado
        if Usuario.query.filter_by(login=login_digitado).first():
            flash("Login já existe! Escolha outro.", "error")
            return redirect(url_for("add_usuario"))

        novo = Usuario(
            login=login_digitado,
            senha=generate_password_hash(senha_digitada),
            perfil=perfil,
            nome=nome
        )
        db.session.add(novo)
        db.session.commit()

        registrar_log("Cadastro de usuário", f"Usuário criado: {login_digitado}")

        flash("Usuário criado com sucesso!", "success")
        return redirect(url_for("listar_usuarios"))

    return render_template("usuarios_add.html", action="add", usuario=None)


@app.route("/config/usuarios/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_usuario(id):
    usuario = Usuario.query.get_or_404(id)

    if request.method == "POST":
        usuario.login = request.form.get("login")
        usuario.perfil = request.form.get("perfil")
        usuario.nome = request.form.get("nome")

        nova_senha = request.form.get("senha")

        # 🔥 Só muda a senha se o campo não estiver vazio
        if nova_senha and nova_senha.strip() != "":
            usuario.senha = generate_password_hash(nova_senha)

        db.session.commit()
        registrar_log("Edição de usuário", f"Usuário editado: {usuario.login}")

        flash("Usuário atualizado com sucesso!", "success")
        return redirect(url_for("listar_usuarios"))

    return render_template("usuarios_edit.html", action="edit", usuario=usuario)



@app.route('/usuarios/delete/<int:id>', methods=['POST'])
@login_required
def delete_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    db.session.delete(usuario)
    db.session.commit()

    registrar_log("Exclusão de usuário", f"Usuário excluído: {usuario.login}")
    
    flash('Usuário excluído com sucesso!', 'success')
    return redirect(url_for('listar_usuarios'))


# ---------------- ROTAS - OPERADOR/ATENDIMENTO ------------------

@app.route("/operador/chamados")
@login_required
def operador_chamados():
    chamados = Atendimento.query.all()
    return render_template("operador_chamados.html", chamados=chamados)


@app.route('/operador/novo-chamado', methods=['GET', 'POST'])
@login_required
def novo_chamado():
    if request.method == 'POST':
        solicitante = request.form.get('solicitante')
        telefone = request.form.get('telefone')
        abrigo_id = request.form.get('abrigo')
        descricao = request.form.get('descricao')

        if not all([solicitante, telefone, abrigo_id, descricao]):
            flash('Todos os campos são obrigatórios!', 'error')
            return redirect(url_for('novo_chamado'))

        atendimento = Atendimento(
            solicitante=solicitante,
            telefone=telefone,
            abrigo_id=abrigo_id,
            descricao=descricao,
            operador_id=current_user.id,
            operador_nome=current_user.nome or current_user.login,
            status="Aberto" # Definindo o status como "Aberto"
        )

        db.session.add(atendimento)
        db.session.commit()

        registrar_log("Criar Atendimento",f"Atendimento criado para '{solicitante}' (Abrigo ID {abrigo_id})")

        flash('Atendimento salvo com sucesso!', 'success')
        return redirect(url_for('atendimentos'))

    abrigos = Abrigo.query.filter_by(status="Ativo").all()

    return render_template('operador_novo_chamado.html', abrigos=abrigos)


@app.route("/api/abrigo/<id>")
def api_abrigo(id):
    abrigo = Abrigo.query.get(id)

    if abrigo:
        return {
            "logradouro": abrigo.logradouro,
            "bairro": abrigo.bairro,
            "cep": abrigo.cep
        }

    return {"erro": "Abrigo não encontrado"}, 404


@app.route("/atendimentos")
@login_required
def atendimentos():
    chamados = Atendimento.query.all()
    return render_template("atendimentos.html", chamados=chamados)


# ----------------- ROTAS - ATENDIMENTO EDIT/VIEW ------------------

@app.route("/atendimento/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar_atendimento(id):
    atendimento = Atendimento.query.get_or_404(id)

    if request.method == "POST":
        if atendimento.status != 'Aberto':
            flash("Este chamado não pode ser editado porque não está aberto.", "error")
            return redirect(url_for("atendimentos"))

        # Atualiza apenas os campos editáveis
        atendimento.solicitante = request.form.get("solicitante")
        atendimento.telefone = request.form.get("telefone")
        atendimento.abrigo_id = request.form.get("abrigo")
        atendimento.descricao = request.form.get("descricao")
        atendimento.ultima_atualizacao = datetime.now(pytz.timezone('America/Sao_Paulo'))

        db.session.commit()

        registrar_log("Editar Atendimento",f"Atendimento #{atendimento.id} atualizado")

        flash("Atendimento atualizado com sucesso!", "success")
        return redirect(url_for("atendimentos"))

    abrigos = Abrigo.query.filter_by(status="Ativo").all()
    return render_template("operador_editar_chamado.html", atendimento=atendimento, abrigos=abrigos)




@app.route("/atendimento/view/<int:id>")
@login_required
def view_atendimento(id):
    atendimento = Atendimento.query.get_or_404(id)
    return render_template("atendimento_view.html", atendimento=atendimento)

# ---------------- ROTAS - ABRIGOS ------------------

@app.route("/config/abrigos/add", methods=["GET", "POST"])
@login_required
def add_abrigo():
    if request.method == "POST":
        nome = request.form.get("nome")
        cep = request.form.get("cep")
        logradouro = request.form.get("logradouro")
        bairro = request.form.get("bairro")
        cidade = request.form.get("cidade")
        estado = request.form.get("estado")

        novo_abrigo = Abrigo(
            nome=nome,
            cep=cep,
            logradouro=logradouro,
            bairro=bairro,
            cidade=cidade,
            estado=estado,
            status=request.form.get("status"),
            latitude=request.form.get("latitude") or None,
            longitude=request.form.get("longitude") or None
        )

        db.session.add(novo_abrigo)
        db.session.commit()

        registrar_log("Criar Abrigo", f"Abrigo '{novo_abrigo.nome}' cadastrado")


        # ====== TOAST ======
        flash("Abrigo cadastrado com sucesso!", "success")

        return redirect(url_for("listar_abrigos"))

    return render_template("config_abrigos_add.html", action="add", abrigo=None)


@app.route("/config/abrigos/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit_abrigo(id):
    abrigo = Abrigo.query.get_or_404(id)

    if request.method == "POST":
        abrigo.nome = request.form.get("nome")
        abrigo.cep = request.form.get("cep")
        abrigo.logradouro = request.form.get("logradouro")
        abrigo.bairro = request.form.get("bairro")
        abrigo.cidade = request.form.get("cidade")
        abrigo.estado = request.form.get("estado")
        abrigo.status = request.form.get("status")
        abrigo.latitude = request.form.get("latitude") or None
        abrigo.longitude = request.form.get("longitude") or None

        db.session.commit()

        registrar_log("Editar Abrigo", f"Abrigo '{abrigo.nome}' atualizado")

        # ====== TOAST ======
        flash("Abrigo atualizado com sucesso!", "success")

        return redirect(url_for("listar_abrigos"))

    return render_template("config_abrigos_add.html", action="edit", abrigo=abrigo)


@app.route("/config/abrigos/view/<int:id>")
@login_required
def view_abrigo(id):
    abrigo = Abrigo.query.get_or_404(id)
    return render_template("abrigo_view.html", abrigo=abrigo)


@app.route("/config/abrigos")
@login_required
def listar_abrigos():
    abrigos = Abrigo.query.all()
    return render_template("config_abrigos.html", abrigos=abrigos)


# ----------------- INICIAR ATENDIMENTOS ------------------
@app.route("/atendimento/iniciar/<int:id>")
@login_required
def iniciar_atendimento(id):
    if current_user.perfil not in ['Admin', 'Atendente']:
        flash("Você não tem permissão para iniciar atendimentos.", "error")
        return redirect(url_for("atendimentos"))

    atendimento = Atendimento.query.get_or_404(id)
    return render_template("atendimento_view.html", atendimento=atendimento, modo_inicio=True)


@app.post("/finalizar_atendimento/<int:id>")
@login_required
def finalizar_atendimento_ajax(id):
    data = request.get_json()
    conclusao = data.get("conclusao")
    senha = data.get("senha")

    if not check_password_hash(current_user.senha, senha):
        return jsonify({"success": False, "error": "Senha incorreta."})

    atendimento = Atendimento.query.get(id)
    if not atendimento:
        return jsonify({"success": False, "error": "Atendimento não encontrado."})

    atendimento.conclusao = conclusao
    atendimento.status = "Atendido"

    # Quando o status for alterado para "Atendido" ou "Cancelado"
    atendimento.finalizado_em = datetime.utcnow()  # Salva a data e hora atual
    
    db.session.commit()

    return jsonify({"success": True})



@app.route("/atendimento/cancelar/<int:id>/ajax", methods=["POST"])
@login_required
def cancelar_atendimento_ajax(id):
    atendimento = Atendimento.query.get_or_404(id)
    data = request.get_json()

    justificativa = data.get("justificativa", "").strip()
    senha = data.get("senha", "").strip()

    if not justificativa or not senha:
        return jsonify({"success": False, "error": "Justificativa e senha são obrigatórios."})

    # Valida senha do usuário logado
    if not check_password_hash(current_user.senha, senha):
        return jsonify({"success": False, "error": "Senha incorreta."})

    # Atualiza status
    atendimento.status = "Cancelado"
    atendimento.justificativa_cancelamento = justificativa

    # Quando o status for alterado para "Atendido" ou "Cancelado"
    atendimento.finalizado_em = datetime.utcnow()  # Salva a data e hora atual
    
    db.session.commit()

    
    return jsonify({"success": True})

# ------------------ Rota Flask para atualizar status e abrir WhatsApp ------------------

@app.route("/atendimento/whatsapp/<int:id>", methods=["GET"])
@login_required
def iniciar_atendimento_whatsapp(id):
    atendimento = Atendimento.query.get_or_404(id)

    if current_user.perfil not in ['Admin', 'Atendente']:
        flash("Você não tem permissão para iniciar atendimentos.", "error")
        return redirect(url_for("atendimentos"))

    # Atualiza status
    atendimento.status = "Em Atendimento"
    db.session.commit()

    # Prepara todas as informações
    abrigo = atendimento.abrigo
    texto = (
        f"Atendimento ID: {atendimento.id}\n"
        f"Solicitante: {atendimento.solicitante}\n"
        f"Contato: {atendimento.telefone}\n"
        f"Abrigo: {abrigo.nome}\n"
        f"Endereço: {abrigo.logradouro}, {abrigo.bairro}, CEP {abrigo.cep}\n"
        f"Latitude: {abrigo.latitude}\n"
        f"Longitude: {abrigo.longitude}\n"
        f"Descrição: {atendimento.descricao}\n"
        f"Status: {atendimento.status}\n"
        f"Mapa: https://www.google.com/maps/search/?api=1&query={abrigo.latitude},{abrigo.longitude}"
    )

    # URL encode
    url_whatsapp = f"https://api.whatsapp.com/send?text={quote(texto)}"

    return redirect(url_whatsapp)



# ------------------ ROTAS DE EXPORTAÇAO ------------------

@app.route("/atendimentos/export/whatsapp/<int:id>")
@login_required
def export_whatsapp(id):
    atendimento = Atendimento.query.get_or_404(id)
    mensagem = f"Atendimento #{atendimento.id} - Cliente: {atendimento.cliente_nome}\nStatus: {atendimento.status}\nDescrição: {atendimento.descricao}"
    # URL encode e direciona para WhatsApp Web
    import urllib.parse
    url = f"https://wa.me/?text={urllib.parse.quote(mensagem)}"
    return redirect(url)

@app.route("/atendimentos/export/pdf/<int:id>")
@login_required
def export_pdf(id):
    atendimento = Atendimento.query.get_or_404(id)
    # Aqui você pode gerar um PDF usando ReportLab ou WeasyPrint
    # Exemplo simplificado:
    from flask import make_response
    pdf_content = f"Atendimento #{atendimento.id}\nCliente: {atendimento.cliente_nome}\nStatus: {atendimento.status}\nDescrição: {atendimento.descricao}"
    response = make_response(pdf_content)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=atendimento_{atendimento.id}.pdf'
    return response

@app.route('/atendimento/<int:id>/pdf')
def exportar_atendimento_pdf(id):
    atendimento = Atendimento.query.get_or_404(id)

    # Passa informações de datas já formatadas para o template
    criado_em = atendimento.criado_em.strftime('%d/%m/%Y %H:%M:%S') if atendimento.criado_em else "N/A"
    finalizado_em = atendimento.finalizado_em.strftime('%d/%m/%Y %H:%M:%S') if atendimento.finalizado_em else "N/A"

    html = render_template(
        "atendimento_pdf.html",
        atendimento=atendimento,
        criado_em=criado_em,
        finalizado_em=finalizado_em
    )

    # Gera PDF em memória
    pdf = pdfkit.from_string(html, False)

    # Retorna PDF como resposta HTTP
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=atendimento_{id}.pdf'
    return response

# --------------- LOGS ------------------



@app.route("/logs")
@login_required
@requer_perfil("Admin")
def logs_sistema():
    logs = LogSistema.query.order_by(LogSistema.data_hora.desc()).limit(500).all()
    return render_template("logs.html", logs=logs)


@app.route("/logs/export/pdf")
@login_required
@requer_perfil("Admin")
def export_logs_pdf():
    logs = LogSistema.query.order_by(LogSistema.data_hora.desc()).all()

    html = render_template("logs_pdf.html", logs=logs)
    pdf = pdfkit.from_string(html, False)

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'inline; filename=logs.pdf'
    return response


@app.route("/logs/export/xlsx")
@login_required
@requer_perfil("Admin")
def export_logs_xlsx():
    logs = LogSistema.query.order_by(LogSistema.data_hora.desc()).all()
    data = [{
        "ID": l.id,
        "Usuário": l.usuario_login,
        "Ação": l.acao,
        "Descrição": l.descricao,
        "Rota": l.rota,
        "Método": l.metodo,
        "IP": l.ip,
        "Data/Hora": l.data_hora.strftime("%d/%m/%Y %H:%M:%S")
    } for l in logs]

    df = pd.DataFrame(data)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return make_response(
        (output.read(), {
            "Content-Disposition": "attachment; filename=logs.xlsx",
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        })
    )


# ---------------- LOGOUT ------------------

@app.route("/logout")
@login_required
def logout():
    usuario = current_user  # captura ANTES

    registrar_log(
        acao="Logout",
        descricao=f"Usuário {usuario.login} realizou logout",
        usuario=usuario
    )

    logout_user()
    return redirect(url_for("login"))




# ---------------- COMANDOS CLI ------------------

@app.cli.command("create-db")
def create_db():
    db.create_all()
    print("Banco criado com sucesso!")


# ---------------- RUN ------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )

# ---------------- SEED ------------------

@app.cli.command("seed")
def seed():
    from werkzeug.security import generate_password_hash

    admin = Usuario(
        login="admin",
        senha=generate_password_hash("123"),
        perfil="Admin",
        nome="Administrador"
    )

    db.session.add(admin)
    db.session.commit()
    print("Seed executado")