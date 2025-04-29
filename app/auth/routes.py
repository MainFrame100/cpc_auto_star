import os
import requests
import json # Оставляем, может пригодиться для API
from flask import redirect, request, url_for, session, current_app, flash, render_template # Добавляем current_app, flash, render_template
from flask_login import login_user, logout_user, current_user # <--- Добавляем current_user
from datetime import datetime, timedelta
from urllib.parse import urlencode # Для формирования URL

from . import auth_bp # Импортируем Blueprint
from .. import db # Изменяем импорт db
from ..models import Token, User, Client, YandexAccount # Изменяем импорт Token, User, Client, YandexAccount на относительные

# Переменные окружения будут загружены при создании app
# YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
# YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
# Константа для URL API Директа (можно вынести в конфиг)
# DIRECT_API_SANDBOX_URL = 'https://api-sandbox.direct.yandex.com/json/v5/' # Убираем, будем брать из конфига

@auth_bp.route('/')
def index():
    """Главная страница аутентификации."""
    # Получаем сообщение из GET параметра (если есть)
    message = request.args.get('message') 
    # Рендерим шаблон вместо возврата строки
    return render_template('auth/index.html', message=message)

@auth_bp.route('/login')
def login():
    """Перенаправляет пользователя на страницу авторизации Яндекса."""
    # Получаем client_id из конфигурации приложения
    client_id = current_app.config.get('YANDEX_CLIENT_ID')
    if not client_id:
        # Можно использовать flash для сообщений об ошибках
        flash("Ошибка: YANDEX_CLIENT_ID не настроен в конфигурации приложения.", 'danger')
        # Лучше редирект на главную или страницу ошибки
        return redirect(url_for('.index'))

    # Redirect URI лучше брать из конфигурации приложения
    redirect_uri = url_for('auth.oauth_callback', _external=True)
    # Проверим, что он http. Для локальной разработки Яндекс требует http
    if redirect_uri.startswith('https'):
       redirect_uri = redirect_uri.replace('https', 'http', 1)
       print(f"Предупреждение: Заменяем https на http в redirect_uri для локальной разработки: {redirect_uri}")
    
    params = {
        'response_type': 'code',
        'client_id': client_id, # Используем client_id из конфига
        'redirect_uri': redirect_uri,
        'scope': 'direct:api' # <--- ДОБАВЛЯЕМ ЗАПРОС ПРАВ НА API ДИРЕКТА
        # 'state': os.urandom(16).hex() # Хорошая практика добавить state
    }
    auth_url = f"https://oauth.yandex.ru/authorize?{urlencode(params)}"
    print(f"Redirecting to Yandex OAuth: {auth_url}") # Логируем URL
    return redirect(auth_url)

