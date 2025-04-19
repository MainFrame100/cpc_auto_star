import os
import requests
import json # Оставляем, может пригодиться для API
from flask import redirect, request, url_for, session, current_app # Добавляем current_app
from datetime import datetime, timedelta
from urllib.parse import urlencode # Для формирования URL

from . import auth_bp # Импортируем Blueprint
from app import db # Импортируем db
from app.models import Token # Импортируем модель
from .utils import get_valid_token, refresh_access_token # Импортируем утилиты

# Переменные окружения будут загружены при создании app
YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
# Константа для URL API Директа (можно вынести в конфиг)
DIRECT_API_SANDBOX_URL = 'https://api-sandbox.direct.yandex.com/json/v5/'

@auth_bp.route('/')
def index():
    """
    Главная страница. Отображает ссылку для входа и сообщения.
    """
    message = request.args.get('message')
    # Используем префикс 'auth.' для url_for
    login_link = f'<a href="{url_for('auth.login_yandex')}">Войти через Яндекс</a>'
    status_html = ""
    logout_link = ""
    test_api_link = ""

    client_login = session.get('yandex_client_login')
    if client_login:
        token_entry = Token.query.filter_by(yandex_login=client_login).first()
        if token_entry:
            status_html = f"<p>Вы вошли как: {client_login}.</p>"
            # Ссылка на тест API пока убрана, будет в другом Blueprint
            test_api_link = f"<a href='{url_for('reports.campaigns')}'>Список кампаний</a> | "
            logout_link = f"<a href='{url_for('auth.logout')}'>Выйти</a>"
            login_link = "" # Убираем ссылку на вход, если уже вошли
        else:
            session.pop('yandex_client_login', None)
            status_html = "<p>Ошибка: Найден логин в сессии, но нет токена в БД. Сессия очищена.</p>"

    return f"""
    <h1>CPC Auto Helper - Вход</h1>
    { f'<p style="color:blue;">{message}</p>' if message else '' }
    { status_html }
    { test_api_link } 
    { logout_link }
    { login_link }
    """

@auth_bp.route('/login/yandex')
def login_yandex():
    """
    Перенаправляет пользователя на страницу авторизации Яндекса.
    """
    if not YANDEX_CLIENT_ID:
        # Можно использовать flash для сообщений об ошибках
        return "Ошибка: YANDEX_CLIENT_ID не найден в .env файле.", 500

    # Redirect URI лучше брать из конфигурации приложения
    redirect_uri = url_for('auth.oauth_callback', _external=True)
    # Проверим, что он http. Для локальной разработки Яндекс требует http
    if redirect_uri.startswith('https'):
       redirect_uri = redirect_uri.replace('https', 'http', 1)
       print(f"Предупреждение: Заменяем https на http в redirect_uri для локальной разработки: {redirect_uri}")
    
    params = {
        'response_type': 'code',
        'client_id': YANDEX_CLIENT_ID,
        'redirect_uri': redirect_uri,
        # 'state': os.urandom(16).hex() # Хорошая практика добавить state
    }
    auth_url = f"https://oauth.yandex.ru/authorize?{urlencode(params)}"
    return redirect(auth_url)

