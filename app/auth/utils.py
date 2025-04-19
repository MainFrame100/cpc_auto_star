import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy # Нужен ли? Вроде db передается в refresh
from app import db # Импортируем db
from app.models import Token # Импортируем модель

load_dotenv() # Загружаем переменные для YANDEX_CLIENT_ID/SECRET

YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')

# --- Функция для получения действительного токена --- 
def get_valid_token(client_login):
    """
    Находит токен в БД по логину, проверяет срок действия.
    Если истек, пытается обновить.
    Возвращает действительный access_token или None.
    """
    if not client_login:
        print("Ошибка: client_login не передан в get_valid_token")
        return None

    token_entry = Token.query.filter_by(yandex_login=client_login).first()

    if not token_entry:
        print(f"Токен для {client_login} не найден в БД.")
        return None

    # Проверяем, не истек ли токен (с запасом в 1 минуту)
    if datetime.utcnow() < token_entry.expires_at - timedelta(minutes=1):
        print(f"Действующий токен для {client_login} найден в БД.")
        return token_entry.access_token
    else:
        print(f"Токен для {client_login} истек или скоро истечет.")
        # Токен истек, пытаемся обновить
        if not token_entry.refresh_token:
            print(f"Refresh token для {client_login} отсутствует. Требуется переавторизация.")
            return None # Нет refresh_token, обновить не можем

        print(f"Пытаемся обновить токен для {client_login} с помощью refresh_token...")
        success = refresh_access_token(token_entry) # Вызываем функцию обновления

        if success:
            print(f"Токен для {client_login} успешно обновлен.")
            return token_entry.access_token # Возвращаем уже обновленный токен
        else:
            print(f"Не удалось обновить токен для {client_login}.")
            return None

# --- Функция для обновления access_token --- 
def refresh_access_token(token_entry):
    """Обновляет access_token с помощью refresh_token.
    Обновляет запись token_entry в БД и возвращает True при успехе, False при неудаче.
    """
    print(f"Попытка обновления токена для {token_entry.yandex_login} через refresh_token.")

    if not token_entry.refresh_token:
        print(f"Ошибка: Refresh token для {token_entry.yandex_login} отсутствует.")
        return False

    # Проверяем наличие ID и секрета приложения
    if not YANDEX_CLIENT_ID or not YANDEX_CLIENT_SECRET:
        print("Ошибка: YANDEX_CLIENT_ID или YANDEX_CLIENT_SECRET не найдены в .env.")
        return False

    token_url = 'https://oauth.yandex.ru/token'
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': token_entry.refresh_token,
        'client_id': YANDEX_CLIENT_ID,
        'client_secret': YANDEX_CLIENT_SECRET
    }

    try:
        response = requests.post(token_url, data=payload)
        response_data = response.json() # Получаем ответ в любом случае

        # Проверяем на ошибки OAuth Яндекса
        if response.status_code != 200:
            error = response_data.get('error')
            error_description = response_data.get('error_description', 'Нет описания')
            print(f"Ошибка обновления токена для {token_entry.yandex_login}. Статус: {response.status_code}. Ошибка: {error}. Описание: {error_description}")
            
            # Если ошибка связана с невалидным refresh_token, удаляем его из БД
            if error == 'invalid_grant': 
                print(f"Невалидный refresh_token для {token_entry.yandex_login}. Удаляем его из БД.")
                token_entry.refresh_token = None
                try:
                    db.session.commit()
                except Exception as e_commit:
                    print(f"Ошибка при удалении невалидного refresh_token из БД: {e_commit}")
                    db.session.rollback()
            return False

        # Успешное обновление
        new_access_token = response_data['access_token']
        new_expires_in = response_data['expires_in']
        new_refresh_token = response_data.get('refresh_token') 

        new_expires_at = datetime.utcnow() + timedelta(seconds=new_expires_in)

        # Обновляем данные в объекте token_entry
        token_entry.access_token = new_access_token
        token_entry.expires_at = new_expires_at
        if new_refresh_token:
            print(f"Получен НОВЫЙ refresh_token для {token_entry.yandex_login}. Обновляем.")
            token_entry.refresh_token = new_refresh_token
        
        # Сохраняем изменения в БД
        db.session.commit()
        print(f"Токен для {token_entry.yandex_login} успешно обновлен в БД.")
        return True

    except requests.exceptions.RequestException as e:
        print(f"Сетевая ошибка при обновлении токена для {token_entry.yandex_login}: {e}")
        db.session.rollback()
        return False
    except KeyError as e:
        print(f"Ошибка: Отсутствует ключ '{e}' в ответе при обновлении токена для {token_entry.yandex_login}. Ответ: {response_data}")
        db.session.rollback()
        return False
    except Exception as e:
        print(f"Непредвиденная ошибка при обновлении токена для {token_entry.yandex_login}: {e}")
        db.session.rollback()
        return False 