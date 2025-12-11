class Config:
    SECRET_KEY = "chave-super-secreta"

    SQLALCHEMY_DATABASE_URI = (
        "postgresql://postgres:1234@localhost:5432/abrigo-amigo"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
