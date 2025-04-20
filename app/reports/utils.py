import requests
import json
import time
import io
import csv
from datetime import date, timedelta, datetime
import os
import traceback # Для детального логирования ошибок

# Импорты из приложения
from app import db
from app.models import (
    Token, WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat, 
    WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat
)
from app.auth.utils import get_valid_token

# URL API Отчетов (песочница)
REPORTS_API_SANDBOX_URL = os.getenv('DIRECT_API_SANDBOX_URL_REPORTS', 'https://api-sandbox.direct.yandex.com/json/v5/reports') # Уточним имя переменной
DIRECT_API_CAMPAIGNS_URL = os.getenv('DIRECT_API_SANDBOX_URL_CAMPAIGNS', 'https://api-sandbox.direct.yandex.com/json/v5/campaigns') # Для кампаний

# Константы для ожидания отчета
MAX_RETRIES = 15
RETRY_DELAY_SECONDS = 5
API_CALL_DELAY = 2 # Задержка между запросами к API Отчетов

# Списки полей для разных срезов отчетов
# Общие метрики
BASE_METRICS = ['Impressions', 'Clicks', 'Cost']

# Поля для среза "Кампания" (самый базовый)
FIELDS_CAMPAIGN = ['CampaignId'] + BASE_METRICS

# Поля для среза "Площадки"
FIELDS_PLACEMENT = ['CampaignId', 'Placement', 'AdNetworkType'] + BASE_METRICS

# Поля для среза "Поисковые запросы"
# Внимание: Отчет по запросам может быть очень большим!
FIELDS_QUERY = ['CampaignId', 'AdGroupId', 'Query'] + BASE_METRICS

# Поля для среза "География"
# CriteriaId - это ID региона из гео-справочника Яндекса
FIELDS_GEO = ['CampaignId', 'CriteriaId'] + BASE_METRICS

# Поля для среза "Устройства"
FIELDS_DEVICE = ['CampaignId', 'Device'] + BASE_METRICS

# Поля для среза "Пол и возраст"
FIELDS_DEMOGRAPHIC = ['CampaignId', 'Gender', 'Age'] + BASE_METRICS

def get_monday_and_sunday(target_date: date = None) -> tuple[date, date]:
    """Возвращает дату понедельника и воскресенья для недели, содержащей target_date.

    Если target_date не указана, используется текущая дата.
    """
    if target_date is None:
        target_date = date.today()
    # weekday() возвращает 0 для понедельника, ..., 6 для воскресенья
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week


def get_week_start_dates(n_weeks: int) -> list[date]:
    """Возвращает список дат начала (понедельников) для последних n_weeks полных недель.

    Текущая неделя не включается.
    """
    today = date.today()
    # Находим понедельник *прошлой* недели
    last_week_monday = today - timedelta(days=today.weekday() + 7)
    week_start_dates = []
    for i in range(n_weeks):
        monday = last_week_monday - timedelta(weeks=i)
        week_start_dates.append(monday)
    return sorted(week_start_dates) # Возвращаем от самой старой к самой новой

