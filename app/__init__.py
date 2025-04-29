import os
import logging # Импортируем logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_migrate import Migrate
from flask_login import LoginManager

# Импортируем класс конфигурации ИЗ ФАЙЛА config.py
from .config import Config

# Загружаем переменные окружения из файла .env в корне проекта
# Лучше делать это до импорта конфигурации и блюпринтов
# load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# --- Конфигурация ---
# УДАЛЕНО: Определение класса Config внутри __init__.py
# class Config:
#     SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(24)
#     SQLALCHEMY_TRACK_MODIFICATIONS = False
#     # Определяем путь к БД здесь, чтобы он был доступен до создания app
#     # Позже будем использовать DATABASE_URL из .env для PostgreSQL
#     SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
#                               f"sqlite:///{os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'instance', 'tokens.db')}"
#
#     # Определяем окружение (production или sandbox)
#     YANDEX_ENV = os.environ.get('YANDEX_ENV', 'sandbox').lower() # По умолчанию песочница
#
#     # URL для API Яндекс.Директ
#     DIRECT_API_V5_URL = os.environ.get('DIRECT_API_V5_URL', 'https://api.direct.yandex.com/json/v5/')
#     DIRECT_API_V501_URL = os.environ.get('DIRECT_API_V501_URL', 'https://api.direct.yandex.com/json/v501/')
#     DIRECT_API_SANDBOX_V5_URL = 'https://api-sandbox.direct.yandex.com/json/v5/'
#     DIRECT_API_SANDBOX_V501_URL = 'https://api-sandbox.direct.yandex.com/json/v501/'
#
#     # URL для Яндекс.OAuth
#     OAUTH_PRODUCTION_URL = 'https://oauth.yandex.ru/'
#     OAUTH_SANDBOX_URL = 'https://oauth.yandex.ru/' # OAuth URL одинаковый для prod и sandbox
#
#     # Устанавливаем актуальные URL в зависимости от окружения
#     if YANDEX_ENV == 'production':
#         DIRECT_API_V5_URL = DIRECT_API_V5_URL
#         DIRECT_API_V501_URL = DIRECT_API_V501_URL
#         OAUTH_BASE_URL = OAUTH_PRODUCTION_URL
#         print(f"*** YANDEX_ENV is '{YANDEX_ENV}'. Using PRODUCTION URLs. ***")
#     else:
#         DIRECT_API_V5_URL = DIRECT_API_SANDBOX_V5_URL
#         DIRECT_API_V501_URL = DIRECT_API_SANDBOX_V501_URL
#         OAUTH_BASE_URL = OAUTH_SANDBOX_URL # В данном случае он совпадает, но структура остается
#         print(f"*** YANDEX_ENV is '{YANDEX_ENV}'. Using SANDBOX URLs. ***")
#
#     # Добавим переменные для OAuth client_id и client_secret
#     YANDEX_CLIENT_ID = os.environ.get('YANDEX_CLIENT_ID')
#     YANDEX_CLIENT_SECRET = os.environ.get('YANDEX_CLIENT_SECRET')
#     YANDEX_SANDBOX_LOGIN = os.environ.get('YANDEX_SANDBOX_LOGIN') # Оставляем на случай отладки

# Инициализация расширений (без app контекста)
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = "Пожалуйста, войдите, чтобы получить доступ к этой странице."
login_manager.login_message_category = "info"

@login_manager.user_loader
def load_user(user_id):
    from .models import User # Теперь основной пользователь это User
    # print(f"[load_user] Attempting to load user with ID: {user_id}")
    try:
        user = User.query.get(int(user_id))
        # print(f"[load_user] Found user: {user.yandex_login if user else 'None'}")
        return user
    except ValueError:
        # print(f"[load_user] Invalid user ID format: {user_id}")
        return None

def configure_logging(app):
    """Настраивает базовое логирование."""
    # Убираем стандартные обработчики Flask, если они есть
    # del app.logger.handlers[:]
    
    log_level = logging.DEBUG if app.config.get('DEBUG') else logging.INFO
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Настройка вывода в stdout
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(logging.Formatter(log_format))
    
    # Добавляем обработчик к логгеру Flask
    # Используем стандартный логгер Python для всего приложения
    # app.logger.addHandler(stream_handler)
    # app.logger.setLevel(log_level)
    
    # Настраиваем корневой логгер
    logging.basicConfig(level=log_level, format=log_format, handlers=[stream_handler])
    
    # Устанавливаем уровень для логгеров библиотек (опционально, чтобы уменьшить шум)
    logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    logging.getLogger('alembic').setLevel(logging.INFO)
    logging.getLogger('werkzeug').setLevel(logging.INFO)

    app.logger.info(f'Logging configured. Level: {logging.getLevelName(log_level)}')

def create_app(config_class=Config):
    """Фабрика для создания экземпляра приложения Flask."""
    app = Flask(__name__,
                instance_relative_config=False, # instance папка больше не нужна с Docker/Postgres
                static_folder='../static', # Указываем путь к static относительно папки app
                template_folder='./templates') # Указываем путь к templates относительно папки app

    # Загружаем конфигурацию из импортированного объекта Config
    app.config.from_object(config_class)

    # УДАЛЕНО: Создание instance папки
    # instance_path = os.path.join(app.root_path, '..', 'instance')
    # try:
    #     os.makedirs(instance_path)
    # except OSError:
    #     pass

    # УДАЛЕНО: Установка URI для SQLite
    # app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(instance_path, 'tokens.db')}"

    # --- НАСТРОЙКА ЛОГИРОВАНИЯ --- 
    configure_logging(app) 
    app.logger.info('Flask application created.')

    # Инициализация расширений с app
    db.init_app(app)
    app.logger.info('Database initialized.')
    migrate.init_app(app, db) # Передаем app и db для Flask-Migrate
    login_manager.init_app(app)
    app.logger.info('LoginManager initialized.')

    # Контекстный процессор (если нужен)
    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow}

    # --- Импорты и регистрация Blueprints ---
    # Импортируем blueprints здесь, чтобы избежать циклических зависимостей
    app.logger.info('Registering blueprints...')
    from .auth import auth_bp
    from .reports import reports_bp
    from .main import main_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(main_bp) # Без префикса
    app.logger.info('Blueprints registered.')

    app.logger.info('Application setup complete.')
    return app 