@auth_bp.route('/oauth-callback')
def oauth_callback():
    """Обрабатывает ответ от Яндекса после авторизации."""
    code = request.args.get('code')
    error = request.args.get('error')
    if error:
        error_description = request.args.get('error_description', 'Нет описания')
        flash(f"Ошибка авторизации Яндекса: {error}. Описание: {error_description}", 'danger')
        return redirect(url_for('.index'))
    
    if not code:
        flash("Не получен код авторизации от Яндекса.", 'danger')
        return redirect(url_for('.index'))

    # Получаем client_id и client_secret из конфигурации
    client_id = current_app.config.get('YANDEX_CLIENT_ID')
    client_secret = current_app.config.get('YANDEX_CLIENT_SECRET')
    if not client_id or not client_secret:
        flash("Ошибка: Не настроены YANDEX_CLIENT_ID или YANDEX_CLIENT_SECRET.", 'danger')
        return redirect(url_for('.index'))

    # Обмен кода на токен
    token_url = 'https://oauth.yandex.ru/token'
    redirect_uri = url_for('auth.oauth_callback', _external=True)
    # Снова проверка на http для локалки
    if redirect_uri.startswith('https'):
       redirect_uri = redirect_uri.replace('https', 'http', 1)
       
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': client_id, # Используем из конфига
        'client_secret': client_secret, # Используем из конфига
        'redirect_uri': redirect_uri # Добавляем redirect_uri и сюда
    }

    try:
        response = requests.post(token_url, data=payload)
        response_data = response.json()

        if response.status_code != 200:
            error = response_data.get('error')
            error_description = response_data.get('error_description', 'Нет описания')
            print(f"Ошибка обмена кода на токен. Статус: {response.status_code}. Ошибка: {error}. Описание: {error_description}")
            flash(f"Ошибка получения токена от Яндекса ({response.status_code}): {response.text}", 'danger')
            return redirect(url_for('.index'))

        token_data = response.json()
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token')
        expires_in = token_data.get('expires_in')
        if not access_token or not expires_in:
            flash("Ответ Яндекса не содержит access_token или expires_in.", 'danger')
            return redirect(url_for('.index'))

        expires_at = datetime.now() + timedelta(seconds=int(expires_in))

        # --- Получение client_login (логин основного пользователя Яндекса) --- 
        user_yandex_login = get_yandex_client_login(access_token)
        if not user_yandex_login:
            current_app.logger.error("Не удалось получить client_login основного пользователя от API Яндекса.")
            flash("Не удалось получить логин пользователя от Яндекса.", 'danger')
            return redirect(url_for('.index'))
        
        current_app.logger.info(f"Успешно получен логин основного пользователя: {user_yandex_login}")

        # --- Находим или создаем пользователя сервиса (User) ---
        user = User.query.filter_by(yandex_login=user_yandex_login).first()
        if not user:
            current_app.logger.info(f"Создаем нового пользователя User для {user_yandex_login}")
            user = User(yandex_login=user_yandex_login)
            db.session.add(user)
            # Commit нужен здесь, чтобы получить user.id для связей ниже
            try:
                db.session.commit()
                current_app.logger.info(f"Пользователь User {user_yandex_login} (ID: {user.id}) создан.")
            except Exception as e_commit:
                db.session.rollback()
                current_app.logger.exception(f"Ошибка создания User в БД для {user_yandex_login}")
                flash("Ошибка сохранения данных пользователя.", 'danger')
                return redirect(url_for('.index'))
        else:
            current_app.logger.info(f"Найден существующий пользователь User {user_yandex_login} (ID: {user.id})")

        # --- Логика MVP: Используем основной аккаунт как первый подключенный --- 
        # В будущем здесь будет выбор клиента и аккаунта для подключения
        # Пока создадим клиента по умолчанию, если его нет, и подключим этот аккаунт
        
        client_name = "Мой Клиент по умолчанию"
        client = Client.query.filter_by(user_id=user.id, name=client_name).first()
        if not client:
            current_app.logger.info(f"Создаем клиента по умолчанию '{client_name}' для User ID {user.id}")
            client = Client(name=client_name, user_id=user.id)
            db.session.add(client)
            # Commit нужен здесь, чтобы получить client.id
            try:
                db.session.commit()
                current_app.logger.info(f"Клиент '{client_name}' (ID: {client.id}) создан.")
            except Exception as e_commit:
                db.session.rollback()
                current_app.logger.exception(f"Ошибка создания Client в БД для User ID {user.id}")
                flash("Ошибка сохранения данных клиента.", 'danger')
                return redirect(url_for('.index'))
        else:
             current_app.logger.info(f"Найден клиент по умолчанию '{client_name}' (ID: {client.id}) для User ID {user.id}")

        # Находим или создаем YandexAccount (в данном случае логин совпадает с логином User)
        yandex_account_login = user_yandex_login 
        yandex_account = YandexAccount.query.filter_by(client_id=client.id, login=yandex_account_login).first()
        if not yandex_account:
            current_app.logger.info(f"Создаем YandexAccount {yandex_account_login} для Client ID {client.id}")
            yandex_account = YandexAccount(login=yandex_account_login, client_id=client.id)
            db.session.add(yandex_account)
             # Commit нужен здесь, чтобы получить yandex_account.id
            try:
                db.session.commit()
                current_app.logger.info(f"YandexAccount {yandex_account_login} (ID: {yandex_account.id}) создан.")
            except Exception as e_commit:
                db.session.rollback()
                current_app.logger.exception(f"Ошибка создания YandexAccount в БД для Client ID {client.id}")
                flash("Ошибка сохранения данных аккаунта.", 'danger')
                return redirect(url_for('.index'))
        else:
             current_app.logger.info(f"Найден YandexAccount {yandex_account_login} (ID: {yandex_account.id}) для Client ID {client.id}")

        # --- Сохранение или обновление токена с ШИФРОВАНИЕМ --- 
        token_entry = Token.query.filter_by(yandex_account_id=yandex_account.id).first()
        
        # Шифруем токены ПЕРЕД сохранением
        encrypted_access = Token.encrypt_data(access_token)
        encrypted_refresh = Token.encrypt_data(refresh_token) # encrypt_data обработает None

        if token_entry:
            current_app.logger.info(f"Обновляем существующий токен для YandexAccount ID {yandex_account.id}")
            token_entry.encrypted_access_token = encrypted_access
            if encrypted_refresh: # Обновляем RT только если он пришел и успешно зашифровался
                token_entry.encrypted_refresh_token = encrypted_refresh
            token_entry.expires_at = expires_at
            token_entry.user_id = user.id # Убедимся, что user_id проставлен
        else:
            current_app.logger.info(f"Создаем новую запись токена для YandexAccount ID {yandex_account.id}")
            token_entry = Token(
                yandex_account_id=yandex_account.id,
                user_id=user.id, # Связываем с User!
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                expires_at=expires_at
            )
            db.session.add(token_entry)
        
        try:
            db.session.commit()
            current_app.logger.info(f"Токен для YandexAccount ID {yandex_account.id} сохранен/обновлен в БД.")
            
            # === Сообщаем Flask-Login, что пользователь вошел (используем User) ===
            login_user(user, remember=True) # <--- Передаем объект User
            current_app.logger.info(f"Flask-Login notified for user: {user.yandex_login} (ID: {user.id}) (Remember Me: True)") 
            # =====================================================

        except Exception as e_commit:
            db.session.rollback()
            current_app.logger.exception(f"Ошибка сохранения Token в БД для YandexAccount ID {yandex_account.id}")
            flash("Ошибка сохранения данных авторизации.", 'danger')
            return redirect(url_for('.index'))

        # Успешный вход
        flash(f'Вход выполнен успешно для пользователя {user.yandex_login}.', 'success')
        # Редирект на главную страницу приложения или дашборд
        return redirect(url_for('main.index')) # Предполагаем, что есть main.index

    except requests.exceptions.RequestException as e:
        print(f"Сетевая ошибка при обмене кода на токен: {e}")
        flash("Сетевая ошибка при получении токена.", 'danger')
        return redirect(url_for('.index'))
    except KeyError as e:
        # Добавим response_data в лог ошибки
        print(f"Ошибка: Отсутствует ключ '{e}' в ответе при обмене кода на токен. Ответ: {response_data if 'response_data' in locals() else 'Не удалось получить ответ'}")
        flash("Ошибка формата ответа от Яндекса при получении токена.", 'danger')
        return redirect(url_for('.index'))
    except json.JSONDecodeError as e: # Добавляем обработку JSONDecodeError
        print(f"Ошибка декодирования JSON при обмене кода на токен: {e}. Ответ: {response.text if 'response' in locals() else 'Ответ не получен'}")
        flash("Ошибка чтения ответа от Яндекса.", 'danger')
        return redirect(url_for('.index'))
    except Exception as e:
        print(f"Непредвиденная ошибка при обмене кода на токен: {e}")
        db.session.rollback() # Откатываем транзакцию БД, если она была начата
        flash("Непредвиденная ошибка сервера.", 'danger')
        return redirect(url_for('.index'))

