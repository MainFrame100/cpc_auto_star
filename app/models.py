from datetime import datetime, timedelta
from app import db

# Определение модели данных для токенов
class Token(db.Model):
    id = db.Column(db.Integer, primary_key=True) # Первичный ключ
    yandex_login = db.Column(db.String(80), unique=True, nullable=False) # Логин Яндекса, уникальный
    access_token = db.Column(db.String(200), nullable=False) # Токен доступа
    refresh_token = db.Column(db.String(200), nullable=True) # Токен обновления (может отсутствовать)
    expires_at = db.Column(db.DateTime, nullable=False) # Время истечения access_token

    def __repr__(self):
        # Удобное представление объекта для отладки
        return f'<Token for {self.yandex_login}>' 