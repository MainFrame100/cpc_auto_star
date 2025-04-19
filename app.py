import os
import requests
import json # Добавили импорт json
from flask import Flask, redirect, request, url_for, session
from dotenv import load_dotenv

# Загружаем переменные окружения из файла .env
load_dotenv()

# Инициализируем Flask приложение
app = Flask(__name__)

# Обязательно устанавливаем секретный ключ для работы сессий Flask
# В реальном приложении используйте более надежный способ генерации и хранения ключа
app.secret_key = os.urandom(24)

# Получаем Client ID и Client Secret из переменных окружения
YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
# Убедитесь, что этот redirect_uri точно совпадает с указанным в настройках приложения Яндекс OAuth
REDIRECT_URI = 'http://127.0.0.1:5000/oauth/callback'

# URL API Песочницы Яндекс.Директ
DIRECT_API_SANDBOX_URL = 'https://api-sandbox.direct.yandex.com/json/v5/'

@app.route('/')
def index():
    """
    Главная страница. Отображает ссылку для входа через Яндекс.
    """
    return f"""
    <h1>CPC Auto Helper - Вход</h1>
    <p><a href="{url_for('login_yandex')}">Войти через Яндекс</a></p>
    """

@app.route('/login/yandex')
def login_yandex():
    """
    Перенаправляет пользователя на страницу авторизации Яндекса.
    """
    if not YANDEX_CLIENT_ID:
        return "Ошибка: YANDEX_CLIENT_ID не найден в .env файле.", 500

    # Формируем URL для авторизации
    auth_url = (
        f"https://oauth.yandex.ru/authorize?"
        f"response_type=code"
        f"&client_id={YANDEX_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        # Можно добавить параметр state для защиты от CSRF, например:
        # f"&state={os.urandom(16).hex()}" # Сохранить state в сессии для проверки в callback
    )
    return redirect(auth_url)

@app.route('/oauth/callback')
def oauth_callback():
    """
    Обрабатывает ответ от сервера авторизации Яндекса.
    """
    error = request.args.get('error')
    if error:
        error_description = request.args.get('error_description', 'Нет описания')
        return f"Ошибка авторизации: {error}. Описание: {error_description}"

    code = request.args.get('code')
    # state = request.args.get('state') # Получить state, если передавали

    # Здесь можно добавить проверку state, если он использовался при редиректе

    if code:
        # На следующих шагах здесь будет код для обмена 'code' на 'access_token'
        session['yandex_auth_code'] = code # Временно сохраним код в сессии для демонстрации
        return f"""
        <h1>Успешная авторизация!</h1>
        <p>Получен authorization code:</p>
        <pre>{code}</pre>
        <p>Он сохранен в сессии.</p>
        <p><a href="{url_for('get_token')}">Обменять код на токен (следующий шаг)</a></p> 
        """ # Добавил ссылку на будущий шаг
    else:
        return "Ошибка: Не удалось получить authorization code от Яндекса."

# Убираем Placeholder и реализуем логику
@app.route('/get_token')
def get_token():
    """
    Обменивает authorization code на access token и refresh token.
    """
    # Проверяем, есть ли код в сессии
    code = session.get('yandex_auth_code')
    if not code:
        return "Ошибка: Authorization code не найден в сессии. Попробуйте <a href='/'>войти</a> заново.", 400

    # Проверяем наличие секретов
    if not YANDEX_CLIENT_ID or not YANDEX_CLIENT_SECRET:
        return "Ошибка: YANDEX_CLIENT_ID или YANDEX_CLIENT_SECRET не найдены в .env файле.", 500

    # Формируем данные для POST-запроса
    token_url = 'https://oauth.yandex.ru/token'
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': YANDEX_CLIENT_ID,
        'client_secret': YANDEX_CLIENT_SECRET
    }

    try:
        # Отправляем POST-запрос для получения токенов
        response = requests.post(token_url, data=payload)
        response.raise_for_status() # Проверяем на HTTP ошибки (4xx, 5xx)

        # Парсим JSON-ответ
        token_data = response.json()

        # Сохраняем токены и время жизни в сессии
        session['yandex_access_token'] = token_data['access_token']
        session['yandex_refresh_token'] = token_data.get('refresh_token') # refresh_token может не быть
        session['yandex_token_expires_in'] = token_data['expires_in']

        # Удаляем использованный auth code из сессии
        session.pop('yandex_auth_code', None)

        # Отображаем результат (временно)
        return f"""
        <h1>Токены получены!</h1>
        <p>Access Token: <pre>{session['yandex_access_token']}</pre></p>
        <p>Refresh Token: <pre>{session.get('yandex_refresh_token', 'Не получен')}</pre></p>
        <p>Expires in (seconds): {session['yandex_token_expires_in']}</p>
        <p>Токены сохранены в сессии.</p>
        <p><a href="{url_for('test_api_call')}">Сделать тестовый запрос к API Директа (следующий шаг)</a></p>
        """ # Исправил endpoint в url_for

    except requests.exceptions.RequestException as e:
        # Ошибка при запросе к Яндекс OAuth
        error_details = f"Ошибка сети или HTTP: {e}"
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                error_details += f" | Ответ сервера: {error_data}"
            except ValueError:
                error_details += f" | Не удалось разобрать ответ сервера: {e.response.text}"
        return f"Ошибка при обмене кода на токен: {error_details}", 500
    except KeyError as e:
        # Ошибка: в ответе нет ожидаемого ключа (например, 'access_token')
        return f"Ошибка: Не удалось найти ключ '{e}' в ответе от Яндекс OAuth. Ответ: {token_data}", 500