def fetch_report(access_token: str, client_login: str, campaign_ids: list[int], 
                 date_from: date, date_to: date, field_names: list[str], report_name: str, 
                 report_type: str = 'CUSTOM_REPORT') -> tuple[list[dict] | None, str | None, str | None]:
    """Заказывает, ожидает и парсит отчет из API Яндекс.Директ v5.

    Args:
        access_token: Действительный OAuth-токен.
        client_login: Логин клиента в Яндекс.Директе.
        campaign_ids: Список ID кампаний для отчета.
        date_from: Дата начала периода отчета.
        date_to: Дата окончания периода отчета.
        field_names: Список полей (Dimension и Metric) для включения в отчет.
        report_name: Уникальное имя отчета для API.
        report_type: Тип отчета (по умолчанию CUSTOM_REPORT).

    Returns:
        Кортеж: (parsed_data, raw_data, error_message).
        parsed_data: Список словарей с данными отчета или None при ошибке.
        raw_data: Сырой текст отчета (TSV) или None при ошибке.
        error_message: Строка с описанием ошибки или None при успехе.
    """
    print(f"Запуск fetch_report для {len(campaign_ids)} кампаний ({campaign_ids[:3]}...), период: {date_from} - {date_to}, отчет: {report_name}")
    if not campaign_ids:
        return [], None, "Список ID кампаний пуст."

    # --- 1. Заказ отчета --- 
    headers_post = {
        'Authorization': f'Bearer {access_token}',
        'Client-Login': client_login,
        'Accept-Language': 'ru',
        'Content-Type': 'application/json',
        'returnMoneyInMicros': 'false',
        'skipReportHeader': 'true',
        'skipReportSummary': 'true' # Итоговая строка не нужна
    }
    if not client_login: # Если client_login пуст (например, для агентского аккаунта без выбора клиента)
        headers_post.pop('Client-Login', None)

    report_definition = {
        'params': {
            'SelectionCriteria': {
                'Filter': [{
                    'Field': 'CampaignId',
                    'Operator': 'IN',
                    'Values': [str(cid) for cid in campaign_ids]
                }],
                # Используем переданные даты
                'DateFrom': date_from.strftime('%Y-%m-%d'),
                'DateTo': date_to.strftime('%Y-%m-%d')
            },
            'FieldNames': field_names,
            'ReportName': report_name, # Используем переданное имя
            'ReportType': report_type, # Используем переданный тип
            'DateRangeType': 'CUSTOM_DATE', # Явно указываем, что используем свои даты
            'Format': 'TSV',
            'IncludeVAT': 'NO', # Обычно статистику смотрят без НДС
            'IncludeDiscount': 'NO'
            # 'Page': { 'Limit': 1000000 } # Можно раскомментировать, если строк очень много
        }
    }

    report_data_raw = None
    retries = 0
    MAX_REPORT_RETRIES = 20 # Максимальное число попыток получить отчет

    while retries < MAX_REPORT_RETRIES:
        retries += 1
        print(f"  Попытка {retries}/{MAX_REPORT_RETRIES}: Отправка POST-запроса для {report_name}...")
        try:
            response = requests.post(REPORTS_API_SANDBOX_URL, headers=headers_post, json=report_definition, timeout=60) # Добавим таймаут
            
            status_code = response.status_code
            request_id = response.headers.get("RequestId", "N/A")
            units_used = response.headers.get("units", "N/A")
            print(f"    Статус ответа: {status_code}. RequestId: {request_id}. Units: {units_used}")

            if status_code == 200:
                print(f"    Отчет {report_name} готов!")
                report_data_raw = response.text
                break
            elif status_code in [201, 202]:
                retry_interval_header = response.headers.get("retryIn", "10") # Дефолт 10 сек
                try:
                    retry_interval = max(int(retry_interval_header), 5) # Минимум 5 секунд
                except ValueError:
                    retry_interval = 10
                print(f"    Отчет {report_name} формируется. Повтор через {retry_interval} секунд...")
                time.sleep(retry_interval)
                continue
            else:
                # Попытаемся извлечь ошибку из тела ответа
                error_detail = ""
                try:
                    error_data = response.json()
                    error_detail = json.dumps(error_data.get('error', {}), ensure_ascii=False)
                except json.JSONDecodeError:
                    error_detail = response.text[:500] # Первые 500 символов текста ошибки
                
                error_msg = f"Ошибка HTTP {status_code} при запросе отчета {report_name}. RequestId: {request_id}. Detail: {error_detail}"
                print(error_msg)
                response.raise_for_status() # Это вызовет HTTPError

        except requests.exceptions.HTTPError as e_http:
            error_msg = f"Ошибка HTTP при запросе отчета {report_name}: {e_http}. Ответ: {getattr(e_http.response, 'text', 'N/A')[:500]}"
            print(error_msg)
            return None, None, error_msg 
        except requests.exceptions.Timeout:
            error_msg = f"Таймаут при запросе отчета {report_name}. Повтор через 60 сек..."
            print(error_msg)
            time.sleep(60) 
            continue # Продолжаем цикл
        except requests.exceptions.RequestException as e_req:
            error_msg = f"Сетевая ошибка при запросе отчета {report_name}: {e_req}. Повтор через 60 сек..."
            print(error_msg)
            time.sleep(60)
            continue # Продолжаем цикл
        except Exception as e_generic:
            error_msg = f"Непредвиденная ошибка при запросе отчета {report_name}: {e_generic}"
            print(error_msg)
            return None, None, error_msg

    if report_data_raw is None:
         error_msg = f"Отчет {report_name} не был готов после {MAX_REPORT_RETRIES} попыток."
         print(error_msg)
         return None, None, error_msg

    # --- 3. Парсинг отчета (TSV) --- 
    parsed_data = []
    parsing_error_msg = None
    rows_processed = 0 
    headers_list = [] 
    try:
        print(f"Парсинг TSV данных отчета {report_name} с помощью csv.DictReader...")
        report_file = io.StringIO(report_data_raw)

        # Используем csv.DictReader. Он сам использует первую строку как заголовки.
        # Убедимся, что в запросе skipReportHeader='false' (или не указан, что = false).
        tsv_reader = csv.DictReader(report_file, delimiter='\t') 
        headers_list = tsv_reader.fieldnames # Получаем заголовки из DictReader
        
        if not headers_list:
             print(f"  Отчет {report_name} не содержит заголовков столбцов (пустой?).")
             return [], report_data_raw, None

        print(f"  Заголовки столбцов из отчета {report_name}: {headers_list}")

        # Читаем данные
        for row in tsv_reader: # DictReader уже пропустил строку заголовков
            rows_processed += 1
            # Проверяем на строку итогов (на всякий случай)
            # В DictReader ключи - это заголовки. Проверим первый ключ/значение.
            first_key = headers_list[0] if headers_list else None
            if first_key and str(row.get(first_key, '')).startswith("Total rows"):
                 print("  Обнаружена и пропущена строка итогов.")
                 continue

            # Обрабатываем строку (row уже словарь)
            parsed_row = {}
            for header, value in row.items():
                if header is None: # Пропускаем колонки без заголовка (если вдруг есть)
                    continue
                # Логика преобразования '--' и типов
                if value == '--':
                    parsed_row[header] = None 
                else:
                    try:
                        # Пытаемся преобразовать в число (float, затем int)
                        # Заменяем запятую на точку для совместимости
                        num_val = float(value.replace(',', '.')) 
                        if num_val.is_integer():
                            parsed_row[header] = int(num_val)
                        else:
                            parsed_row[header] = num_val
                    except (ValueError, TypeError): # Добавляем TypeError на случай None и др.
                        parsed_row[header] = value # Оставляем как строку
            
            parsed_data.append(parsed_row)

        print(f"  Парсинг отчета {report_name} завершен. Строк данных прочитано: {rows_processed}. Сохранено: {len(parsed_data)}.")
        return parsed_data, report_data_raw, None

    except csv.Error as e_csv: # Ошибки CSV 
        parsing_error_msg = f"Ошибка CSV парсинга в отчете {report_name} (строка ~{rows_processed+1}): {e_csv}"
        print(parsing_error_msg)
        return None, report_data_raw, parsing_error_msg 
    except Exception as e_parse: # Любые другие ошибки парсинга
        parsing_error_msg = f"Непредвиденная ошибка при парсинге отчета {report_name}: {e_parse}"
        traceback.print_exc()
        print(parsing_error_msg)
        return None, report_data_raw, parsing_error_msg

