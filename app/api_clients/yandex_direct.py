import requests
import json
import traceback
from flask import current_app

class YandexDirectClientError(Exception):
    """Базовый класс для ошибок API клиента."""
    def __init__(self, message, status_code=None, api_error_code=None, api_error_detail=None):
        super().__init__(message)
        self.status_code = status_code
        self.api_error_code = api_error_code
        self.api_error_detail = api_error_detail

class YandexDirectClient:
    def __init__(self, access_token, client_login, api_v5_url, api_v501_url):
        """
        Инициализирует клиент API Яндекс.Директ.

        Args:
            access_token (str): OAuth токен доступа.
            client_login (str): Логин клиента Яндекс.Директ.
            api_v5_url (str): URL для API v5.
            api_v501_url (str): URL для API v501.
        """
        if not access_token:
            raise ValueError("Access token is required")
        if not client_login:
            raise ValueError("Client login is required")
        # Проверяем переданные аргументы
        if not api_v5_url:
            raise ValueError("API v5 URL is required")
        if not api_v501_url:
            raise ValueError("API v501 URL is required")

        self.access_token = access_token
        self.client_login = client_login
        
        # Используем переданные URL напрямую
        self.api_v5_url = api_v5_url
        self.api_v501_url = api_v501_url

        # Убираем проверку на существование URL в конфиге, т.к. они теперь обязательные аргументы
        # if not self.api_v5_url:
        #     raise ValueError("API v5 URL is not configured")
        # if not self.api_v501_url:
        #     raise ValueError("API v501 URL is not configured")

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Client-Login": self.client_login,
            "Accept-Language": "ru",
            # "Use-Operator-Units": "true" # Можно раскомментировать для отладки баллов
        }
        
        # Словарь для маппинга типов кампаний - переносим сюда
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

    def _make_request(self, service_path, payload, api_version='v5'):
        """
        Выполняет POST-запрос к указанному сервису API.

        Args:
            service_path (str): Путь к сервису (например, 'campaigns', 'reports').
            payload (dict): Тело запроса в формате словаря Python.
            api_version (str): Версия API ('v5' или 'v501').

        Returns:
            dict: Результат запроса в формате словаря Python.

        Raises:
            YandexDirectClientError: В случае сетевой ошибки или ошибки API.
        """
        if api_version == 'v5':
            base_url = self.api_v5_url
        elif api_version == 'v501':
            base_url = self.api_v501_url
        else:
            raise ValueError(f"Unsupported API version: {api_version}")
            
        url = f"{base_url}{service_path}"
        data = json.dumps(payload)

        try:
            result = requests.post(url, headers=self.headers, data=data)
            result.raise_for_status()
            
            response_data = result.json()

            if "error" in response_data:
                error = response_data['error']
                error_code = error.get('error_code')
                error_detail = error.get('error_detail', 'N/A')
                error_string = error.get('error_string', 'N/A')
                message = f"API Error ({api_version}): Code {error_code}, {error_string}: {error_detail}"
                raise YandexDirectClientError(message, status_code=result.status_code, api_error_code=error_code, api_error_detail=error_detail)
            
            return response_data.get('result')

        except requests.exceptions.RequestException as e:
            message = f"Network error during API request to {url}: {e}"
            raise YandexDirectClientError(message) from e
        except json.JSONDecodeError as e:
            message = f"JSON decoding error for response from {url}: {e}"
            raise YandexDirectClientError(message) from e
        except Exception as e:
            message = f"Unexpected error during API request to {url}: {e}"
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
            errors.append(f"Failed to get campaigns from v5: {e}")

        # Запрос к v501
        try:
            result_v501 = self._make_request('campaigns', payload, api_version='v501')
            if result_v501 and 'Campaigns' in result_v501:
                 for campaign in result_v501['Campaigns']:
                    if campaign['Id'] not in campaign_ids:
                        all_campaigns.append(campaign)
                        campaign_ids.add(campaign['Id'])
        except YandexDirectClientError as e:
            errors.append(f"Failed to get campaigns from v501: {e}")

        if errors:
            # Можно решить, что делать с ошибками: пробросить дальше, вернуть пустой список, 
            # вернуть частичный результат и ошибки и т.д. Пока просто логируем и возвращаем что есть.
            print(f"Encountered errors while fetching campaigns: {'; '.join(errors)}")
        
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