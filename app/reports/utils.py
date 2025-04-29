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
    User, Client, YandexAccount, # Добавляем User, Client, YandexAccount
    WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat, 
    WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat
)
from flask import current_app, flash # Импортируем current_app и flash
from flask_login import current_user # Для получения user_id, если нужно

# Импортируем клиент API и его исключения
from ..api_clients.yandex_direct import YandexDirectClient, YandexDirectClientError, YandexDirectAuthError, YandexDirectTemporaryError

# URL API Отчетов и Кампаний будут браться из конфигурации приложения
# REPORTS_API_SANDBOX_URL = os.getenv('DIRECT_API_SANDBOX_URL_REPORTS', 'https://api-sandbox.direct.yandex.com/json/v5/reports')
# DIRECT_API_CAMPAIGNS_URL = os.getenv('DIRECT_API_SANDBOX_URL_CAMPAIGNS', 'https://api-sandbox.direct.yandex.com/json/v5/campaigns')

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

def fetch_report(api_client: YandexDirectClient, campaign_ids: list[int], 
                 date_from: date, date_to: date, field_names: list[str], report_name: str, 
                 report_type: str = 'CUSTOM_REPORT') -> tuple[list[dict] | None, str | None, str | None]:
    """Заказывает, ожидает и парсит отчет из API Яндекс.Директ v5.

    Args:
        api_client: Инициализированный экземпляр YandexDirectClient.
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
    current_app.logger.info(f"Запуск fetch_report для {len(campaign_ids)} кампаний ({campaign_ids[:3]}...) аккаунта {api_client.client_login}, период: {date_from} - {date_to}, отчет: {report_name}")
    if not campaign_ids:
        return [], None, "Список ID кампаний пуст."

    report_payload = {
        'params': {
            'SelectionCriteria': {
                'Filter': [{
                    'Field': 'CampaignId',
                    'Operator': 'IN',
                    'Values': [str(cid) for cid in campaign_ids]
                }],
                'DateFrom': date_from.strftime('%Y-%m-%d'),
                'DateTo': date_to.strftime('%Y-%m-%d')
            },
            'FieldNames': field_names,
            'ReportName': report_name,
            'ReportType': report_type,
            'DateRangeType': 'CUSTOM_DATE',
            'Format': 'TSV',
            'IncludeVAT': 'NO',
            'IncludeDiscount': 'NO'
        }
    }

    report_data_raw = None
    retries = 0
    MAX_REPORT_RETRIES = 20
    RETRY_DELAY_INITIAL = 5
    RETRY_DELAY_MAX = 60
    current_retry_delay = RETRY_DELAY_INITIAL

    while retries < MAX_REPORT_RETRIES:
        retries += 1
        current_app.logger.info(f"  Попытка {retries}/{MAX_REPORT_RETRIES}: Запрос статуса/данных отчета {report_name} для {api_client.client_login}...")
        try:
            # Используем ВРЕМЕННОЕ РЕШЕНИЕ с прямым вызовом requests, пока не адаптируем _make_request
            # TODO: Интегрировать с _make_request
            reports_api_url = f"{api_client.api_v5_url}reports"
            headers_post = api_client.headers.copy()
            headers_post['returnMoneyInMicros'] = 'false'
            headers_post['skipReportHeader'] = 'true' # Заголовки будем использовать из field_names
            headers_post['skipReportSummary'] = 'true'
            
            response = requests.post(
                reports_api_url, 
                headers=headers_post, 
                json=report_payload['params'], # Передаем только params
                timeout=60
            )
            
            status_code = response.status_code
            request_id = response.headers.get("RequestId", "N/A")
            units_used = response.headers.get("units", "N/A")
            current_app.logger.debug(f"    Статус ответа: {status_code}. RequestId: {request_id}. Units: {units_used}")

            if status_code == 200:
                current_app.logger.info(f"    Отчет {report_name} готов!")
                report_data_raw = response.text
                break
            elif status_code in [201, 202]:
                retry_interval_header = response.headers.get("retryIn", str(RETRY_DELAY_INITIAL))
                try:
                    retry_interval = min(max(int(retry_interval_header), 5), RETRY_DELAY_MAX)
                except ValueError:
                    retry_interval = current_retry_delay
                    current_retry_delay = min(current_retry_delay * 2, RETRY_DELAY_MAX)
                current_app.logger.info(f"    Отчет {report_name} формируется. Повтор через {retry_interval} секунд...")
                time.sleep(retry_interval)
                continue
            else:
                error_detail = response.text[:500]
                try:
                    error_data = response.json()
                    error_detail = json.dumps(error_data.get('error', {}), ensure_ascii=False)
                except json.JSONDecodeError:
                    pass # Оставляем текст ошибки
                error_msg = f"Ошибка HTTP {status_code} при запросе отчета {report_name}. RequestId: {request_id}. Detail: {error_detail}"
                current_app.logger.error(error_msg)
                if status_code >= 500 and retries < MAX_REPORT_RETRIES // 2:
                    current_app.logger.warning(f"    Серверная ошибка {status_code}. Повторяем попытку...")
                    time.sleep(current_retry_delay)
                    current_retry_delay = min(current_retry_delay * 2, RETRY_DELAY_MAX)
                    continue
                else:
                    return None, None, error_msg 

        except requests.exceptions.Timeout:
            error_msg = f"Таймаут при запросе отчета {report_name}. Повтор через {current_retry_delay} сек..."
            current_app.logger.warning(error_msg)
            time.sleep(current_retry_delay)
            current_retry_delay = min(current_retry_delay * 2, RETRY_DELAY_MAX)
            continue
        except requests.exceptions.RequestException as e_req:
            error_msg = f"Сетевая ошибка при запросе отчета {report_name}: {e_req}. Повтор через {current_retry_delay} сек..."
            current_app.logger.warning(error_msg)
            time.sleep(current_retry_delay)
            current_retry_delay = min(current_retry_delay * 2, RETRY_DELAY_MAX)
            continue
        except Exception as e_generic:
            error_msg = f"Непредвиденная ошибка при запросе отчета {report_name}: {e_generic}"
            current_app.logger.exception(error_msg)
            return None, None, error_msg

    if report_data_raw is None:
        error_msg = f"Отчет {report_name} не был готов после {MAX_REPORT_RETRIES} попыток."
        current_app.logger.error(error_msg)
        return None, None, error_msg

    # --- 3. Парсинг отчета (TSV) --- 
    parsed_data = []
    parsing_error_msg = None
    rows_processed = 0 
    try:
        current_app.logger.debug(f"Парсинг TSV данных отчета {report_name} ({len(report_data_raw)} байт)..." )
        report_file = io.StringIO(report_data_raw)
        # Используем переданные field_names как заголовки для DictReader
        tsv_reader = csv.DictReader(report_file, fieldnames=field_names, delimiter='\t') 
        
        for row in tsv_reader:
            rows_processed += 1
            parsed_row = {}
            try:
                for header, value in row.items():
                    if header is None: 
                        continue
                    # Преобразование типов
                    clean_value = None
                    if value == '--':
                        clean_value = None
                    elif header in ('Impressions', 'Clicks', 'CampaignId', 'AdGroupId', 'CriteriaId'): # Целочисленные
                        try: 
                            clean_value = int(value) if value is not None else None
                        except (ValueError, TypeError): 
                            clean_value = None
                    elif header in ('Cost'): # С плавающей точкой
                        try: 
                            clean_value = float(value) if value is not None else None
                        except (ValueError, TypeError): 
                            clean_value = None
                    else: # Строковые (оставляем как есть)
                        clean_value = value
                    parsed_row[header] = clean_value
                parsed_data.append(parsed_row)
            except Exception as e_row:
                current_app.logger.error(f"Ошибка парсинга строки {rows_processed} в отчете {report_name}: {row}. Ошибка: {e_row}")
                # Можно пропустить строку или добавить обработку

        current_app.logger.debug(f"  Парсинг отчета {report_name} завершен. Строк: {rows_processed}. Спарсено: {len(parsed_data)}.")

    except Exception as e_parse:
        parsing_error_msg = f"Ошибка парсинга отчета {report_name}: {e_parse}"
        current_app.logger.exception(parsing_error_msg)
        return None, None, parsing_error_msg

    return parsed_data, report_data_raw, None

# --- Основная функция сбора статистики --- 

def collect_weekly_stats_for_last_n_weeks(user_id: int, n_weeks: int = 4) -> tuple[bool, str]:
    """Собирает еженедельную статистику за последние n недель для ВСЕХ аккаунтов пользователя."""
    start_time = time.time()
    current_app.logger.info(f"=== Запуск сбора статистики для User ID: {user_id}, за {n_weeks} нед. ===" )

    total_accounts_processed = 0
    total_campaigns_processed = 0
    total_reports_fetched = 0
    total_rows_saved = 0
    error_messages = []

    try:
        # 1. Найти все активные YandexAccount пользователя
        user = User.query.get(user_id)
        if not user:
            msg = f"Пользователь с ID {user_id} не найден."
            current_app.logger.error(msg)
            return False, msg
        
        accounts = db.session.query(YandexAccount).join(Client).filter(Client.user_id == user.id, YandexAccount.is_active == True).all()
        if not accounts:
            msg = f"Не найдено активных аккаунтов для пользователя {user.yandex_login} (ID: {user.id})."
            current_app.logger.warning(msg)
            return True, msg # Считаем это успехом, просто нечего собирать
            
        current_app.logger.info(f"Найдено {len(accounts)} активных аккаунтов для обработки.")

        # 2. Определить даты недель
        week_start_dates = get_week_start_dates(n_weeks)
        if not week_start_dates:
            msg = "Не удалось определить даты недель."
            current_app.logger.error(msg)
            return False, msg
        current_app.logger.info(f"Даты начала недель для сбора: {week_start_dates}")

        # 3. Цикл по аккаунтам
        for account in accounts:
            total_accounts_processed += 1
            current_app.logger.info(f"--- Обработка аккаунта ID: {account.id}, Логин: {account.login} ---")
            account_campaigns_processed = 0
            account_reports_fetched = 0
            account_rows_saved = 0
            account_errors = []

            try:
                # 3.1 Создать API клиент
                api_client = YandexDirectClient(yandex_account_id=account.id, current_user_id=user.id)

                # 3.2 Получить список АКТИВНЫХ кампаний
                campaign_payload = {
                    "method": "get",
                    "params": {
                        "SelectionCriteria": { "States": ["ON"] }, # Только включенные
                        "FieldNames": ["Id", "Name"] # Нам нужны только ID
                    }
                }
                campaign_result = api_client._make_request('campaigns', campaign_payload, api_version='v5')
                
                active_campaigns = []
                if campaign_result and 'Campaigns' in campaign_result:
                    active_campaigns = campaign_result['Campaigns']
                
                if not active_campaigns:
                    current_app.logger.warning(f"Активные кампании не найдены для аккаунта {account.login}.")
                    continue 
                campaign_ids = [c['Id'] for c in active_campaigns]
                current_app.logger.info(f"Найдено {len(campaign_ids)} активных кампаний для аккаунта {account.login}: {campaign_ids[:10]}...")

                # 3.3 Цикл по неделям
                for week_start in week_start_dates:
                    monday, sunday = get_monday_and_sunday(week_start)
                    current_app.logger.info(f"  Обработка недели: {monday.strftime('%Y-%m-%d')} - {sunday.strftime('%Y-%m-%d')}")

                    # 3.4 Загрузка данных по срезам для ВСЕХ кампаний аккаунта за эту неделю
                    report_date_suffix = monday.strftime('%Y%m%d')
                    report_base_name = f"acc{account.id}_week{report_date_suffix}"
                    
                    # Определяем поля для каждого среза
                    slices_to_fetch = {
                        'campaign': {'fields': ['CampaignId', 'Impressions', 'Clicks', 'Cost'], 'model': WeeklyCampaignStat},
                        'placement': {'fields': ['CampaignId', 'Placement', 'AdNetworkType', 'Impressions', 'Clicks', 'Cost'], 'model': WeeklyPlacementStat},
                        'geo': {'fields': ['CampaignId', 'CriteriaId', 'Impressions', 'Clicks', 'Cost'], 'model': WeeklyGeoStat},
                        'device': {'fields': ['CampaignId', 'Device', 'Impressions', 'Clicks', 'Cost'], 'model': WeeklyDeviceStat},
                        'demographic': {'fields': ['CampaignId', 'Gender', 'Age', 'Impressions', 'Clicks', 'Cost'], 'model': WeeklyDemographicStat},
                    }
                    
                    # Цикл по срезам
                    for slice_key, slice_details in slices_to_fetch.items():
                        report_name = f"{report_base_name}_{slice_key}"
                        current_app.logger.debug(f"    Запрос отчета: {report_name}")
                        
                        # Вызываем АДАПТИРОВАННЫЙ fetch_report
                        parsed_data, raw_data, error_msg = fetch_report(
                            api_client=api_client, 
                            campaign_ids=campaign_ids,
                            date_from=monday,
                            date_to=sunday,
                            field_names=slice_details['fields'],
                            report_name=report_name
                        )
                        
                        if error_msg:
                            err_msg = f"Ошибка при получении среза '{slice_key}' для недели {monday}: {error_msg}"
                            current_app.logger.error(err_msg)
                            account_errors.append(err_msg)
                            continue 
                        
                        account_reports_fetched += 1
                        current_app.logger.debug(f"    Отчет {report_name} получен, {len(parsed_data)} строк.")

                        if not parsed_data:
                            continue

                        # 3.5 Сохранение данных в БД
                        Model = slice_details['model']
                        rows_to_save = []
                        
                        # --- Удаление старых данных --- 
                        try:
                            # Формируем условия для удаления
                            delete_conditions = [
                                Model.yandex_account_id == account.id,
                                Model.week_start_date == monday
                            ]
                            # Для срезов, где campaign_id не является частью PK, добавляем его
                            if slice_key != 'campaign': # У WeeklyCampaignStat составной PK
                                delete_conditions.append(Model.campaign_id.in_(campaign_ids))
                            
                            delete_q = Model.__table__.delete().where(*delete_conditions)
                            result = db.session.execute(delete_q)
                            db.session.commit() 
                            current_app.logger.debug(f"    Удалено {result.rowcount} старых записей для {slice_key}, недели {monday}.")
                        except Exception as e_del:
                            db.session.rollback()
                            current_app.logger.exception(f"    Ошибка при удалении старых данных для {slice_key}, недели {monday}.")
                            account_errors.append(f"Ошибка очистки БД для {slice_key} недели {monday}.")
                            continue 
                        
                        # --- Подготовка данных для сохранения --- 
                        for row_dict in parsed_data:
                            stat_entry = {}
                            stat_entry['week_start_date'] = monday
                            stat_entry['user_id'] = user.id
                            stat_entry['client_id'] = account.client_id
                            stat_entry['yandex_account_id'] = account.id
                            
                            # Сопоставление полей
                            stat_entry['campaign_id'] = row_dict.get('CampaignId')
                            stat_entry['impressions'] = row_dict.get('Impressions')
                            stat_entry['clicks'] = row_dict.get('Clicks')
                            stat_entry['cost'] = row_dict.get('Cost')
                            
                            # Добавляем поля конкретного среза
                            if slice_key == 'placement':
                                stat_entry['placement'] = row_dict.get('Placement')
                                stat_entry['ad_network_type'] = row_dict.get('AdNetworkType')
                            elif slice_key == 'geo':
                                stat_entry['location_id'] = row_dict.get('CriteriaId')
                            elif slice_key == 'device':
                                stat_entry['device_type'] = row_dict.get('Device')
                            elif slice_key == 'demographic':
                                stat_entry['gender'] = row_dict.get('Gender')
                                stat_entry['age_group'] = row_dict.get('Age')
                            
                            # Пропускаем строки с пустым campaign_id (для срезов, где он не PK)
                            if slice_key != 'campaign' and stat_entry['campaign_id'] is None:
                                continue
                                
                            rows_to_save.append(stat_entry)

                        # --- Сохранение --- 
                        if rows_to_save:
                            try:
                                db.session.bulk_insert_mappings(Model, rows_to_save)
                                db.session.commit()
                                account_rows_saved += len(rows_to_save)
                                current_app.logger.debug(f"    Сохранено {len(rows_to_save)} строк для среза {slice_key}, недели {monday}.")
                            except Exception as e_save:
                                db.session.rollback()
                                current_app.logger.exception(f"    Ошибка bulk insert для среза {slice_key}, недели {monday}. Данные: {rows_to_save[:2]}...")
                                account_errors.append(f"Ошибка сохранения в БД для {slice_key} недели {monday}.")
                        
                        # Задержка между запросами отчетов внутри недели
                        time.sleep(API_CALL_DELAY)

            except YandexDirectAuthError as e_auth:
                error_msg = f"Ошибка доступа к аккаунту {account.login}: {e_auth}."
                current_app.logger.error(error_msg)
                error_messages.append(error_msg)
                continue # К следующему аккаунту
            except YandexDirectClientError as e_api:
                error_msg = f"Ошибка API для аккаунта {account.login}: {e_api}"
                current_app.logger.error(error_msg)
                error_messages.append(error_msg)
                continue # К следующему аккаунту
            except Exception as e_acc:
                error_msg = f"Непредвиденная ошибка для аккаунта {account.login}: {e_acc}"
                current_app.logger.exception(error_msg)
                error_messages.append(error_msg)
                continue # К следующему аккаунту
            finally:
                total_reports_fetched += account_reports_fetched
                total_rows_saved += account_rows_saved
                current_app.logger.info(f"--- Аккаунт {account.login} обработан. Отчетов: {account_reports_fetched}, Сохранено строк: {account_rows_saved}. Ошибок: {len(account_errors)} ---")
        
        # --- Финальное сообщение --- 
        end_time = time.time()
        duration = end_time - start_time
        summary_msg = (
            f"Сбор статистики завершен за {duration:.2f} сек. "
            f"Обработано аккаунтов: {total_accounts_processed}, "
            f"Получено отчетов: {total_reports_fetched}, "
            f"Сохранено строк: {total_rows_saved}."
        )
        if error_messages:
            summary_msg += f" Обнаружены ошибки ({len(error_messages)}): {'; '.join(error_messages[:3])}..."
            current_app.logger.error(summary_msg)
            current_app.logger.error(f"Полный список ошибок: {error_messages}")
            # Возвращаем False, так как были ошибки
            return False, summary_msg
        else:
            current_app.logger.info(summary_msg)
            return True, summary_msg

    except Exception as e_global:
        error_msg = f"Глобальная ошибка при сборе статистики для User ID {user_id}: {e_global}"
        current_app.logger.exception(error_msg)
        return False, error_msg