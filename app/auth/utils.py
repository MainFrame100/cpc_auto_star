import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask import session, current_app
from .. import db # <--- Изменяем импорт db
from ..models import Token # <--- Изменяем импорт Token на относительный

# YANDEX_CLIENT_ID и YANDEX_CLIENT_SECRET будут браться из конфигурации
# load_dotenv() # Больше не нужно здесь
# YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
# YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')

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

    # Проверяем наличие ID и секрета приложения в конфигурации
    client_id = current_app.config.get('YANDEX_CLIENT_ID')
    client_secret = current_app.config.get('YANDEX_CLIENT_SECRET')
    if not client_id or not client_secret:
        print("Ошибка: YANDEX_CLIENT_ID или YANDEX_CLIENT_SECRET не найдены в конфигурации приложения.")
        return False

    # Получаем URL OAuth из конфигурации
    base_oauth_url = current_app.config.get('OAUTH_BASE_URL')
    token_url = f"{base_oauth_url}token" # Формируем URL для /token
    print(f"Используем OAuth URL: {token_url}")

    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': token_entry.refresh_token,
        'client_id': client_id, # Используем из config
        'client_secret': client_secret # Используем из config
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

def restore_session(client_login, app): # <--- Принимаем app
    """
    Восстанавливает сессию пользователя из БД.
    Возвращает True если сессия восстановлена, False если нет.
    Работает внутри контекста приложения.
    """
    print(f"[restore_session] Попытка восстановления для {client_login}")
    if not client_login:
        print("[restore_session] Ошибка: client_login не передан")
        return False

    # Запросы к БД и использование session должны быть внутри контекста приложения
    with app.app_context(): # <--- Добавляем контекст
        token_entry = Token.query.filter_by(yandex_login=client_login).first()
        if not token_entry:
            print(f"[restore_session] Токен для {client_login} не найден в БД.")
            return False

        # Проверяем срок действия токена
        if datetime.utcnow() >= token_entry.expires_at - timedelta(minutes=1):
            print(f"[restore_session] Токен для {client_login} истек или скоро истечет.")
            if not token_entry.refresh_token:
                print(f"[restore_session] Refresh token для {client_login} отсутствует.")
                return False
            
            # Пытаемся обновить токен (refresh_access_token уже управляет commit/rollback)
            if not refresh_access_token(token_entry):
                print(f"[restore_session] Не удалось обновить токен для {client_login}.")
                return False
            # Если обновили, token_entry теперь содержит актуальный токен
            print(f"[restore_session] Токен для {client_login} успешно обновлен перед восстановлением сессии.")

        # Возвращаем True, если токен валиден или успешно обновлен
        print(f"[restore_session] Токен для {client_login} валиден/обновлен. Запись в session пропускается.")
        return True # Возвращаем True, если токен валиден/обновлен 