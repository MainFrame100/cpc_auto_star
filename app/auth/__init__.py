from flask import Blueprint

auth_bp = Blueprint('auth', __name__)

# Импортируем роуты, чтобы они зарегистрировались в Blueprint
# Делаем это внизу, чтобы избежать циклических импортов
from . import routes 