# Убираем Placeholder и реализуем логику тестового вызова
@app.route('/test_api')
def test_api_call():
    """
    Выполняет тестовый запрос к API Яндекс.Директа (песочница) для получения списка кампаний.
    """
    access_token = session.get('yandex_access_token')
    if not access_token:
        return "Ошибка: Access Token не найден в сессии. Попробуйте <a href='/'>войти</a> заново.", 400

    # --- 1. Получение логина пользователя --- 
    client_login = session.get('yandex_client_login')
    if not client_login:
        try:
            user_info_url = 'https://login.yandex.ru/info?format=json'
            headers_user_info = {
                'Authorization': f'OAuth {access_token}'
            }
            user_response = requests.get(user_info_url, headers=headers_user_info)
            user_response.raise_for_status()
            user_data = user_response.json()
            client_login = user_data.get('login')
            if not client_login:
                return f"Ошибка: Не удалось получить 'login' из ответа Яндекс ID. Ответ: {user_data}", 500
            session['yandex_client_login'] = client_login # Сохраняем логин в сессию
        except requests.exceptions.RequestException as e:
             return f"Ошибка при получении информации о пользователе Яндекс ID: {e}", 500
        except KeyError as e:
             return f"Ошибка: Не удалось найти ключ '{e}' в ответе от Яндекс ID. Ответ: {user_data}", 500
        except Exception as e:
             return f"Непредвиденная ошибка при получении логина: {e}", 500

    # --- 2. Формирование запроса к API Директа --- 
    api_endpoint = DIRECT_API_SANDBOX_URL + 'campaigns' # Используем URL песочницы

    # Заголовки запроса
    headers_direct = {
        'Authorization': f'Bearer {access_token}', # Используем Bearer для API Директа
        'Client-Login': client_login,
        'Accept-Language': 'ru', # Язык ответных сообщений
        'Content-Type': 'application/json; charset=utf-8'
    }

    # Тело запроса (получаем первые 10 кампаний)
    body = {
        "method": "get",
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["Id", "Name", "State", "Status"], # Запрашиваемые поля
            "Page": {
                "Limit": 10, # Ограничим количество для примера
                "Offset": 0
            }
        }
    }

    # --- 3. Отправка запроса и обработка ответа --- 
    try:
        response = requests.post(api_endpoint, headers=headers_direct, data=json.dumps(body, ensure_ascii=False).encode('utf-8'))

        # Проверка на ошибки API Директа в ответе
        response_data = response.json()
        if 'error' in response_data:
            error = response_data['error']
            return f"""
            <h1>Ошибка API Яндекс.Директ</h1>
            <p>Code: {error.get('error_code')}</p>
            <p>Message: {error.get('error_string')}</p>
            <p>Details: {error.get('error_detail')}</p>
            <p>Request ID: {error.get('request_id')}</p>
            """, 500

        # Проверка на общие HTTP ошибки после проверки API ошибок
        response.raise_for_status()

        # Успешный ответ
        campaigns = response_data.get('result', {}).get('Campaigns', [])

        result_html = f"<h1>Тестовый запрос к API Директа (Песочница)</h1>"
        result_html += f"<p>Логин клиента: {client_login}</p>"
        if campaigns:
            result_html += "<h2>Полученные кампании:</h2><ul>"
            for campaign in campaigns:
                result_html += f"<li>ID: {campaign.get('Id')}, Name: {campaign.get('Name')}, State: {campaign.get('State')}, Status: {campaign.get('Status')}</li>"
            result_html += "</ul>"
        else:
            result_html += "<p>Кампании не найдены.</p>"
        
        # Добавим вывод лимитов API из заголовков ответа (полезно для отладки)
        units_info = response.headers.get('Units')
        if units_info:
            result_html += f"<p>Баллы API: {units_info}</p>"
            
        return result_html

    except requests.exceptions.RequestException as e:
        error_details = f"Ошибка сети или HTTP при запросе к API Директа: {e}"
        if hasattr(e, 'response') and e.response is not None:
             try:
                 error_data = e.response.json() # Попробуем получить JSON ошибки
                 error_details += f" | Ответ сервера: {error_data}"
             except ValueError:
                 error_details += f" | Не удалось разобрать ответ сервера: {e.response.text}"
        return error_details, 500
    except json.JSONDecodeError as e:
        return f"Ошибка декодирования JSON ответа от API Директа: {e}<br>Ответ сервера: {response.text}", 500
    except Exception as e:
        return f"Непредвиденная ошибка при вызове API Директа: {e}", 500

if __name__ == '__main__':
    # Запускаем Flask сервер для локальной разработки
    # debug=True автоматически перезапускает сервер при изменениях кода
    # и показывает подробные ошибки в браузере
    app.run(host='127.0.0.1', port=5000, debug=True) 