from flask import Blueprint

main_bp = Blueprint('main', __name__)

# Импортируем маршруты в конце, чтобы избежать циклических зависимостей
from . import routes 