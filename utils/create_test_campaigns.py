import os
import sys
import json
import requests
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

# Добавляем корневую папку проекта в sys.path
# Это нужно, чтобы можно было импортировать 'app'
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from app import create_app, db
from app.models import Token
from app.auth.utils import get_valid_token # Импортируем функцию получения токена
# Импортируем функции и константы для тестирования отчетов
from app.reports.utils import fetch_report, get_week_start_dates, get_monday_and_sunday, FIELDS_PLACEMENT

# Загружаем переменные окружения из .env файла
load_dotenv(os.path.join(project_root, '.env'))

# Константы
DIRECT_API_SANDBOX_URL = os.getenv('DIRECT_API_SANDBOX_URL', 'https://api-sandbox.direct.yandex.com/json/v5/')
# !!! ВАЖНО: Замените на логин вашего тестового аккаунта в песочнице Яндекса !!!
SANDBOX_CLIENT_LOGIN = os.getenv('YANDEX_SANDBOX_LOGIN', 'ваш-логин-в-песочнице')


def make_api_request(method, service, params, access_token, client_login):
    """Отправляет запрос к API Яндекс.Директ."""
    url = f"{DIRECT_API_SANDBOX_URL}{service.lower()}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Login": client_login,
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8"
    }
    payload = {
        "method": method,
        "params": params
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload, ensure_ascii=False).encode('utf8'))
        response.raise_for_status() # Проверка на HTTP ошибки (4xx, 5xx)
        result = response.json()

        if 'error' in result:
            print(f"Ошибка API ({service}/{method}): {result['error']['error_string']} ({result['error']['error_code']})")
            print(f"Детали: {result['error']['error_detail']}")
            return None

        print(f"Успешный запрос: {service}/{method}")
        return result.get('result') # Возвращаем только поле 'result'

    except requests.exceptions.RequestException as e:
        print(f"Ошибка HTTP запроса к {url}: {e}")
        return None
    except json.JSONDecodeError:
        print(f"Ошибка декодирования JSON ответа от {url}")
        print(f"Ответ: {response.text}")
        return None

