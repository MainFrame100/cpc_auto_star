from flask import Blueprint

reports_bp = Blueprint('reports', __name__, url_prefix='/reports') # Добавим префикс URL

# Импортируем роуты
from . import routes 