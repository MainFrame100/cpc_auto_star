import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from datetime import datetime
from flask_migrate import Migrate
from flask_login import LoginManager

# Загружаем переменные окружения из файла .env в корне проекта
# Лучше делать это до импорта конфигурации и блюпринтов
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# --- Конфигурация ---
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(24)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Определяем путь к БД здесь, чтобы он был доступен до создания app
    # Позже будем использовать DATABASE_URL из .env для PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                              f"sqlite:///{os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'instance', 'tokens.db')}"

    # Определяем окружение (production или sandbox)
    YANDEX_ENV = os.environ.get('YANDEX_ENV', 'sandbox').lower() # По умолчанию песочница

    # URL для API Яндекс.Директ
    DIRECT_API_V5_URL = os.environ.get('DIRECT_API_V5_URL', 'https://api.direct.yandex.com/json/v5/')
    DIRECT_API_V501_URL = os.environ.get('DIRECT_API_V501_URL', 'https://api.direct.yandex.com/json/v501/')
    DIRECT_API_SANDBOX_V5_URL = 'https://api-sandbox.direct.yandex.com/json/v5/'
    DIRECT_API_SANDBOX_V501_URL = 'https://api-sandbox.direct.yandex.com/json/v501/'

    # URL для Яндекс.OAuth
    OAUTH_PRODUCTION_URL = 'https://oauth.yandex.ru/'
    OAUTH_SANDBOX_URL = 'https://oauth.yandex.ru/' # OAuth URL одинаковый для prod и sandbox

    # Устанавливаем актуальные URL в зависимости от окружения
    if YANDEX_ENV == 'production':
        DIRECT_API_V5_URL = DIRECT_API_V5_URL
        DIRECT_API_V501_URL = DIRECT_API_V501_URL
        OAUTH_BASE_URL = OAUTH_PRODUCTION_URL
        print(f"*** YANDEX_ENV is '{YANDEX_ENV}'. Using PRODUCTION URLs. ***")
    else:
        DIRECT_API_V5_URL = DIRECT_API_SANDBOX_V5_URL
        DIRECT_API_V501_URL = DIRECT_API_SANDBOX_V501_URL
        OAUTH_BASE_URL = OAUTH_SANDBOX_URL # В данном случае он совпадает, но структура остается
        print(f"*** YANDEX_ENV is '{YANDEX_ENV}'. Using SANDBOX URLs. ***")

    # Добавим переменные для OAuth client_id и client_secret
    YANDEX_CLIENT_ID = os.environ.get('YANDEX_CLIENT_ID')
    YANDEX_CLIENT_SECRET = os.environ.get('YANDEX_CLIENT_SECRET')
    YANDEX_SANDBOX_LOGIN = os.environ.get('YANDEX_SANDBOX_LOGIN') # Оставляем на случай отладки

# Инициализация расширений
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

# user_loader должен остаться здесь, т.к. он привязан к login_manager
@login_manager.user_loader
def load_user(user_id):
    # Импортируем модель здесь, т.к. она нужна user_loader'у
    # Это безопасно, т.к. user_loader вызывается уже после создания app
    from .models import Token
    print(f"[load_user] Attempting to load user with ID (yandex_login): {user_id}")
    token = Token.query.filter_by(yandex_login=user_id).first()
    if token:
        print(f"[load_user] Found token for {user_id}. Returning token object.")
    else:
        print(f"[load_user] Token not found for {user_id}. Returning None.")
    return token

def create_app(config_class=Config):
    """Фабрика для создания экземпляра приложения Flask."""
    app = Flask(__name__,
                instance_relative_config=True,
                static_folder='../static')

    app.config.from_object(config_class)

    instance_path = os.path.join(app.root_path, '..', 'instance')
    try:
        os.makedirs(instance_path)
    except OSError:
        pass

    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(instance_path, 'tokens.db')}"

    # Инициализация расширений с app
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Контекстный процессор
    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow}

    # --- Импорты и регистрация Blueprints (Перемещено сюда) ---
    from .auth import auth_bp
    from .reports import reports_bp
    from .main import main_bp # Предполагаем, что есть main blueprint

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(main_bp)

    # --- Восстанавливаем сессии при запуске (Перемещено сюда) ---
    with app.app_context():
        # Импортируем здесь, т.к. нужны модели и утилиты
        from .models import Token
        from .auth.utils import restore_session

        print("Attempting to restore sessions...") # Добавим лог
        try:
            tokens = Token.query.all()
            print(f"Found {len(tokens)} tokens to potentially restore.")
            for token in tokens:
                print(f"Restoring session for: {token.yandex_login}")
                restored = restore_session(token.yandex_login, app)
                print(f"Session restored for {token.yandex_login}: {restored}")
        except Exception as e:
             # Ловим ошибки здесь, чтобы сервер не падал, если БД еще не готова
             print(f"Error during session restoration: {e}")
             print("This might be normal if running migrations for the first time.")


    # --- Создание таблиц БД (можно оставить здесь или вынести в команду CLI) ---
    with app.app_context():
        try:
            db.create_all()
            print(f"Database tables checked/created at: {app.config['SQLALCHEMY_DATABASE_URI']}")
        except Exception as e:
            print(f"Error during db.create_all(): {e}")
            # Это может произойти, если есть проблемы с подключением к БД или миграциями


    return app 