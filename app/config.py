import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '..', '.env')) # Загружаем .env из корневой папки

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Добавляем чтение ключа шифрования
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')

    # --- Yandex OAuth --- 
    YANDEX_CLIENT_ID = os.environ.get('YANDEX_CLIENT_ID')
    YANDEX_CLIENT_SECRET = os.environ.get('YANDEX_CLIENT_SECRET')
    # URL для запроса авторизации
    YANDEX_AUTHORIZE_URL = 'https://oauth.yandex.ru/authorize'
    # URL для запроса токена
    YANDEX_TOKEN_URL = 'https://oauth.yandex.ru/token'
    # Используем имя функции callback из auth.routes внутри url_for
    # Префикс /auth/ добавляется через Blueprint
    REDIRECT_URI = 'auth.callback' 
    # Запрашиваемые права доступа (полный доступ к Директу)
    YANDEX_SCOPES = ['direct:full_access']

    # --- Yandex Direct API --- 
    # Убираем старый базовый URL
    # DIRECT_API_BASE_URL = os.getenv('DIRECT_API_BASE_URL', 'https://api.direct.yandex.com/json/v5/') 
    DIRECT_API_V5_URL = os.getenv('DIRECT_API_V5_URL', 'https://api.direct.yandex.com/json/v5/')
    DIRECT_API_V501_URL = os.getenv('DIRECT_API_V501_URL', 'https://api.direct.yandex.com/json/v501/')

    # --- Sandbox Specific --- (Переменные для Песочницы, если нужны)
    SANDBOX_YANDEX_CLIENT_ID = os.environ.get('SANDBOX_YANDEX_CLIENT_ID')
    SANDBOX_YANDEX_CLIENT_SECRET = os.environ.get('SANDBOX_YANDEX_CLIENT_SECRET')
    SANDBOX_DIRECT_API_V5_URL = os.getenv('SANDBOX_DIRECT_API_V5_URL', 'https://api-sandbox.direct.yandex.com/json/v5/')
    SANDBOX_DIRECT_API_V501_URL = os.getenv('SANDBOX_DIRECT_API_V501_URL', 'https://api-sandbox.direct.yandex.com/json/v501/') 