# --- Вспомогательная функция для получения client_login --- 
def get_yandex_client_login(access_token):
    """Получает client_login пользователя через API Яндекс.Директ."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept-Language": "ru", # Язык ответных сообщений
        # Client-Login не нужен для этого запроса
    }
    payload = json.dumps({
        "method": "get",
        "params": {
            "FieldNames": ["Login"]
        }
    })
    
    # Получаем ПРАВИЛЬНЫЙ URL API v5 из конфигурации приложения
    # Убираем старую логику с DIRECT_API_BASE_URL
    api_v5_url = current_app.config.get('DIRECT_API_V5_URL')
    if not api_v5_url:
        current_app.logger.error("DIRECT_API_V5_URL не найден в конфигурации приложения!")
        return None # Возвращаем None, чтобы вызвать ошибку в вызывающем коде
        
    clients_url = f"{api_v5_url}clients" # Формируем URL для /clients
    current_app.logger.info(f"Запрос client_login к: {clients_url}") # Используем логгер
    
    try:
        result = requests.post(clients_url, headers=headers, data=payload, timeout=15) # Добавляем таймаут
        result.raise_for_status()
        data = result.json()

        if "error" in data:
            error = data['error']
            # Используем логгер
            current_app.logger.error(f"Ошибка API при получении client_login: Код {error.get('error_code')}, {error.get('error_string')}: {error.get('error_detail')}")
            return None
        
        # Извлекаем логин из ответа
        if data.get('result') and data['result'].get('Clients') and len(data['result']['Clients']) > 0:
            client_login = data['result']['Clients'][0].get('Login')
            return client_login
        else:
            print("Неожиданный формат ответа API при получении client_login:", data)
            return None

    except requests.exceptions.RequestException as e:
        print(f"Сетевая ошибка при запросе client_login: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Ошибка декодирования JSON при запросе client_login: {e}")
        return None
    except Exception as e:
        print(f"Непредвиденная ошибка при запросе client_login: {e}")
        return None

# Роут /get_token больше не нужен, обмен происходит в callback

# Убрали роут /test_api, он переедет в reports

@auth_bp.route('/logout')
def logout():
    """Выход пользователя из системы с использованием Flask-Login."""
    yandex_login = current_user.yandex_login if current_user.is_authenticated else None
    logout_user() # <--- Вызываем функцию выхода из Flask-Login
    if yandex_login:
        flash(f"Вы успешно вышли из системы ({yandex_login}).", 'info')
        print(f"Пользователь {yandex_login} вышел из системы (Flask-Login).")
    else:
        # Если пользователь не был аутентифицирован, все равно перенаправляем
        flash("Вы вышли из системы.", 'info')
    return redirect(url_for('.index')) # Перенаправляем на страницу входа 