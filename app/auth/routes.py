import os
import requests
import json # Оставляем, может пригодиться для API
from flask import redirect, request, url_for, session, current_app, flash, render_template # Добавляем current_app, flash, render_template
from flask_login import login_user, logout_user, current_user, login_required # <--- Добавляем current_user и login_required
from datetime import datetime, timedelta
from urllib.parse import urlencode # Для формирования URL
import secrets # Для генерации state

from . import auth_bp # Импортируем Blueprint
from .. import db, Config # Изменяем импорт db и Config
from ..models import Token, User, Client, YandexAccount # Изменяем импорт Token, User, Client, YandexAccount на относительные
from .utils import get_yandex_user_info # Предполагаем, что эта функция есть

# Переменные окружения будут загружены при создании app
# YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
# YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
# Константа для URL API Директа (можно вынести в конфиг)
# DIRECT_API_SANDBOX_URL = 'https://api-sandbox.direct.yandex.com/json/v5/' # Убираем, будем брать из конфига

# Константы для OAuth
YANDEX_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
YANDEX_TOKEN_URL = "https://oauth.yandex.ru/token"

@auth_bp.route('/')
def index():
    """Главная страница аутентификации / или дашборд после логина."""
    if current_user.is_authenticated:
        # Если пользователь уже вошел, редиректим на список клиентов
        return redirect(url_for('auth.list_clients'))
    return render_template('auth/index.html')

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
    """Обрабатывает ответ от Яндекса ПОСЛЕ АВТОРИЗАЦИИ ДЛЯ ВХОДА В ПРИЛОЖЕНИЕ."""
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
    token_url = YANDEX_TOKEN_URL # Используем константу
    redirect_uri = url_for('auth.oauth_callback', _external=True)
    # Снова проверка на http для локалки
    if redirect_uri.startswith('https'):
       redirect_uri = redirect_uri.replace('https', 'http', 1)

    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri
    }

    access_token = None # Инициализируем access_token
    try:
        response = requests.post(token_url, data=payload)
        response_data = response.json() # Получаем ответ один раз

        if response.status_code != 200:
            error = response_data.get('error')
            error_description = response_data.get('error_description', 'Нет описания')
            current_app.logger.error(f"Ошибка обмена кода на токен. Статус: {response.status_code}. Ошибка: {error}. Описание: {error_description}")
            flash(f"Ошибка получения токена от Яндекса ({response.status_code}): {response.text}", 'danger')
            return redirect(url_for('.index'))

        access_token = response_data.get('access_token')
        # Refresh token и expires_in нам здесь не нужны для простого входа
        if not access_token:
            flash("Ответ Яндекса не содержит access_token.", 'danger')
            return redirect(url_for('.index'))
            
        # --- Получение логина пользователя Яндекса --- 
        # Используем access_token ТОЛЬКО для идентификации
        user_info = get_yandex_user_info(access_token)
        user_yandex_login = user_info.get('login')
        if not user_yandex_login:
            # get_yandex_user_info уже залогировал ошибку
            flash("Не удалось получить логин пользователя от Яндекса.", 'danger')
            return redirect(url_for('.index'))
        
        current_app.logger.info(f"Успешно получен логин основного пользователя для входа: {user_yandex_login}")

        # --- Находим или создаем пользователя сервиса (User) --- 
        user = User.query.filter_by(yandex_login=user_yandex_login).first()
        if not user:
            current_app.logger.info(f"Создаем нового пользователя User для {user_yandex_login}")
            user = User(yandex_login=user_yandex_login)
            db.session.add(user)
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

        # --- Вход пользователя в систему --- 
        login_user(user, remember=True) # Сообщаем Flask-Login
        current_app.logger.info(f"Flask-Login notified for user: {user.yandex_login} (ID: {user.id}) (Remember Me: True)") 
        flash(f'Вход выполнен успешно для пользователя {user.yandex_login}.', 'success')
        
        # --- РЕДИРЕКТ --- 
        # Редиректим на список клиентов, т.к. это теперь основной интерфейс после логина
        return redirect(url_for('.list_clients')) 

    # --- Обработка ошибок на этапе получения токена или user_info --- 
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Сетевая ошибка при обмене кода на токен или запросе user_info: {e}")
        flash(f"Сетевая ошибка при взаимодействии с Яндексом: {e}", 'danger')
        return redirect(url_for('.index'))
    except json.JSONDecodeError as e:
        current_app.logger.error(f"Ошибка декодирования JSON при обмене кода на токен: {e}")
        flash("Ошибка чтения ответа от Яндекса.", 'danger')
        return redirect(url_for('.index'))
    except ValueError as e: # Ловим ошибку от get_yandex_user_info, если нет логина
        current_app.logger.error(f"Ошибка получения данных пользователя Яндекса: {e}")
        flash(f"Не удалось получить необходимые данные от Яндекса: {e}", 'danger')
        return redirect(url_for('.index'))
    except Exception as e:
        current_app.logger.exception(f"Непредвиденная ошибка в oauth_callback: {e}")
        db.session.rollback() # Откатываем транзакцию БД на всякий случай
        flash("Непредвиденная ошибка сервера при входе.", 'danger')
        return redirect(url_for('.index'))

