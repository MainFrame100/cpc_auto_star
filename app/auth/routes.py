import os
import requests
import json # Оставляем, может пригодиться для API
from flask import redirect, request, url_for, session, current_app, flash, render_template # Добавляем current_app, flash, render_template
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
    """Главная страница аутентификации."""
    # Получаем сообщение из GET параметра (если есть)
    message = request.args.get('message') 
    # Рендерим шаблон вместо возврата строки
    return render_template('auth/index.html', message=message)

@auth_bp.route('/login')
def login():
    """Перенаправляет пользователя на страницу авторизации Яндекса."""
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

        # --- Получение client_login --- 
        client_login = get_yandex_client_login(access_token)
        if not client_login:
            print("Не удалось получить client_login от API Яндекса.")
            flash("Не удалось получить логин пользователя от Яндекса.", 'danger')
            return redirect(url_for('.index'))
        
        print(f"Успешно получен client_login: {client_login}")

        # --- Сохранение токена в БД --- 
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
            flash("Ошибка сохранения данных авторизации.", 'danger')
            return redirect(url_for('.index'))

        # Сохраняем логин в сессии
        session['yandex_client_login'] = client_login

        # Вместо редиректа рендерим шаблон с сообщением об успехе
        return render_template('auth/login_success.html', client_login=client_login)

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
    """Выход пользователя из системы (очистка сессии)."""
    client_login = session.pop('yandex_client_login', None)
    if client_login:
        flash(f"Вы успешно вышли из системы ({client_login}).", 'info')
        print(f"Пользователь {client_login} вышел из системы (сессия очищена).")
    else:
        flash("Вы не были авторизованы.", 'warning')
    return redirect(url_for('.index')) 