def create_text_campaign_rsya(access_token, client_login, name_prefix="Тест РСЯ "):
    """Создает тестовую РСЯ кампанию, группу объявлений и объявление."""
    campaign_name = f"{name_prefix}{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    today_date = datetime.now().strftime('%Y-%m-%d')

    # 1. Создание кампании
    print(f"Создание кампании '{campaign_name}'...")
    campaign_params = {
        "Campaigns": [
            {
                "Name": campaign_name,
                "StartDate": today_date,
                "TextCampaign": {
                    "BiddingStrategy": {
                        "Search": {"BiddingStrategyType": "SERVING_OFF"}, # Отключаем показы на поиске
                        "Network": { # Стратегия для сетей
                            "BiddingStrategyType": "AVERAGE_CPC", # Явная стратегия
                            "AverageCpc": {
                                "AverageCpc": 1000000 # Пример: 1 у.е. (в микроединицах валюты аккаунта)
                            }
                        }
                    },
                    "Settings": [
                         #{"Option": "SET_NETWORK_TARGETING_ONLY", "Value": "YES"} # Явно указываем только сети
                         # Можно добавить другие настройки при необходимости
                    ]
                }
            }
        ]
    }
    campaign_result = make_api_request('add', 'campaigns', campaign_params, access_token, client_login)

    if not campaign_result or not campaign_result.get('AddResults') or campaign_result['AddResults'][0].get('Errors'):
        print("Не удалось создать кампанию.")
        if campaign_result and campaign_result.get('AddResults') and campaign_result['AddResults'][0].get('Errors'):
            print("Ошибки API:", campaign_result['AddResults'][0]['Errors'])
        return None

    campaign_id = campaign_result['AddResults'][0]['Id']
    print(f"Кампания создана успешно. ID: {campaign_id}")

    # 2. Создание группы объявлений
    print(f"Создание группы объявлений для кампании ID {campaign_id}...")
    adgroup_params = {
        "AdGroups": [
            {
                "Name": f"Группа {datetime.now().strftime('%H-%M-%S')}",
                "CampaignId": campaign_id,
                "RegionIds": [225] # 225 = Россия. Можно выбрать другие регионы
            }
        ]
    }
    adgroup_result = make_api_request('add', 'adgroups', adgroup_params, access_token, client_login)

    if not adgroup_result or not adgroup_result.get('AddResults') or adgroup_result['AddResults'][0].get('Errors'):
        print("Не удалось создать группу объявлений.")
        # По-хорошему, здесь можно добавить удаление созданной кампании, если группа не создалась
        return None

    adgroup_id = adgroup_result['AddResults'][0]['Id']
    print(f"Группа объявлений создана успешно. ID: {adgroup_id}")

    # 3. Создание объявления
    print(f"Создание объявления для группы ID {adgroup_id}...")
    ad_params = {
        "Ads": [
            {
                "AdGroupId": adgroup_id,
                "TextAd": {
                    "Title": "Тестовое РСЯ Объявление",
                    "Text": "Это текст тестового объявления, созданного через API для РСЯ кампании.",
                    "Href": "https://example.com" # Используйте реальный URL, если нужно
                }
            }
        ]
    }
    ad_result = make_api_request('add', 'ads', ad_params, access_token, client_login)

    if not ad_result or not ad_result.get('AddResults') or ad_result['AddResults'][0].get('Errors'):
        print("Не удалось создать объявление.")
        # Аналогично, можно добавить удаление кампании/группы
        return None

    ad_id = ad_result['AddResults'][0]['Id']
    print(f"Объявление создано успешно. ID: {ad_id}")

    # 4. Создание ключевого слова (для активации группы)
    print(f"Создание ключевого слова для группы ID {adgroup_id}...")
    keyword_params = {
        "Keywords": [
            {
                "AdGroupId": adgroup_id,
                "Keyword": "тестовый ключ рся"
                # Можно добавить ставку, если нужно: "Bid": 1000000
            }
        ]
    }
    keyword_result = make_api_request('add', 'keywords', keyword_params, access_token, client_login)

    if not keyword_result or not keyword_result.get('AddResults') or keyword_result['AddResults'][0].get('Errors'):
        print("Не удалось создать ключевое слово.")
        # Здесь тоже можно добавить логику отката (удаление кампании/группы/объявления)
        # Пока просто выводим ошибку и продолжаем к resume
        if keyword_result and keyword_result.get('AddResults') and keyword_result['AddResults'][0].get('Errors'):
             print("Ошибки API при создании ключа:", keyword_result['AddResults'][0]['Errors'])
    else:
        keyword_id = keyword_result['AddResults'][0]['Id']
        print(f"Ключевое слово создано успешно. ID: {keyword_id}")

    # 5. Отправка объявления на модерацию
    print(f"Отправка объявления ID {ad_id} на модерацию...")
    moderate_params = {
        "SelectionCriteria": {
            "Ids": [ad_id] # Отправляем ID созданного объявления
        }
    }
    moderate_result = make_api_request('moderate', 'ads', moderate_params, access_token, client_login)

    if not moderate_result or not moderate_result.get('ModerateResults') or moderate_result['ModerateResults'][0].get('Errors'):
        print(f"Не удалось отправить объявление ID {ad_id} на модерацию.")
        if moderate_result and moderate_result.get('ModerateResults') and moderate_result['ModerateResults'][0].get('Errors'):
            print("Ошибки API при модерации:", moderate_result['ModerateResults'][0]['Errors'])
        # Возвращаем ID кампании, даже если модерация не удалась
    else:
        print(f"Объявление ID {ad_id} успешно отправлено на модерацию.")
        # Это должно автоматически перевести кампанию в статус MODERATION

    print("-" * 20)
    print(f"Успешно создана тестовая РСЯ кампания:")
    print(f"  Имя: {campaign_name}")
    print(f"  ID Кампании: {campaign_id}")
    print(f"  ID Группы: {adgroup_id}")
    print(f"  ID Объявления: {ad_id}")
    print("-" * 20)

    return campaign_id


def create_performance_campaign(access_token, client_login, name_prefix="Тест ЕПК "):
    """Создает тестовую ЕПК (Performance) кампанию."""
    # TODO: Реализовать создание ЕПК, если необходимо.
    # Требует больше параметров, включая CounterId (Метрика), FeedId (если используется)
    # и специфичные настройки стратегии.
    print("Функция create_performance_campaign еще не реализована.")
    return None


def resume_existing_campaigns(access_token, client_login, campaign_ids):
    """Пытается активировать (resume) список существующих кампаний по их ID."""
    if not campaign_ids:
        print("Список ID кампаний для активации пуст.")
        return

    print(f"Попытка активировать кампании с ID: {campaign_ids}...")
    resume_params = {
        "SelectionCriteria": {
            "Ids": campaign_ids
        }
    }
    resume_result = make_api_request('resume', 'campaigns', resume_params, access_token, client_login)

    if not resume_result or not resume_result.get('ResumeResults'):
        print(f"Не удалось отправить запрос на активацию для кампаний: {campaign_ids}.")
        # Дополнительная проверка ошибок может быть добавлена здесь, если API возвращает частичные ошибки
    else:
        results = resume_result['ResumeResults']
        for i, result in enumerate(results):
            campaign_id = campaign_ids[i]
            if result.get('Errors'):
                print(f"Ошибка при активации кампании ID {campaign_id}: {result['Errors']}")
            else:
                print(f"Кампания ID {campaign_id} успешно отправлена на активацию/модерацию.")