# Роут /get_token больше не нужен, обмен происходит в callback

# Убрали роут /test_api, он переедет в reports

@auth_bp.route('/logout')
@login_required
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

# --- Управление Клиентами --- 

@auth_bp.route('/clients')
@login_required
def list_clients():
    """Отображает список клиентов текущего пользователя."""
    user_clients = Client.query.filter_by(user_id=current_user.id).order_by(Client.name).all()
    return render_template('auth/client_list.html', clients=user_clients)

@auth_bp.route('/clients/add', methods=['GET', 'POST'])
@login_required
def add_client():
    """Обрабатывает добавление нового клиента."""
    if request.method == 'POST':
        client_name = request.form.get('client_name')
        if not client_name:
            flash('Необходимо указать имя клиента.', 'warning')
        else:
            # Проверка на дубликат имени клиента у этого пользователя
            existing_client = Client.query.filter_by(user_id=current_user.id, name=client_name).first()
            if existing_client:
                flash(f'Клиент с именем "{client_name}" уже существует.', 'warning')
            else:
                new_client = Client(name=client_name, user_id=current_user.id)
                db.session.add(new_client)
                try:
                    db.session.commit()
                    flash(f'Клиент "{client_name}" успешно добавлен.', 'success')
                    return redirect(url_for('.list_clients'))
                except Exception as e:
                    db.session.rollback()
                    flash(f'Ошибка при добавлении клиента: {e}', 'danger')
                    current_app.logger.error(f"Error adding client for user {current_user.id}: {e}")
    # Для GET запроса или если POST не удался
    return render_template('auth/add_client.html')

# --- OAuth Флоу Яндекса (с учетом Client ID) --- 

@auth_bp.route('/yandex')
@login_required
def yandex_authorize():
    """Редирект на Яндекс для авторизации. Добавляет client_id в state."""
    client_id_to_link = request.args.get('client_id')
    if not client_id_to_link:
        flash("Не указан ID клиента для привязки аккаунта.", "danger")
        # Редирект на список клиентов, чтобы пользователь выбрал
        return redirect(url_for('.list_clients'))
    
    # Проверяем, что клиент принадлежит текущему пользователю
    client = Client.query.filter_by(id=client_id_to_link, user_id=current_user.id).first()
    if not client:
        flash("Указанный клиент не найден или не принадлежит вам.", "danger")
        return redirect(url_for('.list_clients'))

    # Генерируем state, включая client_id
    state_token = secrets.token_urlsafe(16)
    state_with_client_id = f"client_id={client_id_to_link}:{state_token}"
    session['oauth_state'] = state_with_client_id # Сохраняем state в сессию
    
    # !!! ЯВНО УКАЗЫВАЕМ ЯНДЕКСУ ПРАВИЛЬНЫЙ CALLBACK URL ДЛЯ ПРИВЯЗКИ !!!
    redirect_uri_for_linking = url_for('auth.yandex_callback', _external=True)
    # Проверка на http для локалки
    if redirect_uri_for_linking.startswith('https'):
        redirect_uri_for_linking = redirect_uri_for_linking.replace('https', 'http', 1)
        print(f"Предупреждение: Заменяем https на http в redirect_uri для привязки аккаунта: {redirect_uri_for_linking}")

    params = {
        'response_type': 'code',
        'client_id': Config.YANDEX_CLIENT_ID,
        'state': state_with_client_id,
        'redirect_uri': redirect_uri_for_linking, # <--- ДОБАВЛЯЕМ СЮДА
        'force_confirm': 'yes' # Запрашивать подтверждение каждый раз (рекомендуется)
    }
    # Формируем URL и делаем редирект
    auth_url = requests.Request('GET', YANDEX_AUTHORIZE_URL, params=params).prepare().url
    return redirect(auth_url)