# --- Функции для работы с API Campaigns --- 

def get_active_campaigns(access_token: str, client_login: str) -> tuple[list[dict] | None, str | None]:
    """Получает список активных кампаний пользователя из API Яндекс.Директ.

    Args:
        access_token: Действительный OAuth-токен.
        client_login: Логин клиента в Яндекс.Директе.

    Returns:
        Кортеж: (campaign_list, error_message).
        campaign_list: Список словарей с данными кампаний (Id, Name, State, Status, Type)
                       или None при ошибке.
        error_message: Строка с описанием ошибки или None при успехе.
    """
    print(f"Получение списка активных кампаний для {client_login}...")
    campaigns_url = f"{DIRECT_API_CAMPAIGNS_URL}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Login": client_login,
        "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8"
    }
    # Запрашиваем только активные кампании (не архивные)
    # Можно добавить и другие фильтры по состоянию/статусу, если нужно
    payload = json.dumps({
        "method": "get",
        "params": {
            "SelectionCriteria": {
                 "States": ["ON", "OFF", "SUSPENDED"] # Исключаем ARCHIVED
                 # Можно добавить "Statuses": ["ACCEPTED", "MODERATION", "DRAFT"] и т.п.
            },
            "FieldNames": ["Id", "Name", "State", "Status", "Type"] 
        }
    })

    try:
        response = requests.post(campaigns_url, headers=headers, data=payload, timeout=30)
        units_used = response.headers.get("units", "N/A")
        print(f"  Запрос кампаний: Статус {response.status_code}, Units: {units_used}")
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            error = data['error']
            error_message = f"Ошибка API при получении кампаний: Код {error.get('error_code', 'N/A')}, {error.get('error_string', 'N/A')}: {error.get('error_detail', 'N/A')}"
            print(f"  {error_message}")
            return None, error_message
        elif data.get('result') and 'Campaigns' in data['result']:
            campaign_list = data['result']['Campaigns']
            print(f"  Получено {len(campaign_list)} активных кампаний.")
            return campaign_list, None
        else:
            # Если Campaigns нет, но и ошибки нет - вероятно, кампаний просто 0
            if data.get('result') is not None:
                 print(f"  Активных кампаний не найдено для {client_login}.")
                 return [], None # Возвращаем пустой список
            else: 
                 error_message = "Неожиданный формат ответа API при получении кампаний (нет result)."
                 print(f"  {error_message}")
                 print(f"  Ответ API: {data}")
                 return None, error_message

    except requests.exceptions.Timeout:
        error_message = "Таймаут при запросе списка кампаний."
        print(f"  {error_message}")
        return None, error_message
    except requests.exceptions.RequestException as e:
        error_message = f"Сетевая ошибка при запросе кампаний: {e}"
        print(f"  {error_message}")
        return None, error_message
    except json.JSONDecodeError as e:
        error_message = f"Ошибка декодирования JSON при запросе кампаний: {e}"
        print(f"  {error_message}")
        print(f"  Raw response: {response.text[:500]}...")
        return None, error_message
    except Exception as e:
        error_message = f"Непредвиденная ошибка при запросе кампаний: {e}"
        print(f"  {error_message}")
        return None, error_message

