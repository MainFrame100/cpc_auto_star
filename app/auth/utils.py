import os
import requests
from datetime import datetime, timedelta
# УДАЛЕНО: from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask import session, current_app
from .. import db
# УДАЛЕНО: from ..models import Token 

# --- Файл утилит для аутентификации --- 

# ВНИМАНИЕ: Функции get_valid_token, refresh_access_token, restore_session 
# были удалены, так как логика получения и обновления токена 
# теперь инкапсулирована в YandexDirectClient и обработке OAuth callback.

# Если здесь потребуются другие утилиты, связанные с auth (например, проверка state), 
# их можно добавить сюда. 