def get_campaign_details(access_token, client_login, campaign_ids):
    """Получает и выводит детальную информацию о статусах кампаний по их ID."""
    if not campaign_ids:
        print("Список ID кампаний для получения деталей пуст.")
        return

    print(f"Запрос деталей для кампаний с ID: {campaign_ids}...")
    params = {
        "SelectionCriteria": {
            "Ids": campaign_ids
        },
        "FieldNames": ["Id", "Name", "State", "Status", "StatusPayment", "StatusClarification", "Type"]
    }
    details_result = make_api_request('get', 'campaigns', params, access_token, client_login)

    if not details_result or not details_result.get('Campaigns'):
        print(f"Не удалось получить детали для кампаний: {campaign_ids}.")
    else:
        print("--- Детали кампаний ---")
        for campaign in details_result['Campaigns']:
            print(f"  ID: {campaign.get('Id')}")
            print(f"    Name: {campaign.get('Name')}")
            print(f"    Type: {campaign.get('Type')}")
            print(f"    State: {campaign.get('State')}")
            print(f"    Status: {campaign.get('Status')}")
            print(f"    StatusPayment: {campaign.get('StatusPayment')}")
            print(f"    StatusClarification: {campaign.get('StatusClarification')}")
            print("    -")
        print("-----------------------")


def get_draft_ad_ids_for_campaigns(access_token, client_login, campaign_ids):
    """Получает ID объявлений в статусе DRAFT для указанных кампаний."""
    if not campaign_ids:
        print("Список ID кампаний для поиска объявлений пуст.")
        return []

    print(f"Поиск объявлений в статусе DRAFT для кампаний: {campaign_ids}...")
    ad_ids = []
    params = {
        "SelectionCriteria": {
            "CampaignIds": campaign_ids,
            "Statuses": ["DRAFT"] # Ищем только объявления-черновики
        },
        "FieldNames": ["Id", "CampaignId", "State", "Status"] # Добавил Status для ясности
    }
    # TODO: Учесть возможное ограничение на количество возвращаемых объектов (Limit/Offset)
    # Для небольшого числа кампаний/объявлений это не критично.
    ads_result = make_api_request('get', 'ads', params, access_token, client_login)

    if ads_result and ads_result.get('Ads'):
        for ad in ads_result['Ads']:
            ad_ids.append(ad['Id'])
            print(f"  Найдено объявление ID {ad['Id']} в кампании {ad['CampaignId']} (State: {ad['State']}, Status: {ad.get('Status')})")
    else:
        print(f"Не найдено объявлений в статусе DRAFT для кампаний {campaign_ids} или произошла ошибка API.")

    if not ad_ids:
        print("Не найдено подходящих объявлений для отправки на модерацию.")

    return ad_ids

def moderate_existing_ads(access_token, client_login, ad_ids):
    """Отправляет список существующих объявлений на модерацию."""
    if not ad_ids:
        print("Список ID объявлений для модерации пуст.")
        return

    print(f"Отправка объявлений на модерацию: {ad_ids}...")
    moderate_params = {
        "SelectionCriteria": {
            "Ids": ad_ids
        }
    }
    moderate_result = make_api_request('moderate', 'ads', moderate_params, access_token, client_login)

    if not moderate_result or not moderate_result.get('ModerateResults'):
        print(f"Не удалось отправить запрос на модерацию для объявлений: {ad_ids}.")
    else:
        results = moderate_result['ModerateResults']
        for i, result in enumerate(results):
            ad_id = ad_ids[i] # Предполагаем, что порядок сохраняется
            if result.get('Errors'):
                print(f"Ошибка при модерации объявления ID {ad_id}: {result['Errors']}")
            else:
                print(f"Объявление ID {ad_id} успешно отправлено на модерацию.")