@auth_bp.route('/oauth/callback')
def oauth_callback():
    """
    Обрабатывает ответ от сервера авторизации Яндекса.
    Обменивает code на токен.
    """
    error = request.args.get('error')
    if error:
        error_description = request.args.get('error_description', 'Нет описания')
        return f"Ошибка авторизации: {error}. Описание: {error_description}"

    code = request.args.get('code')
    # state = request.args.get('state') # Получить state и проверить

    if not code:
        return redirect(url_for('auth.index', message="Ошибка: Не получен код авторизации от Яндекса."))

    # Обмен кода на токен
    token_url = 'https://oauth.yandex.ru/token'
    redirect_uri = url_for('auth.oauth_callback', _external=True)
    # Снова проверка на http для локалки
    if redirect_uri.startswith('https'):
       redirect_uri = redirect_uri.replace('https', 'http', 1)
       
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': YANDEX_CLIENT_ID,
        'client_secret': YANDEX_CLIENT_SECRET,
        'redirect_uri': redirect_uri # Добавляем redirect_uri и сюда
    }

    try:
        response = requests.post(token_url, data=payload)
        response_data = response.json()

        if response.status_code != 200:
            error = response_data.get('error')
            error_description = response_data.get('error_description', 'Нет описания')
            print(f"Ошибка обмена кода на токен. Статус: {response.status_code}. Ошибка: {error}. Описание: {error_description}")
            return redirect(url_for('auth.index', message=f"Ошибка получения токена: {error_description}"))

        # --- Получение client_login --- 
        access_token = response_data['access_token']
        client_login = get_yandex_client_login(access_token)

        if not client_login:
            print("Не удалось получить client_login от API Яндекса.")
            return redirect(url_for('auth.index', message="Не удалось получить логин пользователя от Яндекса."))
        
        print(f"Успешно получен client_login: {client_login}")

        # --- Сохранение токена в БД --- 
        expires_in = response_data['expires_in']
        refresh_token = response_data.get('refresh_token') # refresh_token может не вернуться
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Ищем существующий токен или создаем новый
        token_entry = Token.query.filter_by(yandex_login=client_login).first()
        if token_entry:
            print(f"Обновляем существующий токен для {client_login}")
            token_entry.access_token = access_token
            token_entry.refresh_token = refresh_token if refresh_token else token_entry.refresh_token # Обновляем RT только если он пришел
            token_entry.expires_at = expires_at
        else:
            print(f"Создаем новую запись токена для {client_login}")
            token_entry = Token(
                yandex_login=client_login,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at
            )
            db.session.add(token_entry)
        
        try: # Добавляем try-except вокруг commit
            db.session.commit()
            print(f"Токен для {client_login} сохранен/обновлен в БД.")
        except Exception as e_commit:
            db.session.rollback()
            print(f"Ошибка сохранения токена в БД: {e_commit}")
            return redirect(url_for('auth.index', message="Ошибка сохранения данных авторизации."))

        # Сохраняем логин в сессии
        session['yandex_client_login'] = client_login

        # Перенаправляем на главную с сообщением об успехе
        return redirect(url_for('auth.index', message="Успешный вход и получение токена!"))

    except requests.exceptions.RequestException as e:
        print(f"Сетевая ошибка при обмене кода на токен: {e}")
        return redirect(url_for('auth.index', message="Сетевая ошибка при получении токена."))
    except KeyError as e:
        # Добавим response_data в лог ошибки
        print(f"Ошибка: Отсутствует ключ '{e}' в ответе при обмене кода на токен. Ответ: {response_data if 'response_data' in locals() else 'Не удалось получить ответ'}")
        return redirect(url_for('auth.index', message="Ошибка формата ответа от Яндекса при получении токена."))
    except json.JSONDecodeError as e: # Добавляем обработку JSONDecodeError
        print(f"Ошибка декодирования JSON при обмене кода на токен: {e}. Ответ: {response.text if 'response' in locals() else 'Ответ не получен'}")
        return redirect(url_for('auth.index', message="Ошибка чтения ответа от Яндекса."))
    except Exception as e:
        print(f"Непредвиденная ошибка при обмене кода на токен: {e}")
        db.session.rollback() # Откатываем транзакцию БД, если она была начата
        return redirect(url_for('auth.index', message="Непредвиденная ошибка сервера."))

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
    
    clients_url = f"{DIRECT_API_SANDBOX_URL}clients"
    
    try:
        result = requests.post(clients_url, headers=headers, data=payload)
        result.raise_for_status() # Проверка на HTTP ошибки (4xx, 5xx)
        data = result.json()

        if "error" in data:
            error = data['error']
            print(f"Ошибка API при получении client_login: Код {error['error_code']}, {error['error_string']}: {error['error_detail']}")
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
    """Очищает сессию пользователя."""
    session.pop('yandex_client_login', None)
    session.pop('yandex_auth_code', None) # На всякий случай
    # Можно добавить удаление токена из БД, но пока оставим
    return redirect(url_for('auth.index', message="Вы успешно вышли.")) 