# --- Основная функция сбора статистики --- 

def collect_weekly_stats_for_last_n_weeks(yandex_login: str, n_weeks: int = 4):
    """Собирает еженедельную статистику за последние n полных недель для пользователя.

    Args:
        yandex_login: Логин пользователя в Яндексе.
        n_weeks: Количество последних полных недель для сбора данных.

    Returns:
        Кортеж (success, message).
        success: True, если сбор прошел успешно (даже если данных не было), False при ошибке.
        message: Сообщение о результате или ошибке.
    """
    print(f"\n=== Запуск сбора еженедельной статистики для {yandex_login} за {n_weeks} недель ===")
    
    # 1. Получаем валидный токен
    access_token = get_valid_token(yandex_login)
    if not access_token:
        error_msg = f"Не удалось получить действительный токен для {yandex_login}. Сбор остановлен."
        print(error_msg)
        return False, error_msg
    print("Действующий токен получен.")

    # 2. Получаем список активных кампаний
    campaign_list, error_msg_campaigns = get_active_campaigns(access_token, yandex_login)
    if error_msg_campaigns:
        print(f"Ошибка получения списка кампаний: {error_msg_campaigns}. Сбор остановлен.")
        return False, f"Ошибка получения списка кампаний: {error_msg_campaigns}"
    if not campaign_list:
        print("Активные кампании не найдены. Сбор статистики не требуется.")
        return True, "Активные кампании не найдены."
    # Получаем только ID кампаний
    campaign_ids = [c['Id'] for c in campaign_list]
    print(f"Найдено {len(campaign_ids)} активных кампаний: {campaign_ids[:5]}...")

    # 3. Определяем даты недель
    week_start_dates = get_week_start_dates(n_weeks)
    if not week_start_dates:
         print("Не удалось определить даты для сбора статистики. Сбор остановлен.")
         return False, "Не удалось определить даты недель."
    print(f"Будут обработаны недели, начинающиеся с: {week_start_dates}")

    # 4. Цикл по неделям
    total_reports_requested = 0
    total_errors = 0
    all_stats_objects = [] 

    # Определяем ID кампании для теста (берем первую из списка)
    test_campaign_id_list = campaign_ids[:1] if campaign_ids else []
    if not test_campaign_id_list:
        print("Нет кампаний для тестового запроса.")
        return True, "Нет активных кампаний для сбора статистики."
    print(f"!!! ТЕСТОВЫЙ РЕЖИМ: Запрашиваем данные только для кампании ID: {test_campaign_id_list[0]} !!!")

    for week_start in week_start_dates:
        _, week_end = get_monday_and_sunday(week_start)
        week_str = week_start.strftime('%Y-%m-%d')
        print(f"\n-- Обработка недели: {week_str} ({week_start} - {week_end}) --")

        # Предварительно удаляем ВСЕ данные для этого пользователя и этой недели из ВСЕХ таблиц
        # Это гарантирует перезапись при обновлении.
        # Возможно, лучше удалять только для конкретного среза перед его загрузкой?
        # Пока удаляем всё для недели перед началом обработки срезов.
        # TODO: Рассмотреть более гранулярное удаление.
        try:
            print(f"  Удаление старых данных для пользователя {yandex_login}, недели {week_str}...")
            tables_to_clear = [
                WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat,
                WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat
            ]
            deleted_counts = {}
            for table_model in tables_to_clear:
                # Используем db.session.query(table_model) вместо table_model.query 
                # чтобы избежать конфликта имен с колонкой 'query' в WeeklySearchQueryStat
                if table_model == WeeklyCampaignStat:
                     delete_query = db.session.query(table_model).filter(
                         table_model.yandex_login == yandex_login,
                         table_model.week_start_date == week_start
                     )
                else:
                     delete_query = db.session.query(table_model).filter(
                         table_model.yandex_login == yandex_login,
                         table_model.week_start_date == week_start
                     )
                
                deleted_count = delete_query.delete(synchronize_session=False) 
                deleted_counts[table_model.__tablename__] = deleted_count
            
            db.session.commit() # Коммитим удаление
            print(f"  Старые данные удалены: {deleted_counts}")

        except Exception as e_delete:
            db.session.rollback() # Откатываем транзакцию при ошибке удаления
            error_msg_delete = f"Ошибка при удалении старых данных для недели {week_str}: {e_delete}"
            print(f"  {error_msg_delete}")
            traceback.print_exc()
            total_errors += 1
            continue # Пропускаем эту неделю, если не удалось очистить данные

        # --- СБОР ДАННЫХ ПО КАМПАНИЯМ (базовый - ТОЛЬКО ОН ДЛЯ ТЕСТА) --- 
        print(f"  Запрос статистики по КАМПАНИЯМ для недели {week_str} (Кампания ID: {test_campaign_id_list[0]})...")
        report_name_campaign = f"CampaignStats_{yandex_login}_{week_str}_{datetime.now().strftime('%H%M%S')}"
        total_reports_requested += 1
        # Передаем только тестовый ID кампании
        parsed_data_camp, _, error_msg_camp = fetch_report(
            access_token=access_token, client_login=yandex_login, campaign_ids=test_campaign_id_list, 
            date_from=week_start, date_to=week_end, 
            field_names=FIELDS_CAMPAIGN, report_name=report_name_campaign
        )
        
        if error_msg_camp:
            print(f"    Ошибка API при получении отчета по кампаниям: {error_msg_camp}")
            total_errors += 1
        elif parsed_data_camp is not None:
            print(f"    Получено {len(parsed_data_camp)} строк данных по кампаниям.")
            # Преобразование и добавление в сессию
            try:
                for row in parsed_data_camp:
                    # Проверяем наличие обязательных полей
                    if row.get('CampaignId') is None:
                        print(f"    Пропущена строка без CampaignId: {row}")
                        continue
                    
                    stat = WeeklyCampaignStat(
                        yandex_login=yandex_login,
                        week_start_date=week_start,
                        campaign_id=int(row['CampaignId']), # API возвращает Id
                        impressions=int(row.get('Impressions', 0) or 0), # Заменяем None на 0
                        clicks=int(row.get('Clicks', 0) or 0),
                        cost=float(row.get('Cost', 0.0) or 0.0)
                    )
                    all_stats_objects.append(stat)
                print(f"    Добавлено {len(parsed_data_camp)} записей WeeklyCampaignStat в список для коммита.")
            except Exception as e_proc_camp:
                print(f"    Ошибка обработки данных отчета по кампаниям: {e_proc_camp}")
                traceback.print_exc()
                total_errors += 1
        else:
             print("    Получен неожиданный результат (None) без ошибки от fetch_report для кампаний.")
             total_errors += 1 # Считаем это ошибкой
        
        time.sleep(API_CALL_DELAY) # Пауза после запроса кампаний
        
        # === РАСКОММЕНТИРОВАТЬ БЛОКИ ДРУГИХ СРЕЗОВ ===
        
        # --- СБОР ДАННЫХ ПО ПЛОЩАДКАМ --- 
        print(f"  Запрос статистики по ПЛОЩАДКАМ для недели {week_str} (Кампания ID: {test_campaign_id_list[0]})...")
        report_name_placement = f"PlacementStats_{yandex_login}_{week_str}_{datetime.now().strftime('%H%M%S')}"
        total_reports_requested += 1
        parsed_data_place, _, error_msg_place = fetch_report(
            access_token=access_token, client_login=yandex_login, campaign_ids=test_campaign_id_list,
            date_from=week_start, date_to=week_end, 
            field_names=FIELDS_PLACEMENT, report_name=report_name_placement
        )

        if error_msg_place:
            print(f"    Ошибка API при получении отчета по площадкам: {error_msg_place}")
            total_errors += 1
        elif parsed_data_place is not None:
            print(f"    Получено {len(parsed_data_place)} строк данных по площадкам.")
            try:
                for row in parsed_data_place:
                    if row.get('CampaignId') is None: continue # Пропускаем, если нет CampaignId
                    stat = WeeklyPlacementStat(
                        yandex_login=yandex_login,
                        week_start_date=week_start,
                        campaign_id=int(row['CampaignId']),
                        placement=row.get('Placement'), # Может быть None
                        ad_network_type=row.get('AdNetworkType'),
                        impressions=int(row.get('Impressions', 0) or 0),
                        clicks=int(row.get('Clicks', 0) or 0),
                        cost=float(row.get('Cost', 0.0) or 0.0)
                    )
                    all_stats_objects.append(stat)
                print(f"    Добавлено {len(parsed_data_place)} записей WeeklyPlacementStat.")
            except Exception as e_proc_place:
                print(f"    Ошибка обработки данных отчета по площадкам: {e_proc_place}")
                traceback.print_exc()
                total_errors += 1
        else:
             print("    Получен неожиданный результат (None) без ошибки от fetch_report для площадок.")
             total_errors += 1
        
        time.sleep(API_CALL_DELAY) 
        
        # --- СБОР ДАННЫХ ПО ЗАПРОСАМ --- 
        print(f"  Запрос статистики по ЗАПРОСАМ для недели {week_str} (Кампания ID: {test_campaign_id_list[0]})...")
        report_name_query = f"QueryStats_{yandex_login}_{week_str}_{datetime.now().strftime('%H%M%S')}"
        total_reports_requested += 1
        parsed_data_query, _, error_msg_query = fetch_report(
            access_token=access_token, client_login=yandex_login, campaign_ids=test_campaign_id_list,
            date_from=week_start, date_to=week_end, 
            field_names=FIELDS_QUERY, report_name=report_name_query
        )

        if error_msg_query:
            print(f"    Ошибка API при получении отчета по запросам: {error_msg_query}")
            total_errors += 1
        elif parsed_data_query is not None:
            print(f"    Получено {len(parsed_data_query)} строк данных по запросам.")
            try:
                for row in parsed_data_query:
                    if row.get('CampaignId') is None or row.get('AdGroupId') is None: continue
                    stat = WeeklySearchQueryStat(
                        yandex_login=yandex_login,
                        week_start_date=week_start,
                        campaign_id=int(row['CampaignId']),
                        ad_group_id=int(row['AdGroupId']),
                        query=row.get('Query'),
                        impressions=int(row.get('Impressions', 0) or 0),
                        clicks=int(row.get('Clicks', 0) or 0),
                        cost=float(row.get('Cost', 0.0) or 0.0)
                    )
                    all_stats_objects.append(stat)
                print(f"    Добавлено {len(parsed_data_query)} записей WeeklySearchQueryStat.")
            except Exception as e_proc_query:
                print(f"    Ошибка обработки данных отчета по запросам: {e_proc_query}")
                traceback.print_exc()
                total_errors += 1
        else:
            print("    Получен неожиданный результат (None) без ошибки от fetch_report для запросов.")
            total_errors += 1
            
        time.sleep(API_CALL_DELAY)

        # --- СБОР ДАННЫХ ПО ГЕОГРАФИИ --- 
        print(f"  Запрос статистики по ГЕОГРАФИИ для недели {week_str} (Кампания ID: {test_campaign_id_list[0]})...")
        report_name_geo = f"GeoStats_{yandex_login}_{week_str}_{datetime.now().strftime('%H%M%S')}"
        total_reports_requested += 1
        parsed_data_geo, _, error_msg_geo = fetch_report(
            access_token=access_token, client_login=yandex_login, campaign_ids=test_campaign_id_list,
            date_from=week_start, date_to=week_end, 
            field_names=FIELDS_GEO, report_name=report_name_geo
        )

        if error_msg_geo:
            print(f"    Ошибка API при получении отчета по гео: {error_msg_geo}")
            total_errors += 1
        elif parsed_data_geo is not None:
            print(f"    Получено {len(parsed_data_geo)} строк данных по гео.")
            try:
                for row in parsed_data_geo:
                    if row.get('CampaignId') is None or row.get('CriteriaId') is None: continue
                    stat = WeeklyGeoStat(
                        yandex_login=yandex_login,
                        week_start_date=week_start,
                        campaign_id=int(row['CampaignId']),
                        location_id=int(row['CriteriaId']), # Переименовали поле модели для ясности
                        impressions=int(row.get('Impressions', 0) or 0),
                        clicks=int(row.get('Clicks', 0) or 0),
                        cost=float(row.get('Cost', 0.0) or 0.0)
                    )
                    all_stats_objects.append(stat)
                print(f"    Добавлено {len(parsed_data_geo)} записей WeeklyGeoStat.")
            except Exception as e_proc_geo:
                print(f"    Ошибка обработки данных отчета по гео: {e_proc_geo}")
                traceback.print_exc()
                total_errors += 1
        else:
            print("    Получен неожиданный результат (None) без ошибки от fetch_report для гео.")
            total_errors += 1
            
        time.sleep(API_CALL_DELAY)

        # --- СБОР ДАННЫХ ПО УСТРОЙСТВАМ --- 
        print(f"  Запрос статистики по УСТРОЙСТВАМ для недели {week_str} (Кампания ID: {test_campaign_id_list[0]})...")
        report_name_device = f"DeviceStats_{yandex_login}_{week_str}_{datetime.now().strftime('%H%M%S')}"
        total_reports_requested += 1
        parsed_data_device, _, error_msg_device = fetch_report(
            access_token=access_token, client_login=yandex_login, campaign_ids=test_campaign_id_list,
            date_from=week_start, date_to=week_end, 
            field_names=FIELDS_DEVICE, report_name=report_name_device
        )

        if error_msg_device:
            print(f"    Ошибка API при получении отчета по устройствам: {error_msg_device}")
            total_errors += 1
        elif parsed_data_device is not None:
            print(f"    Получено {len(parsed_data_device)} строк данных по устройствам.")
            try:
                for row in parsed_data_device:
                    if row.get('CampaignId') is None: continue
                    stat = WeeklyDeviceStat(
                        yandex_login=yandex_login,
                        week_start_date=week_start,
                        campaign_id=int(row['CampaignId']),
                        device_type=row.get('Device'), # API возвращает 'Device'
                        impressions=int(row.get('Impressions', 0) or 0),
                        clicks=int(row.get('Clicks', 0) or 0),
                        cost=float(row.get('Cost', 0.0) or 0.0)
                    )
                    all_stats_objects.append(stat)
                print(f"    Добавлено {len(parsed_data_device)} записей WeeklyDeviceStat.")
            except Exception as e_proc_device:
                print(f"    Ошибка обработки данных отчета по устройствам: {e_proc_device}")
                traceback.print_exc()
                total_errors += 1
        else:
            print("    Получен неожиданный результат (None) без ошибки от fetch_report для устройств.")
            total_errors += 1
            
        time.sleep(API_CALL_DELAY)

        # --- СБОР ДАННЫХ ПО ДЕМОГРАФИИ --- 
        print(f"  Запрос статистики по ПОЛУ И ВОЗРАСТУ для недели {week_str} (Кампания ID: {test_campaign_id_list[0]})...")
        report_name_demo = f"DemographicStats_{yandex_login}_{week_str}_{datetime.now().strftime('%H%M%S')}"
        total_reports_requested += 1
        parsed_data_demo, _, error_msg_demo = fetch_report(
            access_token=access_token, client_login=yandex_login, campaign_ids=test_campaign_id_list,
            date_from=week_start, date_to=week_end, 
            field_names=FIELDS_DEMOGRAPHIC, report_name=report_name_demo
        )

        if error_msg_demo:
            print(f"    Ошибка API при получении отчета по демографии: {error_msg_demo}")
            total_errors += 1
        elif parsed_data_demo is not None:
            print(f"    Получено {len(parsed_data_demo)} строк данных по демографии.")
            try:
                for row in parsed_data_demo:
                    if row.get('CampaignId') is None: continue
                    stat = WeeklyDemographicStat(
                        yandex_login=yandex_login,
                        week_start_date=week_start,
                        campaign_id=int(row['CampaignId']),
                        gender=row.get('Gender'), # API возвращает 'Gender'
                        age_group=row.get('Age'),   # API возвращает 'Age'
                        impressions=int(row.get('Impressions', 0) or 0),
                        clicks=int(row.get('Clicks', 0) or 0),
                        cost=float(row.get('Cost', 0.0) or 0.0)
                    )
                    all_stats_objects.append(stat)
                print(f"    Добавлено {len(parsed_data_demo)} записей WeeklyDemographicStat.")
            except Exception as e_proc_demo:
                print(f"    Ошибка обработки данных отчета по демографии: {e_proc_demo}")
                traceback.print_exc()
                total_errors += 1
        else:
            print("    Получен неожиданный результат (None) без ошибки от fetch_report для демографии.")
            total_errors += 1
            
        time.sleep(API_CALL_DELAY) # Пауза после последнего запроса недели
        
        # Конец цикла по неделям? Нет, это внутри цикла. Коммит - после цикла

    # --- Конец цикла по неделям ---

    # 5. Массовое добавление и коммит всех собранных данных
    if all_stats_objects:
        print(f"\nДобавление {len(all_stats_objects)} объектов статистики в сессию БД...")
        try:
            db.session.add_all(all_stats_objects)
            print("Коммит транзакции в БД...")
            db.session.commit()
            print("Коммит успешно завершен.")
            final_message = f"Сбор статистики завершен. Запрошено отчетов: {total_reports_requested}. Ошибок: {total_errors}. Добавлено записей: {len(all_stats_objects)}."
            print(f"=== {final_message} ===")
            return True, final_message
        except Exception as e_commit:
            db.session.rollback()
            error_msg_commit = f"Критическая ошибка при коммите данных в БД: {e_commit}"
            print(error_msg_commit)
            traceback.print_exc()
            return False, error_msg_commit
    elif total_errors > 0:
        error_msg_final = f"Сбор статистики завершен с ошибками ({total_errors} ошибок). Данные не были сохранены."
        print(f"=== {error_msg_final} ===")
        return False, error_msg_final
    else:
        final_message = "Сбор статистики завершен. Новых данных для сохранения не найдено."
        print(f"=== {final_message} ===")
        return True, final_message