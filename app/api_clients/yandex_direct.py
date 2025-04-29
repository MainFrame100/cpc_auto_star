import requests
import json
import traceback
import time # для ретраев и ожидания отчетов
from flask import current_app, flash
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

# Импортируем модели для получения токена
from ..models import Token, YandexAccount
from .. import db

class YandexDirectClientError(Exception):
    """Базовый класс для ошибок API клиента."""
    def __init__(self, message, status_code=None, api_error_code=None, api_error_detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.api_error_code = api_error_code
        self.api_error_detail = api_error_detail

class YandexDirectAuthError(YandexDirectClientError):
    """Ошибка, связанная с аутентификацией или авторизацией (невалидный токен, нет прав)."""
    pass

class YandexDirectTemporaryError(YandexDirectClientError):
    """Временная ошибка API (можно попробовать повторить запрос)."""
    pass

class YandexDirectClient:
    def __init__(self, yandex_account_id: int, current_user_id: int):
        """
        Инициализирует клиент API Яндекс.Директ для конкретного рекламного аккаунта.

        Args:
            yandex_account_id (int): ID рекламного аккаунта (YandexAccount) в нашей БД.
            current_user_id (int): ID текущего авторизованого пользователя (User) для проверки прав.

        Raises:
            YandexDirectAuthError: Если токен не найден, недействителен или принадлежит другому пользователю.
            ValueError: Если не настроены URL API в конфигурации.
        """
        current_app.logger.debug(f"Initializing YandexDirectClient for YandexAccount ID: {yandex_account_id}, User ID: {current_user_id}")
        
        # --- Получение и проверка токена ---
        token_entry = Token.query.filter_by(yandex_account_id=yandex_account_id).first()

        if not token_entry:
            msg = f"Токен для YandexAccount ID {yandex_account_id} не найден в БД."
            current_app.logger.error(msg)
            raise YandexDirectAuthError(msg)
        
        # !!! КРИТИЧЕСКИ ВАЖНАЯ ПРОВЕРКА ПРАВ ДОСТУПА !!!
        if token_entry.user_id != current_user_id:
            msg = f"Попытка доступа к токену YandexAccount ID {yandex_account_id} пользователем {current_user_id}, но токен принадлежит пользователю {token_entry.user_id}."
            current_app.logger.critical(msg) # Логируем как критическую ошибку
            raise YandexDirectAuthError("Доступ к данному аккаунту запрещен.")
        
        # Получаем расшифрованный токен и проверяем срок действия
        try:
            self.access_token = token_entry.access_token # Используем свойство для дешифровки
            if not self.access_token:
                 raise ValueError("Расшифрованный access_token пуст.")
        except Exception as e_decrypt:
            msg = f"Ошибка дешифровки токена для YandexAccount ID {yandex_account_id}: {e_decrypt}"
            current_app.logger.error(msg)
            # Возможно, стоит удалить невалидный токен или пометить аккаунт как неактивный
            raise YandexDirectAuthError(msg) from e_decrypt
            
        # TODO: Добавить проверку token_entry.expires_at и логику обновления токена, если он истек
        # if datetime.now() >= token_entry.expires_at:
        #     try:
        #         new_access_token, new_refresh_token, new_expires_at = refresh_yandex_token(token_entry.refresh_token)
        #         # Обновить token_entry в БД с шифрованием...
        #         self.access_token = new_access_token
        #     except Exception as e_refresh:
        #         raise YandexDirectAuthError(f"Не удалось обновить истекший токен: {e_refresh}") from e_refresh

        # Получаем логин связанного аккаунта
        if not token_entry.yandex_account:
             msg = f"У токена с ID {token_entry.id} отсутствует связь с YandexAccount."
             current_app.logger.error(msg)
             raise YandexDirectClientError(msg) # Это ошибка данных, не авторизации
        
        self.client_login = token_entry.yandex_account.login
        if not self.client_login:
            msg = f"У YandexAccount ID {yandex_account_id} отсутствует логин."
            current_app.logger.error(msg)
            raise YandexDirectClientError(msg)
        
        current_app.logger.debug(f"Token valid, Client Login: {self.client_login}")

        # --- Получение URL API из конфига --- 
        self.api_v5_url = current_app.config.get('DIRECT_API_V5_URL')
        self.api_v501_url = current_app.config.get('DIRECT_API_V501_URL')

        if not self.api_v5_url:
            raise ValueError("DIRECT_API_V5_URL не настроен в конфигурации")
        if not self.api_v501_url:
            raise ValueError("DIRECT_API_V501_URL не настроен в конфигурации")

        # --- Формирование заголовков --- 
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Client-Login": self.client_login,
            "Accept-Language": "ru",
            # "Use-Operator-Units": "true"
        }
        
        # Словарь для маппинга типов кампаний
        self.campaign_type_map = {
            "TEXT_CAMPAIGN": "Текстово-графические объявления",
            "UNIFIED_CAMPAIGN": "Единая перфоманс-кампания",
            "SMART_CAMPAIGN": "Смарт-баннеры",
            "DYNAMIC_TEXT_CAMPAIGN": "Динамические объявления",
            "MOBILE_APP_CAMPAIGN": "Реклама мобильных приложений",
            "MCBANNER_CAMPAIGN": "Баннер на поиске",
            "CPM_BANNER_CAMPAIGN": "Медийная кампания",
            "CPM_DEALS_CAMPAIGN": "Медийная кампания со сделками",
            "CPM_FRONTPAGE_CAMPAIGN": "Медийная кампания на Главной",
            "CPM_PRICE": "Кампания с фиксированным СРМ"
        }

    # === Декоратор для ретраев ===
    # Определяем типы ошибок, после которых нужно делать ретрай
    RETRYABLE_API_ERROR_CODES = {9000} # Пример: Internal server error
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504} # Too Many Requests, Server errors

    def _is_retryable_exception(self, exception):
        """Проверяет, стоит ли повторять запрос после этой ошибки."""
        # Получаем исключение из retry_state - УБИРАЕМ ЭТО
        # exception = retry_state.outcome.exception()

        # Убираем проверку if not exception:
        # if not exception:
        #     return False

        # Сначала проверяем на явные временные ошибки
        if isinstance(exception, requests.exceptions.Timeout):
            current_app.logger.warning(f"Retryable exception (Timeout): {exception}")
            return True
        if isinstance(exception, requests.exceptions.ConnectionError):
            current_app.logger.warning(f"Retryable exception (ConnectionError): {exception}")
            return True
        if isinstance(exception, YandexDirectTemporaryError):
            current_app.logger.warning(f"Retryable exception (Temporary): {exception}")
            return True # Если мы сами пометили ошибку как временную

        # Затем проверяем другие ошибки YandexDirectClientError по кодам
        if isinstance(exception, YandexDirectClientError):
            if exception.status_code in self.RETRYABLE_STATUS_CODES:
                current_app.logger.warning(f"Retryable exception (Status Code {exception.status_code}): {exception}")
                return True
            # if exception.api_error_code in self.RETRYABLE_API_ERROR_CODES:
            #     current_app.logger.warning(f"Retryable exception (API Code {exception.api_error_code}): {exception}")
            #     return True

        # Если ни одно условие не подошло
        current_app.logger.info(f"Non-retryable exception encountered: {type(exception)} - {exception}")
        return False

    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=2, max=10),
           # Используем retry_if_exception с нашей функцией
           retry=retry_if_exception(_is_retryable_exception),
           reraise=True)
    def _make_request(self, service_path, payload, api_version='v5'):
        """
        Выполняет POST-запрос к указанному сервису API с ретраями.
        (Остальные Args, Returns, Raises как раньше)
        """
        if api_version == 'v5':
            base_url = self.api_v5_url
        elif api_version == 'v501':
            base_url = self.api_v501_url
        else:
            raise ValueError(f"Unsupported API version: {api_version}")
            
        url = f"{base_url}{service_path}"
        # Логируем URL и часть payload для отладки (без секретов!)
        log_payload = payload.copy()
        if 'params' in log_payload and isinstance(log_payload['params'], dict):
             log_payload['params'] = {k: v for k, v in log_payload['params'].items() if k != 'Headers'} # Убираем Headers если есть
        current_app.logger.debug(f"Making request to {url} with payload: {json.dumps(log_payload, ensure_ascii=False)}")
        
        data = json.dumps(payload)

        try:
            result = requests.post(url, headers=self.headers, data=data, timeout=60) # Добавляем таймаут
            current_app.logger.debug(f"Request to {url} completed with status: {result.status_code}")
            # Логируем заголовки ответа для отладки лимитов
            # current_app.logger.debug(f"Response headers: {result.headers}") 
            
            # Обработка специфических кодов ответа Яндекса
            if result.status_code == 401: # Unauthorized
                 raise YandexDirectAuthError("Ошибка авторизации (401). Возможно, токен недействителен.", status_code=401)
            if result.status_code == 403: # Forbidden
                 raise YandexDirectAuthError(f"Доступ запрещен (403) к {url}. Проверьте права токена.", status_code=403)
            if result.status_code == 429: # Too Many Requests
                 raise YandexDirectTemporaryError("Слишком много запросов (429). Повторите попытку позже.", status_code=429)
            if result.status_code >= 500: # Server errors
                 # Ошибки 5xx считаем временными
                 raise YandexDirectTemporaryError(f"Внутренняя ошибка сервера API ({result.status_code}) при запросе к {url}.", status_code=result.status_code)

            # Проверяем на остальные HTTP ошибки
            result.raise_for_status()
            
            response_data = result.json()

            # Проверка на ошибки уровня API в ответе
            if "error" in response_data:
                error = response_data['error']
                error_code = error.get('error_code')
                error_detail = error.get('error_detail', 'N/A')
                error_string = error.get('error_string', 'N/A')
                message = f"API Error ({api_version}): Code {error_code}, {error_string}: {error_detail}"
                
                # Определяем тип ошибки API
                if error_code in {52, 53, 54, 56}: # Коды ошибок авторизации/токена
                     raise YandexDirectAuthError(message, status_code=result.status_code, api_error_code=error_code, api_error_detail=error_detail)
                # Можно добавить коды временных ошибок API, если они известны
                # elif error_code in {9000}:
                #     raise YandexDirectTemporaryError(...) 
                else:
                    raise YandexDirectClientError(message, status_code=result.status_code, api_error_code=error_code, api_error_detail=error_detail)
            
            # Логируем успешный результат (частично)
            result_payload = response_data.get('result')
            if isinstance(result_payload, dict):
                log_result = {k: v for i, (k, v) in enumerate(result_payload.items()) if i < 3} # Первые 3 ключа
            else:
                log_result = str(result_payload)[:100] # Первые 100 символов
            current_app.logger.debug(f"Request successful. Result sample: {log_result}")
            
            return result_payload # Возвращаем только содержимое ключа 'result'

        except requests.exceptions.RequestException as e:
            message = f"Network error during API request to {url}: {e}"
            current_app.logger.warning(message) # Логируем как warning
            raise YandexDirectClientError(message) from e
        except json.JSONDecodeError as e:
            message = f"JSON decoding error for response from {url}: {e}. Response text: {result.text[:500]}"
            current_app.logger.error(message)
            raise YandexDirectClientError(message) from e
        # YandexDirectAuthError и YandexDirectTemporaryError будут перехвачены ретрай-декоратором или проброшены выше
        except Exception as e:
            message = f"Unexpected error during API request to {url}: {e}"
            current_app.logger.exception(message) # Логируем с traceback
            raise YandexDirectClientError(message) from e

    def get_campaigns(self, selection_criteria=None, field_names=None):
        """
        Получает список кампаний, делая запросы к v5 и v501 и объединяя результаты.

        Args:
            selection_criteria (dict, optional): Критерии отбора для API.
            field_names (list, optional): Список запрашиваемых полей.

        Returns:
            list: Список словарей с данными кампаний, отсортированный по имени.
                  Возвращает пустой список, если кампании не найдены или произошли ошибки.
                  Каждый словарь дополнен полем 'readable_type'.
        """
        if field_names is None:
            field_names = ["Id", "Name", "State", "Status", "Type"]

        payload = {
            "method": "get",
            "params": {
                "SelectionCriteria": selection_criteria or {},
                "FieldNames": field_names
            }
        }

        all_campaigns = []
        campaign_ids = set()
        errors = []

        # Запрос к v5
        try:
            result_v5 = self._make_request('campaigns', payload, api_version='v5')
            if result_v5 and 'Campaigns' in result_v5:
                for campaign in result_v5['Campaigns']:
                    if campaign['Id'] not in campaign_ids:
                        all_campaigns.append(campaign)
                        campaign_ids.add(campaign['Id'])
        except YandexDirectClientError as e:
            current_app.logger.warning(f"Failed to get campaigns from v5 for account {self.client_login}: {e}")
            errors.append(f"v5: {e}")

        # Запрос к v501
        try:
            result_v501 = self._make_request('campaigns', payload, api_version='v501')
            if result_v501 and 'Campaigns' in result_v501:
                 for campaign in result_v501['Campaigns']:
                    if campaign['Id'] not in campaign_ids:
                        all_campaigns.append(campaign)
                        campaign_ids.add(campaign['Id'])
        except YandexDirectClientError as e:
            current_app.logger.warning(f"Failed to get campaigns from v501 for account {self.client_login}: {e}")
            errors.append(f"v501: {e}")

        if errors:
            # Сообщаем пользователю об ошибках
            flash(f"Не удалось получить полный список кампаний для аккаунта {self.client_login}. Ошибки: {'; '.join(errors)}", 'warning')
            current_app.logger.error(f"Encountered errors while fetching campaigns for {self.client_login}: {'; '.join(errors)}")
        
        # Добавляем читаемый тип и сортируем
        processed_campaign_list = []
        for campaign in all_campaigns:
            campaign_type_code = campaign.get('Type')
            campaign['readable_type'] = self.campaign_type_map.get(campaign_type_code, campaign_type_code)
            processed_campaign_list.append(campaign)
        
        return sorted(processed_campaign_list, key=lambda c: c.get('Name', ''))

    # --- Другие методы API клиента будут добавлены здесь ---
    # def get_report(...)
    # def block_placements(...) 