@auth_bp.route('/yandex/callback')
@login_required # Убедимся, что пользователь все еще залогинен
def yandex_callback():
    """Обработка callback от Яндекса после авторизации."""
    code = request.args.get('code')
    state = request.args.get('state')
    session_state = session.pop('oauth_state', None)

    # 1. Проверка state
    if not state or state != session_state:
        flash('Ошибка авторизации: несовпадение параметра state или он отсутствует.', 'danger')
        current_app.logger.warning(f"OAuth state mismatch or missing. Received: {state}, Expected: {session_state}")
        return redirect(url_for('.list_clients')) # Редирект на список клиентов

    # 2. Извлечение client_id из state
    try:
        state_parts = state.split(':')
        if len(state_parts) != 2 or not state_parts[0].startswith('client_id='):
             raise ValueError("Invalid state format")
        client_id_str = state_parts[0].split('=')[1]
        client_id = int(client_id_str)
    except (ValueError, IndexError):
        flash('Ошибка авторизации: неверный формат параметра state.', 'danger')
        current_app.logger.error(f"Invalid state format received: {state}")
        return redirect(url_for('.list_clients'))

    # 3. Проверка существования клиента и принадлежности пользователю
    target_client = Client.query.filter_by(id=client_id, user_id=current_user.id).first()
    if not target_client:
        flash(f"Клиент с ID {client_id} не найден или не принадлежит вам.", "danger")
        return redirect(url_for('.list_clients'))

    # 4. Обмен кода на токен
    token_data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': Config.YANDEX_CLIENT_ID,
        'client_secret': Config.YANDEX_CLIENT_SECRET
    }
    try:
        response = requests.post(YANDEX_TOKEN_URL, data=token_data)
        response.raise_for_status() # Проверка на HTTP ошибки
        token_info = response.json()
        access_token = token_info.get('access_token')
        refresh_token = token_info.get('refresh_token')
        expires_in = token_info.get('expires_in')
        
        if not access_token or not expires_in:
             raise ValueError("Ответ API не содержит access_token или expires_in")
        
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    except requests.exceptions.RequestException as e:
        flash(f'Ошибка сети при получении токена от Яндекса: {e}', 'danger')
        current_app.logger.error(f"Network error getting Yandex token: {e}")
        return redirect(url_for('.list_clients'))
    except (ValueError, json.JSONDecodeError) as e:
        flash(f'Ошибка обработки ответа от Яндекса при получении токена: {e}', 'danger')
        current_app.logger.error(f"Error processing Yandex token response: {e}. Response: {response.text[:500]}")
        return redirect(url_for('.list_clients'))

    # 5. Получение информации о пользователе (логин)
    try:
        user_info = get_yandex_user_info(access_token)
        yandex_login = user_info.get('login')
        if not yandex_login:
            raise ValueError("Не удалось получить логин из информации о пользователе Яндекса.")
            
    except Exception as e:
        flash(f'Не удалось получить информацию об аккаунте Яндекса: {e}', 'danger')
        current_app.logger.error(f"Error getting Yandex user info: {e}")
        return redirect(url_for('.list_clients'))

    # 6. Проверка на дубликат YandexAccount для ЭТОГО клиента
    existing_yandex_account = YandexAccount.query.filter_by(client_id=client_id, login=yandex_login).first()
    if existing_yandex_account:
         flash(f'Аккаунт Яндекс.Директ "{yandex_login}" уже привязан к клиенту "{target_client.name}".', 'warning')
         return redirect(url_for('.list_clients'))
         
    # 7. Создание YandexAccount и Token
    try:
        # Создаем новый рекламный аккаунт
        new_yandex_account = YandexAccount(
            login=yandex_login,
            client_id=client_id,
            is_active=True # По умолчанию активен
        )
        db.session.add(new_yandex_account)
        db.session.flush() # Получаем ID для new_yandex_account перед созданием Token
        
        # Шифруем токены
        encrypted_access = Token.encrypt_data(access_token)
        encrypted_refresh = Token.encrypt_data(refresh_token) if refresh_token else None

        # Создаем запись с токеном
        new_token = Token(
            yandex_account_id=new_yandex_account.id,
            user_id=current_user.id, # !!! Важно: привязка к текущему пользователю !!!
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypted_refresh,
            expires_at=expires_at
        )
        db.session.add(new_token)
        db.session.commit()
        
        flash(f'Аккаунт Яндекс.Директ "{yandex_login}" успешно привязан к клиенту "{target_client.name}".', 'success')
        current_app.logger.info(f"Successfully linked Yandex account {yandex_login} (ID: {new_yandex_account.id}) to Client ID {client_id} for User ID {current_user.id}")

    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при сохранении аккаунта или токена в базе данных: {e}', 'danger')
        current_app.logger.error(f"DB error linking Yandex account {yandex_login} to client {client_id}: {e}")
        
    # Перенаправляем на список клиентов после всех операций
    return redirect(url_for('.list_clients'))

# Вспомогательная функция (если ее еще нет)
# def get_yandex_user_info(access_token):
#     info_url = "https://login.yandex.ru/info"
#     headers = {"Authorization": f"OAuth {access_token}"}
#     try:
#         response = requests.get(info_url, headers=headers)
#         response.raise_for_status()
#         return response.json()
#     except requests.exceptions.RequestException as e:
#         raise Exception(f"Ошибка сети при запросе Yandex user info: {e}") from e
#     except json.JSONDecodeError:
#         raise Exception(f"Ошибка декодирования JSON от Yandex user info. Ответ: {response.text[:200]}") 