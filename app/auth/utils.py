import os
import requests
import json
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask import session, current_app
from .. import db

# --- Файл утилит для аутентификации --- 

# ВНИМАНИЕ: Функции get_valid_token, refresh_access_token, restore_session 
# были удалены, так как логика получения и обновления токена 
# теперь инкапсулирована в YandexDirectClient и обработке OAuth callback.

# Если здесь потребуются другие утилиты, связанные с auth (например, проверка state), 
# их можно добавить сюда. 

def get_yandex_user_info(access_token: str) -> dict:
    """Запрашивает информацию о пользователе Яндекса по токену доступа.

    Args:
        access_token (str): Действующий OAuth токен доступа.

    Returns:
        dict: Словарь с информацией о пользователе (включая 'login') или пустой словарь при ошибке.
    
    Raises:
        Exception: При сетевых ошибках или ошибках декодирования JSON.
    """
    info_url = "https://login.yandex.ru/info"
    headers = {"Authorization": f"OAuth {access_token}"}
    current_app.logger.debug(f"Запрос информации о пользователе Яндекса к {info_url}")
    try:
        response = requests.get(info_url, headers=headers, timeout=10)
        response.raise_for_status() # Проверяем HTTP ошибки
        user_info = response.json()
        current_app.logger.debug(f"Получена информация от Yandex Login API: {user_info}")
        # Проверяем наличие обязательного поля login
        if 'login' not in user_info:
             current_app.logger.error(f"Ответ от {info_url} не содержит поля 'login'. Ответ: {user_info}")
             raise ValueError("Ответ API login.yandex.ru не содержит поля 'login'")
        return user_info
    except requests.exceptions.Timeout as e_timeout:
        current_app.logger.error(f"Таймаут при запросе к {info_url}: {e_timeout}")
        raise Exception(f"Таймаут при запросе информации о пользователе Яндекса") from e_timeout
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Сетевая ошибка при запросе к {info_url}: {e}. Статус: {response.status_code if 'response' in locals() else 'N/A'}. Ответ: {response.text[:200] if 'response' in locals() else 'N/A'}")
        raise Exception(f"Ошибка сети при запросе информации о пользователе Яндекса") from e
    except json.JSONDecodeError as e_json:
        current_app.logger.error(f"Ошибка декодирования JSON от {info_url}: {e_json}. Ответ: {response.text[:200] if 'response' in locals() else 'N/A'}")
        raise Exception(f"Ошибка чтения ответа от сервера информации Яндекса") from e_json
    except ValueError as e_val:
        # Перехватываем нашу ошибку ValueError, если нет поля login
        raise e_val
    except Exception as e_other:
        # Ловим остальные непредвиденные ошибки
        current_app.logger.exception(f"Непредвиденная ошибка в get_yandex_user_info")
        raise Exception("Непредвиденная ошибка при получении данных пользователя Яндекса") from e_other
