import os
import logging # Импортируем logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_migrate import Migrate
from flask_login import LoginManager
from cryptography.fernet import Fernet
from logging.handlers import RotatingFileHandler

# Импортируем класс конфигурации ИЗ ФАЙЛА config.py
from .config import Config



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

    # --- Настройка логирования --- 
    # Устанавливаем базовый уровень логирования для приложения
    app.logger.setLevel(logging.INFO) 
    
    # Логирование в консоль (остается по умолчанию, но можно настроить формат)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO) # Уровень для консоли
    stream_formatter = logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )
    stream_handler.setFormatter(stream_formatter)
    # Удаляем стандартный обработчик Flask, если он есть, и добавляем свой
    # (можно пропустить, если стандартный устраивает)
    # if app.logger.hasHandlers():
    #     app.logger.handlers.clear()
    # app.logger.addHandler(stream_handler)

    # Логирование в файл (только если не в режиме отладки)
    app.logger.info(f"Проверка условий для файлового логирования: app.debug={app.debug}, app.testing={app.testing}")
    if app.debug and not app.testing:
        # Используем правильный разделитель для os.path.join
        logs_dir = os.path.join(app.root_path, '..', 'logs') 
        app.logger.info(f"Целевая папка для логов: {logs_dir}")
        
        if not os.path.exists(logs_dir):
            app.logger.info(f"Папка {logs_dir} не существует, попытка создать...")
            try:
                os.makedirs(logs_dir)
                app.logger.info(f"Создана папка для логов: {logs_dir}")
            except OSError as e:
                 app.logger.error(f"Ошибка создания папки логов {logs_dir}: {e}. Проверьте права доступа.")
                 logs_dir = None # Сбрасываем путь, чтобы не пытаться создать файл
        
        # Проверяем еще раз, существует ли папка (могла не создаться из-за прав)
        if logs_dir and os.path.exists(logs_dir):
            log_file = os.path.join(logs_dir, 'cpc_auto_star.log')
            app.logger.info(f"Настройка RotatingFileHandler для файла: {log_file}")
            try:
                # RotatingFileHandler: 10MB макс размер, храним 5 старых файлов
                file_handler = RotatingFileHandler(log_file, maxBytes=1024*1024*10, backupCount=5, encoding='utf-8')
                file_handler.setFormatter(logging.Formatter(
                     '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]' # Подробный формат
                ))
                file_handler.setLevel(logging.INFO) # Уровень для файла
                app.logger.addHandler(file_handler)
                app.logger.info('=== Обработчик файлового лога успешно добавлен ===')
                app.logger.info('=== CPC Auto Star startup (logged to file) ===') # Запись о старте приложения в лог
            except Exception as e_handler:
                 app.logger.error(f"Ошибка при создании или добавлении FileHandler для {log_file}: {e_handler}")
        else:
             app.logger.warning(f"Папка для логов {logs_dir} не доступна. Файловое логирование пропускается.")
    else:
         app.logger.info('Пропускаем настройку файлового логирования (app.debug или app.testing is True)')

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