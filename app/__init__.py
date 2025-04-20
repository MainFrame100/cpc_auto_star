import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from datetime import datetime

# Загружаем переменные окружения из файла .env в корне проекта
# Лучше делать это до импорта конфигурации и блюпринтов
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Инициализация расширений (без привязки к app)
db = SQLAlchemy()

def create_app():
    """Фабрика для создания экземпляра приложения Flask."""
    # Указываем путь к папке static относительно корня проекта
    app = Flask(__name__, 
                instance_relative_config=True,
                static_folder='../static')

    # --- Конфигурация приложения --- 
    # Загрузка секретного ключа
    # В реальном приложении лучше использовать более безопасные способы
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))
    
    # Конфигурация SQLAlchemy
    # Используем instance папку для БД
    db_path = os.path.join(app.instance_path, 'tokens.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Убедимся, что папка instance существует
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass # Папка уже существует

    # --- Инициализация расширений --- 
    db.init_app(app)

    # === Контекстный процессор для добавления datetime в шаблоны ===
    @app.context_processor
    def inject_now():
        # Передаем в шаблон переменную 'now', которая является функцией datetime.utcnow
        # Можно использовать datetime.now(), если не нужна привязка к UTC
        return {'now': datetime.utcnow}
    # ================================================================

    # --- Регистрация Blueprints --- 
    from .auth import auth_bp # Импортируем внутри функции
    app.register_blueprint(auth_bp)

    from .reports import reports_bp # <<< ДОБАВИТЬ ЭТО
    app.register_blueprint(reports_bp) # <<< ДОБАВИТЬ ЭТО

    # --- (Опционально) Создание таблиц БД --- 
    # Можно добавить команду Flask CLI для этого, 
    # но для простоты пока оставим возможность создания при первом запуске
    with app.app_context():
        db.create_all()
        print(f"База данных проверена/создана по пути: {db_path}")

    return app 