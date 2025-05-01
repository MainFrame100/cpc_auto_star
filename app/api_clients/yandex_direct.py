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

class YandexDirectReportError(YandexDirectClientError):
    """Ошибка, специфичная для API отчетов (например, отчет не готов после всех попыток)."""
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
            
        # Добавляем URL для API Отчетов
        self.reports_api_url = f"{self.api_v5_url}reports" # Базовый URL для отчетов

        # --- Формирование заголовков --- 
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Client-Login": self.client_login,
            "Accept-Language": "ru",
            # "Use-Operator-Units": "true"
        }
        
        # Добавляем заголовки специфичные для API Отчетов
        self.report_headers = self.headers.copy()
        self.report_headers['returnMoneyInMicros'] = 'false'
        self.report_headers['skipReportSummary'] = 'true'
        # self.report_headers['skipColumnHeader'] = 'true' # Оставим заголовки столбцов
        # self.report_headers['skipReportHeader'] = 'true' # Оставим заголовок отчета
        
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

    # === Логика ретраев для _make_request ===
    RETRYABLE_API_ERROR_CODES = {9000} # Пример: Internal server error
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504} # Too Many Requests, Server errors

    def _is_retryable_exception(self, exception):
        """Проверяет, стоит ли повторять запрос после этой ошибки."""
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
        (Предназначен для стандартных запросов API, не для отчетов)
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
            # Используем self.headers (стандартные заголовки)
            result = requests.post(url, headers=self.headers, data=data, timeout=60) 
            current_app.logger.debug(f"Request to {url} completed with status: {result.status_code}")
            
            # Обработка специфических кодов ответа Яндекса
            if result.status_code == 401: # Unauthorized
                 raise YandexDirectAuthError("Ошибка авторизации (401). Возможно, токен недействителен.", status_code=401)
            if result.status_code == 403: # Forbidden
                 raise YandexDirectAuthError(f"Доступ запрещен (403) к {url}. Проверьте права токена.", status_code=403)
            if result.status_code == 429: # Too Many Requests
                 raise YandexDirectTemporaryError("Слишком много запросов (429). Повторите попытку позже.", status_code=429)
            if result.status_code >= 500: # Server errors
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
                elif error_code in self.RETRYABLE_API_ERROR_CODES:
                     raise YandexDirectTemporaryError(message, status_code=result.status_code, api_error_code=error_code, api_error_detail=error_detail) 
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

        except requests.exceptions.Timeout as e_timeout:
             message = f"Network timeout during API request to {url}: {e_timeout}"
             current_app.logger.warning(message) 
             # Tenacity должен обработать
             raise YandexDirectTemporaryError(message) from e_timeout
        except requests.exceptions.ConnectionError as e_conn:
             message = f"Network connection error during API request to {url}: {e_conn}"
             current_app.logger.warning(message) 
             # Tenacity должен обработать
             raise YandexDirectTemporaryError(message) from e_conn
        except requests.exceptions.RequestException as e:
            message = f"Network error during API request to {url}: {e}"
            current_app.logger.warning(message) # Логируем как warning
            # Считаем другие сетевые ошибки не временными для _make_request?
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

    # === Метод для получения отчетов ===

    def get_report(self, report_definition: dict) -> str:
        """
        Запрашивает, ожидает и возвращает сырые данные отчета (TSV).
        Внутренний цикл обрабатывает ожидание (201/202) и ретраи временных ошибок.
        """
        if not isinstance(report_definition, dict) or 'params' not in report_definition:
             raise ValueError("Некорректная структура report_definition. Ожидается dict с ключом 'params'.")

        report_name = report_definition.get('params', {}).get('ReportName', 'UnnamedReport')
        current_app.logger.info(f"Запрос отчета '{report_name}' для аккаунта {self.client_login}...")

        # --- Используем сессию requests ---
        session = requests.Session()
        session.headers.update(self.report_headers)

        # --- Цикл ожидания отчета с ретраями временных ошибок ---
        retry_delay = 5 
        attempt = 0
        MAX_ATTEMPTS = 25  
        RETRY_DELAY_MAX = 60 
        temporary_error_retries = 0
        MAX_TEMPORARY_ERROR_RETRIES = 5 

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            current_app.logger.info(f"  Попытка {attempt}/{MAX_ATTEMPTS}: Запрос статуса/данных отчета '{report_name}'...")
            
            try:
                response = session.post(
                    self.reports_api_url,
                    json=report_definition,
                    timeout=90 
                )

                status_code = response.status_code
                request_id = response.headers.get("RequestId", "N/A")
                units_used = response.headers.get("units", "N/A")
                current_app.logger.debug(f"    Статус ответа: {status_code}. RequestId: {request_id}. Units: {units_used}")

                # Сбрасываем счетчик временных ошибок при успешном запросе (даже если отчет не готов)
                temporary_error_retries = 0 

                # --- Обработка статусов ответа --- 
                if status_code == 200: 
                    current_app.logger.info(f"    Отчет '{report_name}' готов!")
                    report_data = response.text 
                    return report_data
                elif status_code in [201, 202]: 
                    retry_interval_header = response.headers.get("retryIn", str(retry_delay))
                    try:
                        current_retry_delay = min(max(int(retry_interval_header), 5), RETRY_DELAY_MAX)
                    except ValueError:
                        current_retry_delay = min(retry_delay * 2, RETRY_DELAY_MAX)
                    retry_delay = current_retry_delay
                    status_message = "принят в обработку (201)" if status_code == 201 else "еще не готов (202)"
                    current_app.logger.info(f"    Отчет '{report_name}' {status_message}. Повтор через {current_retry_delay} сек...")
                    time.sleep(current_retry_delay)
                    continue 

                # --- Обработка НЕ временных ошибок API отчетов --- 
                elif status_code == 400:
                     error_detail = self._get_error_detail(response)
                     error_msg = f"Ошибка 400 в запросе отчета '{report_name}'. RequestId: {request_id}. Detail: {error_detail}"
                     current_app.logger.error(error_msg)
                     raise YandexDirectReportError(error_msg, status_code=status_code, api_error_detail=error_detail)
                elif status_code == 401:
                     raise YandexDirectAuthError(f"Ошибка авторизации (401) при запросе отчета '{report_name}'.", status_code=status_code)
                elif status_code == 403:
                     raise YandexDirectAuthError(f"Доступ запрещен (403) к API отчетов для '{report_name}'.", status_code=status_code)

                # --- Обработка ВРЕМЕННЫХ ошибок API (429, 5xx) --- 
                elif status_code == 429 or status_code >= 500:
                     error_message_map = {
                         429: "Слишком много запросов (429)",
                         500: "Внутренняя ошибка сервера (500)",
                         502: "Bad Gateway (502)",
                         503: "Service Unavailable (503)",
                         504: "Gateway Timeout (504)",
                     }
                     error_reason = error_message_map.get(status_code, f"Ошибка сервера ({status_code})")
                     error_msg = f"{error_reason} при запросе отчета '{report_name}'. RequestId: {request_id}."
                     current_app.logger.warning(error_msg + f" Попытка ретрая временной ошибки ({temporary_error_retries+1}/{MAX_TEMPORARY_ERROR_RETRIES})...")
                     temporary_error_retries += 1
                     if temporary_error_retries >= MAX_TEMPORARY_ERROR_RETRIES:
                         current_app.logger.error(f"Превышено количество ретраев ({MAX_TEMPORARY_ERROR_RETRIES}) для временных ошибок API при запросе отчета '{report_name}'.")
                         raise YandexDirectTemporaryError(f"{error_reason} после {MAX_TEMPORARY_ERROR_RETRIES} попыток.", status_code=status_code)
                     server_retry_delay = min(wait_exponential(multiplier=1, min=5, max=30)(temporary_error_retries), RETRY_DELAY_MAX)
                     time.sleep(server_retry_delay)
                     continue
                
                else: # Другие неожиданные HTTP ошибки
                    error_detail = self._get_error_detail(response)
                    error_msg = f"Неожиданный статус {status_code} при запросе отчета '{report_name}'. RequestId: {request_id}. Detail: {error_detail}"
                    current_app.logger.error(error_msg)
                    raise YandexDirectReportError(error_msg, status_code=status_code, api_error_detail=error_detail)

            # --- Обработка сетевых ошибок и таймаутов --- 
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e_net:
                error_msg = f"Сетевая ошибка/таймаут при запросе отчета '{report_name}' (попытка {attempt}): {e_net}"
                current_app.logger.warning(error_msg + f" Попытка ретрая временной ошибки ({temporary_error_retries+1}/{MAX_TEMPORARY_ERROR_RETRIES})...")
                temporary_error_retries += 1
                if temporary_error_retries >= MAX_TEMPORARY_ERROR_RETRIES:
                     current_app.logger.error(f"Превышено количество ретраев ({MAX_TEMPORARY_ERROR_RETRIES}) для сетевых ошибок при запросе отчета '{report_name}'.")
                     raise YandexDirectTemporaryError(f"Сетевая ошибка/таймаут после {MAX_TEMPORARY_ERROR_RETRIES} попыток.") from e_net
                network_retry_delay = min(wait_exponential(multiplier=1, min=5, max=30)(temporary_error_retries), RETRY_DELAY_MAX)
                time.sleep(network_retry_delay)
                continue
            
            except requests.exceptions.RequestException as e_req:
                error_msg = f"Критическая сетевая ошибка при запросе отчета '{report_name}' (попытка {attempt}): {e_req}"
                current_app.logger.error(error_msg)
                raise YandexDirectClientError(error_msg) from e_req
            # --- Конец блока try ---

        # --- Если цикл завершился без получения отчета --- 
        error_msg = f"Отчет '{report_name}' не был готов или ошибка после {MAX_ATTEMPTS} попыток."
        current_app.logger.error(error_msg)
        raise YandexDirectReportError(error_msg)

    def _get_error_detail(self, response: requests.Response) -> str:
        """Вспомогательная функция для извлечения деталей ошибки из ответа."""
        try:
             # Пытаемся разобрать JSON, если есть
             error_data = response.json().get('error', {})
             return json.dumps(error_data, ensure_ascii=False)
        except json.JSONDecodeError:
             # Если не JSON, возвращаем текст
             return response.text[:500] # Ограничиваем длину

    # === Существующие методы ===
    def get_campaigns(self, selection_criteria=None, field_names=None):
        """
        Получает список кампаний с использованием стандартного _make_request.
        """
        payload = {
            "method": "get",
            "params": {
                "FieldNames": field_names or ["Id", "Name", "Type", "State", "Status"],
            }
        }
        if selection_criteria:
             payload["params"]["SelectionCriteria"] = selection_criteria
             
        return self._make_request("/campaigns", payload)

    def get_clients(self):
        """
        Получает информацию о клиенте (для прямого рекламодателя).
        Использует API v5.01.
        """
        payload = {
             "method": "get",
             "params": {
                 "FieldNames": ["Login", "ClientId", "ClientInfo", "Grants", "Representatives", "Settings", "Type"]
             }
         }
        return self._make_request("/clients", payload, api_version='v501')
         
    def get_agency_clients(self):
        """
        Получает список клиентов агентства.
        """
        payload = {
             "method": "get",
             "params": {
                 "FieldNames": ["Login", "ClientId", "ClientInfo"]
             }
         }
        # Использует стандартный сервис clients API v5
        return self._make_request("/agencyclients", payload)

    def get_adgroups(self, campaign_ids: list[int], field_names: list[str] = ["Id", "Name", "CampaignId", "Status", "Type"]):
        """
        Получает группы объявлений для указанных кампаний.
        """
        payload = {
            "method": "get",
            "params": {
                "SelectionCriteria": {
                    "CampaignIds": campaign_ids
                },
                "FieldNames": field_names
            }
        }
        return self._make_request("/adgroups", payload)

    def set_adgroup_bids(self, bids: list[dict]):
        """
        Устанавливает ставки для групп объявлений.
        Ожидает список словарей, каждый из которых содержит AdGroupId и Bid.
        """
        payload = {
            "method": "set",
            "params": {
                "Bids": bids # [{ "AdGroupId": id1, "Bid": bid1 }, { "AdGroupId": id2, "Bid": bid2 }, ...]
            }
        }
        return self._make_request("/bids", payload)
        
    def suspend_adgroups(self, adgroup_ids: list[int]):
        """
        Останавливает показы для указанных групп объявлений.
        """
        payload = {
            "method": "suspend",
            "params": { 
                "SelectionCriteria": { 
                    "Ids": adgroup_ids 
                 } 
            }
        }
        return self._make_request("/adgroups", payload)

    def resume_adgroups(self, adgroup_ids: list[int]):
        """
        Возобновляет показы для указанных групп объявлений.
        """
        payload = {
            "method": "resume",
            "params": { 
                "SelectionCriteria": { 
                    "Ids": adgroup_ids 
                 } 
            }
        }
        return self._make_request("/adgroups", payload)

    def get_campaign_type_display_name(self, campaign_type_api_name: str) -> str:
         """Возвращает человекочитаемое название типа кампании."""
         return self.campaign_type_map.get(campaign_type_api_name, campaign_type_api_name) # Возвращаем исходное, если нет в мапе 