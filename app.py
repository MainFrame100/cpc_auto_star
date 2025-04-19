import os
import requests
import json # Добавили импорт json
from flask import Flask, redirect, request, url_for, session
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy # <--- Добавили импорт
from datetime import datetime, timedelta # <--- Добавили timedelta

# Загружаем переменные окружения из файла .env
load_dotenv()

# Инициализируем Flask приложение
app = Flask(__name__)

# Конфигурация SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tokens.db' # Путь к файлу БД
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Отключаем ненужное отслеживание

# Инициализация SQLAlchemy
db = SQLAlchemy(app)

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

# Определение модели данных для токенов
class Token(db.Model):
    id = db.Column(db.Integer, primary_key=True) # Первичный ключ
    yandex_login = db.Column(db.String(80), unique=True, nullable=False) # Логин Яндекса, уникальный
    access_token = db.Column(db.String(200), nullable=False) # Токен доступа
    refresh_token = db.Column(db.String(200), nullable=True) # Токен обновления (может отсутствовать)
    expires_at = db.Column(db.DateTime, nullable=False) # Время истечения access_token

    def __repr__(self):
        # Удобное представление объекта для отладки
        return f'<Token for {self.yandex_login}>'

# --- Временный код для создания БД и таблиц --- 
# Запустите приложение один раз, чтобы создать tokens.db
# Затем закомментируйте или удалите этот блок
# with app.app_context():
#     db.create_all()
# print("База данных и таблицы проверены/созданы.") # Для отладки
# --------------------------------------------- 

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
    Обменивает authorization code на access token и refresh token,
    получает client_login и сохраняет/обновляет данные в БД.
    """
    code = session.get('yandex_auth_code')
    if not code:
        return "Ошибка: Authorization code не найден в сессии. Попробуйте <a href='/'>войти</a> заново.", 400

    if not YANDEX_CLIENT_ID or not YANDEX_CLIENT_SECRET:
        return "Ошибка: YANDEX_CLIENT_ID или YANDEX_CLIENT_SECRET не найдены в .env файле.", 500

    token_url = 'https://oauth.yandex.ru/token'
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': YANDEX_CLIENT_ID,
        'client_secret': YANDEX_CLIENT_SECRET
    }

    try:
        # --- 1. Обмен кода на токены --- 
        response = requests.post(token_url, data=payload)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data['access_token']
        refresh_token = token_data.get('refresh_token') # Может быть None
        expires_in = token_data['expires_in']

        # --- 2. Получение client_login --- 
        # (Временно дублируем логику из test_api_call, позже вынесем)
        try:
            user_info_url = 'https://login.yandex.ru/info?format=json'
            headers_user_info = {'Authorization': f'OAuth {access_token}'}
            user_response = requests.get(user_info_url, headers=headers_user_info)
            user_response.raise_for_status()
            user_data = user_response.json()
            client_login = user_data.get('login')
            if not client_login:
                return f"Ошибка: Не удалось получить 'login' из ответа Яндекс ID при получении токена. Ответ: {user_data}", 500
        except requests.exceptions.RequestException as e_user:
             return f"Ошибка при получении информации о пользователе Яндекс ID при получении токена: {e_user}", 500
        except Exception as e_user_generic:
             return f"Непредвиденная ошибка при получении логина при получении токена: {e_user_generic}", 500

        # --- 3. Расчет времени истечения токена --- 
        expires_at_dt = datetime.utcnow() + timedelta(seconds=expires_in)

        # --- 4. Поиск/Обновление/Создание записи в БД --- 
        existing_token = Token.query.filter_by(yandex_login=client_login).first()

        if existing_token:
            # Обновляем существующий токен
            existing_token.access_token = access_token
            existing_token.expires_at = expires_at_dt
            # Обновляем refresh_token только если он пришел в ответе
            if refresh_token:
                existing_token.refresh_token = refresh_token
            print(f"Токен для {client_login} обновлен в БД.") # Отладка
        else:
            # Создаем новый токен
            new_token = Token(
                yandex_login=client_login,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at_dt
            )
            db.session.add(new_token)
            print(f"Новый токен для {client_login} создан в БД.") # Отладка

        # --- 5. Сохранение изменений в БД --- 
        db.session.commit()

        # --- 6. Очистка временного кода и сохранение логина в сессии --- 
        # session.pop('yandex_auth_code', None) # Больше не нужно, код использован
        # УДАЛИТЬ строки сохранения в session Flask (если они были)
        # session.pop('yandex_access_token', None)
        # session.pop('yandex_refresh_token', None)
        # session.pop('yandex_token_expires_in', None)

        # Сохраняем логин пользователя в сессии Flask для использования в других роутах
        session['yandex_client_login'] = client_login

        # --- 7. Отображение результата --- 
        return f"""
        <h1>Токены получены и сохранены в БД!</h1>
        <p>Логин: {client_login}</p>
        <p>Access Token сохранен (в БД).</p>
        <p>Refresh Token { 'сохранен' if refresh_token else 'не получен / не обновлен'} (в БД).</p>
        <p>Время истечения Access Token (UTC): {expires_at_dt}</p>
        <p><a href="{url_for('test_api_call')}">Сделать тестовый запрос к API Директа (используя токен из БД)</a></p>
        """

    except requests.exceptions.RequestException as e:
        # Ошибка при запросе к Яндекс OAuth
        error_details = f"Ошибка сети или HTTP при обмене кода: {e}"
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                error_details += f" | Ответ сервера: {error_data}"
            except ValueError:
                error_details += f" | Не удалось разобрать ответ сервера: {e.response.text}"
        return f"Ошибка при обмене кода на токен: {error_details}", 500
    except KeyError as e:
        # Ошибка: в ответе нет ожидаемого ключа (например, 'access_token')
        return f"Ошибка: Не удалось найти ключ '{e}' в ответе от Яндекс OAuth при обмене кода. Ответ: {token_data if 'token_data' in locals() else 'Ответ не получен'}", 500
    except Exception as e_main:
        # Ловим другие возможные ошибки на верхнем уровне
        db.session.rollback() # Откатываем транзакцию БД в случае ошибки
        return f"Непредвиденная ошибка в /get_token: {e_main}", 500

# Убираем Placeholder и реализуем логику тестового вызова
@app.route('/test_api')
def test_api_call():
    """
    Выполняет тестовый запрос к API Яндекс.Директа (песочница),
    используя токен, полученный из БД.
    """
    # --- 1. Получение логина пользователя из сессии --- 
    client_login = session.get('yandex_client_login')
    if not client_login:
        # Если логина в сессии нет, пользователь не авторизован (или сессия истекла)
        return "Ошибка: Логин пользователя не найден в сессии. Попробуйте <a href='/'>войти</a> заново.", 400

    # --- 2. Получение токена из Базы Данных --- 
    token_entry = Token.query.filter_by(yandex_login=client_login).first()

    if not token_entry:
        # Если записи в БД нет для этого логина
        return f"Ошибка: Токен для пользователя '{client_login}' не найден в базе данных. Попробуйте <a href='/'>войти</a> заново, чтобы сохранить токен.", 404 # 404 Not Found

    # Получаем access_token из записи БД
    access_token = token_entry.access_token

    # --- 3. Формирование запроса к API Директа (остается почти без изменений) --- 
    api_endpoint = DIRECT_API_SANDBOX_URL + 'campaigns'

    headers_direct = {
        'Authorization': f'Bearer {access_token}', # Используем токен из БД
        'Client-Login': client_login,
        'Accept-Language': 'ru',
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

    # --- 4. Отправка запроса и обработка ответа --- 
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