import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:1234@localhost:5432/abrigo-amigo"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
