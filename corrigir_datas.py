from app import app, db, Atendimento  # Importando o app, db e Atendimento de app.py
from datetime import timedelta

def corrigir_datas():
    # Criando um contexto de aplicativo
    with app.app_context():
        # Obtendo todos os atendimentos
        atendimentos = Atendimento.query.all()
        
        for a in atendimentos:
            # Corrigindo a data de criação para GMT-3
            if a.criado_em:
                a.criado_em = a.criado_em - timedelta(hours=3)
            
            # Corrigindo a data de finalização (cancelamento ou concluído) para GMT-3
            if a.finalizado_em:
                a.finalizado_em = a.finalizado_em - timedelta(hours=3)

        # Comitando as alterações no banco de dados
        db.session.commit()
        print("Correção concluída! Horários ajustados para GMT-3.")

if __name__ == "__main__":
    corrigir_datas()