if __name__ == "__main__":
    print("Запуск утилиты создания тестовых кампаний...")

    if SANDBOX_CLIENT_LOGIN == 'ваш-логин-в-песочнице':
         print("!!! ОШИБКА: Пожалуйста, укажите ваш логин песочницы Яндекса в переменной")
         print("YANDEX_SANDBOX_LOGIN в файле .env или прямо в скрипте create_test_campaigns.py")
         print("в переменной SANDBOX_CLIENT_LOGIN.")
         sys.exit(1) # Выход из скрипта

    app = create_app() # Создаем экземпляр Flask-приложения

    # Используем контекст приложения для доступа к db и конфигурации
    with app.app_context():
        print(f"Попытка получить токен для логина: {SANDBOX_CLIENT_LOGIN}")
        access_token = get_valid_token(SANDBOX_CLIENT_LOGIN)

        if access_token:
            print("Токен успешно получен.")

            # --- Включение кампаний (resume) --- (Комментируем для чистоты теста)
            campaign_ids_to_resume = [482489, 482490, 482524, 482525, 482526] # Кампании OFF / ACCEPTED
            # if campaign_ids_to_resume:
            #     print(f"Попытка включить кампании (resume): {campaign_ids_to_resume}...")
            #     resume_existing_campaigns(access_token, SANDBOX_CLIENT_LOGIN, campaign_ids_to_resume)
            # else:
            #     print("Нет ID кампаний для включения.")
            # -----------------------------------

            # --- ТЕСТОВЫЙ ЗАПУСК fetch_report (Комментируем после завершения теста) --- 
            # print("\n--- Запуск тестового запроса отчета --- ")
            # # Выбираем ID кампании для теста (берем первый из списка resume)
            # # !!! Убедись, что хотя бы один ID из списка ниже существует в твоей песочнице !!!
            # test_campaign_ids = campaign_ids_to_resume[:1] 
            # if test_campaign_ids:
            #     print(f"Тестируем на кампаниях: {test_campaign_ids}")
            #     try:
            #         # Определяем даты для прошлой полной недели
            #         past_week_starts = get_week_start_dates(1) 
            #         if past_week_starts:
            #             date_from = past_week_starts[0]
            #             _, date_to = get_monday_and_sunday(date_from) # Получаем воскресенье той же недели
            #             print(f"Период отчета: {date_from} - {date_to}")
            # 
            #             # Задаем поля и имя отчета
            #             field_names_to_test = FIELDS_PLACEMENT
            #             report_name = f"Test_Placement_{date_from.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}"
            #             print(f"Запрашиваемые поля: {field_names_to_test}")
            #             print(f"Имя отчета: {report_name}")
            # 
            #             # Вызываем функцию
            #             parsed_data, raw_data, error_message = fetch_report(
            #                 access_token=access_token,
            #                 client_login=SANDBOX_CLIENT_LOGIN,
            #                 campaign_ids=test_campaign_ids,
            #                 date_from=date_from,
            #                 date_to=date_to,
            #                 field_names=field_names_to_test,
            #                 report_name=report_name
            #             )
            # 
            #             # Печатаем результат
            #             if error_message:
            #                 print(f"\nОШИБКА при получении отчета: {error_message}")
            #             elif parsed_data is not None:
            #                 print(f"\nУСПЕХ! Получено строк данных: {len(parsed_data)}")
            #                 print("Первые 5 строк данных:")
            #                 for i, row in enumerate(parsed_data[:5]):
            #                     print(f"  {i+1}: {row}")
            #             else:
            #                 print("\nНеожиданный результат: нет ни данных, ни сообщения об ошибке.")
            #         else:
            #             print("Не удалось определить дату начала прошлой недели.")
            #     
            #     except Exception as e_test:
            #         print(f"\nНепредвиденная ОШИБКА во время тестового запуска fetch_report: {e_test}")
            # else:
            #     print("Нет ID кампаний в списке campaign_ids_to_resume для запуска теста.")
            # print("--- Тестовый запрос отчета завершен ---\n")
            # --- КОНЕЦ ТЕСТОВОГО ЗАПУСКА --- 


            # --- Отправка существующих объявлений на модерацию (закомментировано) ---
            # campaign_ids_to_moderate = [482489, 482490, 482524, 482525, 482526] # Кампании в статусе DRAFT
            # if campaign_ids_to_moderate:
            #     print("Этап 1: Поиск ID объявлений в статусе DRAFT...")
            #     ad_ids_to_moderate = get_draft_ad_ids_for_campaigns(access_token, SANDBOX_CLIENT_LOGIN, campaign_ids_to_moderate)
            #     if ad_ids_to_moderate:
            #         print("\nЭтап 2: Отправка найденных объявлений на модерацию...")
            #         moderate_existing_ads(access_token, SANDBOX_CLIENT_LOGIN, ad_ids_to_moderate)
            #     else:
            #         print("\nНе найдено объявлений для отправки на модерацию.")
            # else:
            #     print("Нет ID кампаний для поиска объявлений.")
            # ----------------------------------------------------

            # --- Другие действия (закомментировано) ---
            # get_campaign_details(...)
            # create_text_campaign_rsya(...)

        else:
            print(f"Не удалось получить действительный токен для логина {SANDBOX_CLIENT_LOGIN}.")
            print("Убедитесь, что для этого логина был пройден процесс OAuth авторизации")
            print("в основном приложении или что токен еще действителен.")

    print("Работа утилиты завершена.") 