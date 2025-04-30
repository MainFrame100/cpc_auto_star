import requests
import json
import time
import io
import csv
from datetime import date, timedelta, datetime
import os
import traceback # Для детального логирования ошибок
from sqlalchemy.dialects.postgresql import insert as pg_insert # <-- Добавляем импорт для UPSERT

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
    """Возвращает дату понедельника и воскресенья для недели, содержащей target_date."""
    if target_date is None:
        target_date = date.today()
    # weekday() возвращает 0 для понедельника, ..., 6 для воскресенья
    start_of_week = target_date - timedelta(days=target_date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week


def get_week_start_dates(n_weeks: int) -> list[date]:
    """Возвращает список дат начала (понедельников) для последних n_weeks полных недель."""
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
                 report_type: str = 'CUSTOM_REPORT', goals: list[str] | None = None) -> tuple[list[dict] | None, str | None, str | None]:
    """Заказывает, ожидает и парсит отчет из API Яндекс.Директ v5."""
    current_app.logger.info(f"Запуск fetch_report для {len(campaign_ids) if campaign_ids else 'всех'} кампаний ({campaign_ids[:3] if campaign_ids else 'N/A'}...) аккаунта {api_client.client_login}, период: {date_from} - {date_to}, отчет: {report_name}, Goals: {goals}")

    # Формируем SelectionCriteria ТОЛЬКО с датами
    selection_criteria = {
        'DateFrom': date_from.strftime('%Y-%m-%d'),
        'DateTo': date_to.strftime('%Y-%m-%d')
    }
    # Добавляем фильтр по CampaignId ТОЛЬКО если campaign_ids не пуст
    if campaign_ids:
        # Важно: добавляем ключ 'Filter' только здесь
        selection_criteria['Filter'] = [{
                    'Field': 'CampaignId',
                    'Operator': 'IN',
                    'Values': [str(cid) for cid in campaign_ids]
        }]

    report_payload = {
        'params': {
            'SelectionCriteria': selection_criteria, # Используем сформированный selection_criteria
            'FieldNames': field_names,
            'ReportName': report_name,
            'ReportType': report_type,
            'DateRangeType': 'CUSTOM_DATE',
            'Format': 'TSV',
            'IncludeVAT': 'NO',
            'IncludeDiscount': 'NO'
        }
    }

    # --- Добавляем Goals, если они переданы ---
    if goals:
        report_payload['params']['Goals'] = goals
        current_app.logger.debug(f"  Добавлены цели в запрос: {goals}")
    # --- Конец добавления Goals ---

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
            headers_post['skipReportSummary'] = 'true'
            
            response = requests.post(
                reports_api_url, 
                headers=headers_post, 
                json=report_payload, # <--- ИСПРАВЛЕНО: отправляем весь payload
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
        current_app.logger.debug(f"Парсинг TSV данных отчета {report_name} ({len(report_data_raw)} байт)...")
        current_app.logger.debug(f"Raw report data (first 500 chars) for {report_name}:\n{report_data_raw[:500]}")
        report_file = io.StringIO(report_data_raw)
        tsv_reader = csv.DictReader(report_file, fieldnames=field_names, delimiter='\t')
        
        for i, row in enumerate(tsv_reader):
            rows_processed += 1
            current_app.logger.debug(f"  Парсинг строки {i+1}: {row}")
            parsed_row = {}
            for header, value in row.items():
                if header is None:
                    continue
                clean_value = None
                if value == '--':
                    clean_value = None
                elif header in ('Impressions', 'Clicks', 'CampaignId', 'AdGroupId', 'CriteriaId'):
                    try:
                        clean_value = int(value) if value is not None else None
                    except (ValueError, TypeError):
                        clean_value = None
                elif header in ('Cost'):
                    try:
                        clean_value = float(value) if value is not None else None
                    except (ValueError, TypeError):
                        clean_value = None
                else:
                    clean_value = value
                parsed_row[header] = clean_value
            parsed_data.append(parsed_row)

        current_app.logger.info(f"  Парсинг отчета {report_name} завершен. Всего строк прочитано: {rows_processed}. Успешно спарсено: {len(parsed_data)}.")

    except Exception as e_parse:
        parsing_error_msg = f"Критическая ошибка парсинга отчета {report_name}: {e_parse}"
        current_app.logger.exception(parsing_error_msg)
        return None, None, parsing_error_msg

    return parsed_data, report_data_raw, None

# --- Вспомогательная функция для парсинга целей ---
def _parse_metrika_goals(goals_str: str | None) -> list[str]:
    """Парсит строку с ID целей, разделенных запятыми."""
    if not goals_str:
        return []
    try:
        # Убираем пробелы и пустые элементы
        goal_ids = [goal.strip() for goal in goals_str.split(',') if goal.strip()]
        # Проверяем, что это числа (хотя API принимает строки)
        for goal_id in goal_ids:
            if not goal_id.isdigit():
                current_app.logger.warning(f"Найден нечисловой ID цели при парсинге: '{goal_id}' в строке '{goals_str}'. Он будет передан в API как есть.")
        return goal_ids
    except Exception as e:
        current_app.logger.error(f"Ошибка парсинга строки целей '{goals_str}': {e}")
        return []


# --- Основная функция сбора статистики --- 

# Удаляем старую функцию collect_weekly_stats_for_last_n_weeks, 
# так как новая update_client_statistics ее заменяет
# def collect_weekly_stats_for_last_n_weeks(...): ...


# --- Функция-оркестратор для обновления статистики клиента --- 

def update_client_statistics(client_id: int, user_id: int) -> tuple[bool, str]:
    """Оркестрирует двухэтапный процесс обновления статистики для клиента."""
    start_time = time.time()
    current_app.logger.info(f"=== Запуск update_client_statistics для Client ID: {client_id}, User ID: {user_id} ===")

    client = db.session.get(Client, client_id)
    if not client or client.user_id != user_id:
        msg = f"Клиент с ID {client_id} не найден или не принадлежит пользователю {user_id}."
        current_app.logger.error(msg)
        return False, msg

    accounts = YandexAccount.query.filter_by(client_id=client_id, is_active=True).all()
    if not accounts:
        msg = f"У клиента '{client.name}' (ID: {client_id}) нет активных подключенных аккаунтов Яндекс.Директ."
        current_app.logger.warning(msg)
        return True, msg # Считаем успешным запуском, но делать нечего

    current_app.logger.info(f"Найдено {len(accounts)} активных аккаунтов для обновления клиента '{client.name}'.")

    # --- Определяем даты для Шага 1 (последняя полная неделя) и Шага 2 (4 недели) ---
    step1_weeks = get_week_start_dates(1)
    step2_weeks = get_week_start_dates(4) # 4 недели для детальной статистики

    if not step1_weeks or not step2_weeks:
        msg = "Не удалось определить даты недель для обновления."
        current_app.logger.error(msg)
        return False, msg
        
    last_week_monday = step1_weeks[0]
    _, last_week_sunday = get_monday_and_sunday(last_week_monday)
    
    step2_first_monday = step2_weeks[0]
    step2_last_monday = step2_weeks[-1]
    _, step2_last_sunday = get_monday_and_sunday(step2_last_monday)
    
    current_app.logger.info(f"Шаг 1: Целевая неделя для списка кампаний: {last_week_monday} - {last_week_sunday}")
    current_app.logger.info(f"Шаг 2: Целевой период для детальной статистики: {step2_first_monday} - {step2_last_sunday}")

    # --- Шаг 1: Быстрое обновление списка кампаний --- 
    current_app.logger.info("--- Начало Шага 1: Обновление списка кампаний ---")
    step1_success = True # Станет False, если будут критичные ошибки (DB)
    step1_errors = []   
    campaigns_upserted_total = 0

    # Определяем поля для отчета Шага 1 (добавляем метрики)
    step1_field_names = ['CampaignId', 'CampaignName', 'CampaignType', 'Impressions', 'Clicks', 'Cost']

    for account in accounts:
        current_app.logger.info(f"  Шаг 1: Обработка аккаунта {account.login} (ID: {account.id})")
        try:
            api_client = YandexDirectClient(yandex_account_id=account.id, current_user_id=user_id)
            
            report_date_suffix = last_week_monday.strftime('%Y%m%d')
            report_name = f"client{client_id}_acc{account.id}_step1_camp_list_{report_date_suffix}"
            
            parsed_data, _, error_msg = fetch_report(
                api_client=api_client,
                campaign_ids=[], # Передаем пустой список, т.к. фильтр не нужен
                date_from=last_week_monday,
                date_to=last_week_sunday,
                field_names=step1_field_names,
                report_name=report_name,
                report_type='CAMPAIGN_PERFORMANCE_REPORT' # Используем стандартный тип
            )
            
            if error_msg:
                err_msg = f"Шаг 1: Ошибка API для аккаунта {account.login}: {error_msg}"
                current_app.logger.error(err_msg)
                step1_errors.append(err_msg)
                continue # Переходим к следующему аккаунту
            
            if parsed_data is None: # Может быть None, если отчет пуст или ошибка парсинга
                current_app.logger.warning(f"  Шаг 1: Отчет для аккаунта {account.login} не вернул данных или ошибка парсинга.")
                continue
                
            # ---> Фильтруем данные ДО подготовки UPSERT <---    
            valid_parsed_data = [row for row in parsed_data if row.get('CampaignId') is not None]
            if not valid_parsed_data:
                 current_app.logger.info(f"  Шаг 1: Нет валидных строк (с CampaignId) в отчете для аккаунта {account.login}.")
                 continue
                 
            # --- Готовим данные для UPSERT (используем valid_parsed_data) --- 
            upsert_data = []
            for campaign_data in valid_parsed_data: # <-- Используем отфильтрованные данные
                # campaign_id = campaign_data.get('CampaignId') # Проверка campaign_id уже не нужна
                # if campaign_id is None: 
                #     current_app.logger.warning(f"    Шаг 1: Пропуск строки без CampaignId в отчете для {account.login}: {campaign_data}")
                #     continue 

                upsert_data.append({
                    'week_start_date': last_week_monday, 
                    'user_id': user_id,
                    'client_id': client_id,
                    'yandex_account_id': account.id,
                    'campaign_id': campaign_data.get('CampaignId'), # Берем ID из валидных данных
                    'campaign_name': campaign_data.get('CampaignName'),
                    'campaign_type': campaign_data.get('CampaignType'),
                    'impressions': campaign_data.get('Impressions'), # <-- Добавляем метрики
                    'clicks': campaign_data.get('Clicks'),         # <-- Добавляем метрики
                    'cost': campaign_data.get('Cost'),             # <-- Добавляем метрики
                    'updated_at': datetime.utcnow()
                })
            
            if not upsert_data:
                current_app.logger.info(f"    Шаг 1: Нет данных для UPSERT для аккаунта {account.login}, неделя {last_week_monday}.")
                continue
                
            # --- Выполняем UPSERT --- 
            current_app.logger.debug(f"    Шаг 1: Подготовлено {len(upsert_data)} записей для UPSERT. Пример: {upsert_data[0] if upsert_data else 'N/A'}") # <-- Лог перед UPSERT
            stmt = pg_insert(WeeklyCampaignStat).values(upsert_data)
            # Исправляем синтаксис ON CONFLICT, ссылаясь на имя констрейнта
            update_stmt = stmt.on_conflict_do_update(
                constraint='uq_weekly_campaign_stat', # <-- Используем имя ограничения из миграции
                set_={
                    # Используем строковые ключи для целевых колонок
                    'campaign_name': stmt.excluded.campaign_name,
                    'campaign_type': stmt.excluded.campaign_type,
                    'impressions': stmt.excluded.impressions,
                    'clicks': stmt.excluded.clicks,
                    'cost': stmt.excluded.cost,
                    'updated_at': stmt.excluded.updated_at # <-- Оставляем это поле
                }
            )
            
            try:
                result = db.session.execute(update_stmt) # <-- Получаем результат выполнения
                db.session.commit()
                campaigns_upserted_total += len(upsert_data)
                current_app.logger.info(f"    Шаг 1: Успешно UPSERT {len(upsert_data)} записей (затронуто строк: {result.rowcount}) для аккаунта {account.login}, неделя {last_week_monday}.") # <-- Лог после UPSERT
            except Exception as e_upsert:
                db.session.rollback()
                err_msg = f"Шаг 1: Ошибка DB UPSERT для аккаунта {account.login}, неделя {last_week_monday}: {e_upsert}"
                current_app.logger.exception(err_msg)
                step1_errors.append(err_msg)
                step1_success = False # Ошибка БД - критична
                # Можно прервать цикл по аккаунтам, если ошибка БД?
                # break 
                
        except (YandexDirectAuthError, YandexDirectClientError) as e_api_outer:
            err_msg = f"Шаг 1: Ошибка API при обработке аккаунта {account.login}: {e_api_outer}"
            current_app.logger.error(err_msg)
            step1_errors.append(err_msg)
            # Не критично для всего процесса, продолжаем
        except Exception as e_generic:
            err_msg = f"Шаг 1: Непредвиденная ошибка при обработке аккаунта {account.login}: {e_generic}"
            current_app.logger.exception(err_msg)
            step1_errors.append(err_msg)
            step1_success = False # Непредвиденная ошибка может быть критичной
            # break # Можно прервать

    current_app.logger.info(f"--- Завершение Шага 1. Успешно UPSERT: {campaigns_upserted_total} записей. Ошибок аккаунтов: {len(step1_errors)}. Общий успех: {step1_success} ---")

    # --- Проверка успеха Шага 1 --- 
    if not step1_success:
        error_details = "; ".join(step1_errors[:3])
        msg = f"Критическая ошибка на Шаге 1 (обновление списка кампаний): {error_details}... Обновление прервано."
        current_app.logger.error(msg)
        # Не продолжаем Шаг 2, если Шаг 1 не удался критически
        return False, msg
    elif step1_errors: # Если были некритические ошибки API по аккаунтам
        current_app.logger.warning(f"Во время Шага 1 были некритические ошибки ({len(step1_errors)}). Продолжаем Шаг 2...")

    # --- Шаг 2: Полная загрузка детальной статистики за 4 НЕДЕЛИ --- 
    current_app.logger.info(f"--- Начало Шага 2: Полная загрузка статистики за {len(step2_weeks)} недели ---")
    step2_success = True # Станет False при *критических* ошибках Шага 2 (например, DB)
    step2_errors_by_slice = {} # {slice_key: [error_msg1, error_msg2], ...}
    total_rows_upserted_step2 = 0
    processed_campaign_ids_step2 = set() # Для отслеживания обработанных кампаний

    # Получаем цели клиента
    metrika_goals_list = _parse_metrika_goals(client.metrika_goals)
    current_app.logger.info(f"Используемые цели Метрики для Шага 2: {metrika_goals_list}")
    
    # --- Определяем, какие именно кампании нужно обновить ---
    # Запрашиваем ID кампаний, которые есть в WeeklyCampaignStat за последние 4 недели для этого клиента
    campaigns_to_update_query = db.session.query(
            WeeklyCampaignStat.yandex_account_id, 
            WeeklyCampaignStat.campaign_id
        ).filter(
            WeeklyCampaignStat.client_id == client_id,
            WeeklyCampaignStat.week_start_date.in_(step2_weeks) 
        ).distinct()
        
    campaigns_to_update_list = campaigns_to_update_query.all()
    if not campaigns_to_update_list:
        msg = f"Шаг 2: Не найдено кампаний для обновления детальной статистики в БД за период {step2_first_monday} - {step2_last_sunday}."
        current_app.logger.warning(msg)
        # Шаг 1 мог пройти успешно, но данных для Шага 2 нет. Считаем это успехом.
        end_time = time.time()
        duration = end_time - start_time
        return True, f"Шаг 1 завершен ({campaigns_upserted_total} записей). {msg} Общее время: {duration:.2f} сек."
        
    # Группируем campaign_id по yandex_account_id для удобства
    account_campaign_map = {}
    for acc_id, camp_id in campaigns_to_update_list:
        if acc_id not in account_campaign_map:
            account_campaign_map[acc_id] = []
        account_campaign_map[acc_id].append(camp_id)
        processed_campaign_ids_step2.add(camp_id) # Добавляем в общий сет
        
    current_app.logger.info(f"Шаг 2: Найдено {len(campaigns_to_update_list)} пар (аккаунт, кампания) для обновления детальной статистики.")

    # --- Определяем срезы для Шага 2 ---
    # Добавляем поле Conversions
    base_metrics_step2 = BASE_METRICS + ['Conversions']
    
    slices_to_fetch_step2 = {
        'campaign': {'fields': ['CampaignId', 'CampaignName', 'CampaignType'] + base_metrics_step2, 'model': WeeklyCampaignStat, 'report_type': 'CAMPAIGN_PERFORMANCE_REPORT'},
        'placement': {'fields': ['CampaignId', 'Placement', 'AdNetworkType'] + base_metrics_step2, 'model': WeeklyPlacementStat, 'report_type': 'CUSTOM_REPORT'},
        'query': {'fields': ['CampaignId', 'AdGroupId', 'Query'] + base_metrics_step2, 'model': WeeklySearchQueryStat, 'report_type': 'CUSTOM_REPORT'},
        'geo': {'fields': ['CampaignId', 'CriteriaId'] + base_metrics_step2, 'model': WeeklyGeoStat, 'report_type': 'CUSTOM_REPORT'},
        'device': {'fields': ['CampaignId', 'Device'] + base_metrics_step2, 'model': WeeklyDeviceStat, 'report_type': 'CUSTOM_REPORT'},
        'demographic': {'fields': ['CampaignId', 'Gender', 'Age'] + base_metrics_step2, 'model': WeeklyDemographicStat, 'report_type': 'CUSTOM_REPORT'},
    }

    # --- Цикл по аккаунтам, для которых есть кампании к обновлению ---
    for account in accounts:
        if account.id not in account_campaign_map:
            current_app.logger.debug(f"  Шаг 2: Пропуск аккаунта {account.login} (ID: {account.id}), нет кампаний для обновления в этом аккаунте.")
            continue

        account_campaign_ids = account_campaign_map[account.id]
        current_app.logger.info(f"--- Шаг 2: Обработка аккаунта {account.login} (ID: {account.id}). Кампании: {len(account_campaign_ids)} ---")
        
        try:
            api_client = YandexDirectClient(yandex_account_id=account.id, current_user_id=user_id)
            
            # --- Словарь для хранения данных перед UPSERT ---
            # { ModelClass: [list_of_rows_for_upsert] }
            all_data_to_upsert = {model_details['model']: [] for model_details in slices_to_fetch_step2.values()}
            
            # --- Цикл по срезам для данного аккаунта ---
            for slice_key, slice_details in slices_to_fetch_step2.items():
                report_date_suffix = step2_first_monday.strftime('%Y%m%d')
                report_name = f"client{client_id}_acc{account.id}_step2_{slice_key}_{report_date_suffix}"
                current_app.logger.info(f"    Шаг 2: Запрос среза '{slice_key}' для аккаунта {account.login} ({len(account_campaign_ids)} кампаний) за период {step2_first_monday} - {step2_last_sunday}")
                
                # Вызов fetch_report с указанием периода в 4 недели и целями
                parsed_data, _, error_msg = fetch_report(
                    api_client=api_client,
                    campaign_ids=account_campaign_ids, # Передаем ID кампаний ЭТОГО аккаунта
                    date_from=step2_first_monday,
                    date_to=step2_last_sunday,
                    field_names=slice_details['fields'],
                    report_name=report_name,
                    report_type=slice_details['report_type'],
                    goals=metrika_goals_list # Передаем цели
                )

                if error_msg:
                    err_msg = f"Шаг 2: Ошибка API для аккаунта {account.login}, срез '{slice_key}': {error_msg}"
                    current_app.logger.error(err_msg)
                    step2_errors_by_slice.setdefault(slice_key, []).append(f"Account {account.login}: API Error - {error_msg}")
                    # Ошибки API обычно некритичны для всего процесса, но отмечаем для среза
                    continue # Переходим к следующему срезу

                if parsed_data is None:
                    current_app.logger.warning(f"    Шаг 2: Отчет для аккаунта {account.login}, срез '{slice_key}' не вернул данных.")
                    continue
                    
                # --- Обработка и подготовка данных для UPSERT ---
                Model = slice_details['model']
                
                # Фильтруем строки, где нет CampaignId (если это не сам WeeklyCampaignStat)
                valid_slice_data = [row for row in parsed_data if slice_key == 'campaign' or row.get('CampaignId') is not None]
                current_app.logger.debug(f"    Шаг 2: Получено {len(parsed_data)} строк, валидных (с CampaignId): {len(valid_slice_data)} для среза '{slice_key}'")
                
                if not valid_slice_data:
                    continue

                # Группируем по неделям (так как отчет приходит за весь период)
                weekly_grouped_data = {} # { week_start_date: [list_of_rows] }
                for row in valid_slice_data:
                    row_date_str = row.get('Date') # Отчеты возвращают поле 'Date'
                    if not row_date_str: continue 
                    try:
                        row_date = date.fromisoformat(row_date_str)
                        week_start, _ = get_monday_and_sunday(row_date)
                        # Убедимся, что эта неделя входит в наш 4-недельный диапазон
                        if week_start in step2_weeks:
                           if week_start not in weekly_grouped_data:
                               weekly_grouped_data[week_start] = []
                           weekly_grouped_data[week_start].append(row)
                    except ValueError:
                        current_app.logger.warning(f"    Шаг 2: Некорректный формат даты '{row_date_str}' в отчете среза '{slice_key}'. Строка: {row}")
                        continue

                # Теперь проходим по сгруппированным данным и готовим словари для UPSERT
                for week_start, weekly_rows in weekly_grouped_data.items():
                    for row_dict in weekly_rows:
                        stat_entry = {
                            'week_start_date': week_start,
                            'user_id': user_id,
                            'client_id': client_id,
                            'yandex_account_id': account.id,
                            'campaign_id': row_dict.get('CampaignId'),
                            'impressions': row_dict.get('Impressions'),
                            'clicks': row_dict.get('Clicks'),
                            'cost': row_dict.get('Cost'),
                            'conversions': row_dict.get('Conversions'), # Добавлено поле конверсий
                            'updated_at': datetime.utcnow()
                            # 'weekly_campaign_stat_id' будет добавлен позже для детальных срезов
                        }
                        
                        # Добавляем специфичные поля и обновляем имя/тип для WeeklyCampaignStat
                        if slice_key == 'campaign':
                            stat_entry['campaign_name'] = row_dict.get('CampaignName')
                            stat_entry['campaign_type'] = row_dict.get('CampaignType')
                        elif slice_key == 'placement':
                            stat_entry['placement'] = row_dict.get('Placement')
                            stat_entry['ad_network_type'] = row_dict.get('AdNetworkType')
                        elif slice_key == 'query':
                            stat_entry['ad_group_id'] = row_dict.get('AdGroupId')
                            stat_entry['query'] = row_dict.get('Query')
                        elif slice_key == 'geo':
                            stat_entry['location_id'] = row_dict.get('CriteriaId')
                        elif slice_key == 'device':
                            stat_entry['device_type'] = row_dict.get('Device')
                        elif slice_key == 'demographic':
                            stat_entry['gender'] = row_dict.get('Gender')
                            stat_entry['age_group'] = row_dict.get('Age')
                            
                        # Добавляем подготовленный словарь в общий список для данной Модели
                        all_data_to_upsert[Model].append(stat_entry)
                        
                # Задержка между запросами отчетов одного аккаунта
                time.sleep(API_CALL_DELAY) 
                
            # --- Конец цикла по срезам ---
            
            # --- Выполняем UPSERT для аккаунта ---
            current_app.logger.info(f"    Шаг 2: Подготовлены данные для UPSERT аккаунта {account.login}. Начинаем запись в БД...")
            account_rows_upserted = 0
            
            # 1. Сначала UPSERT для WeeklyCampaignStat
            campaign_stats_to_upsert = all_data_to_upsert.get(WeeklyCampaignStat, [])
            if campaign_stats_to_upsert:
                try:
                    stmt = pg_insert(WeeklyCampaignStat).values(campaign_stats_to_upsert)
                    update_stmt = stmt.on_conflict_do_update(
                        constraint='uq_weekly_campaign_stat', # Используем имя ограничения
                        set_={
                            'campaign_name': stmt.excluded.campaign_name,
                            'campaign_type': stmt.excluded.campaign_type,
                            'impressions': stmt.excluded.impressions,
                            'clicks': stmt.excluded.clicks,
                            'cost': stmt.excluded.cost,
                            'conversions': stmt.excluded.conversions, # Обновляем конверсии
                            'updated_at': stmt.excluded.updated_at
                        }
                    )
                    result = db.session.execute(update_stmt)
                    db.session.commit() # Коммитим после каждого типа среза для аккаунта? Или в конце аккаунта?
                    account_rows_upserted += len(campaign_stats_to_upsert)
                    current_app.logger.debug(f"      UPSERT WeeklyCampaignStat: {len(campaign_stats_to_upsert)} записей (затронуто {result.rowcount}).")
                except Exception as e_upsert_camp:
                    db.session.rollback()
                    err_msg = f"Шаг 2: Ошибка DB UPSERT WeeklyCampaignStat для аккаунта {account.login}: {e_upsert_camp}"
                    current_app.logger.exception(err_msg)
                    step2_errors_by_slice.setdefault("DB_UPSERT_WCS", []).append(f"Account {account.login}: DB UPSERT Error - {e_upsert_camp}")
                    step2_success = False # Ошибка БД критична
                    # Прерываем обработку ДРУГИХ срезов для этого аккаунта, так как weekly_campaign_stat_id будет недоступен
                    continue # К следующему аккаунту
            
            # 2. Получаем ID только что обновленных WeeklyCampaignStat
            # Создаем ключи для поиска
            lookup_keys = set()
            for camp_stat in campaign_stats_to_upsert:
                lookup_keys.add((
                    camp_stat['yandex_account_id'], 
                    camp_stat['campaign_id'], 
                    camp_stat['week_start_date']
                ))
                
            weekly_stat_id_map = {}
            if lookup_keys:
                try:
                    fetched_ids = db.session.query(
                        WeeklyCampaignStat.id, 
                        WeeklyCampaignStat.yandex_account_id, 
                        WeeklyCampaignStat.campaign_id, 
                        WeeklyCampaignStat.week_start_date
                    ).filter(
                        WeeklyCampaignStat.yandex_account_id == account.id,
                        WeeklyCampaignStat.week_start_date.in_(step2_weeks),
                        WeeklyCampaignStat.campaign_id.in_(account_campaign_ids) # Фильтр по кампаниям аккаунта
                        # Можно добавить фильтр по tuple, но SQLAlchemy <1.4 может не поддерживать IN для tuple
                    ).all()
                    
                    for id_val, acc_id, camp_id, week_start in fetched_ids:
                         # Формируем ключ как в lookup_keys
                         key = (acc_id, camp_id, week_start)
                         weekly_stat_id_map[key] = id_val
                    current_app.logger.debug(f"      Получено {len(weekly_stat_id_map)} ID из WeeklyCampaignStat для маппинга.")
                except Exception as e_fetch_ids:
                    err_msg = f"Шаг 2: Ошибка получения ID из WeeklyCampaignStat для аккаунта {account.login}: {e_fetch_ids}"
                    current_app.logger.exception(err_msg)
                    step2_errors_by_slice.setdefault("FETCH_WCS_IDS", []).append(f"Account {account.login}: {err_msg}")
                    step2_success = False
                    continue # К следующему аккаунту

            # 3. UPSERT для остальных срезов, добавляя weekly_campaign_stat_id
            for Model, rows_to_upsert in all_data_to_upsert.items():
                if Model == WeeklyCampaignStat: continue # Уже обработали
                if not rows_to_upsert: continue

                valid_rows_for_model = []
                for row in rows_to_upsert:
                    lookup_key = (row['yandex_account_id'], row['campaign_id'], row['week_start_date'])
                    parent_id = weekly_stat_id_map.get(lookup_key)
                    if parent_id:
                        row['weekly_campaign_stat_id'] = parent_id
                        valid_rows_for_model.append(row)
                    else:
                        # Возможно, для этой комбинации (акк,камп,неделя) не было данных в WeeklyCampaignStat?
                        # Это не должно происходить, если weekly_stat_id_map заполнена корректно после UPSERT WCS
                        current_app.logger.warning(f"    Шаг 2: Не найден weekly_campaign_stat_id для ключа {lookup_key}. Пропуск строки: {row}")

                if not valid_rows_for_model: continue
                
                # Получаем имя unique constraint для модели (предполагаем, что оно есть)
                # Можно сделать маппинг Model -> constraint_name
                # constraint_name = f"uq_{Model.__tablename__}" # Не всегда верно, лучше взять из модели или задать явно
                # Возьмем из PROJECT_README (осторожно, если менялось)
                constraint_map = {
                    WeeklyPlacementStat: '_week_placement_uc',
                    WeeklySearchQueryStat: '_week_query_uc',
                    WeeklyGeoStat: '_week_geo_uc',
                    WeeklyDeviceStat: '_week_device_uc',
                    WeeklyDemographicStat: '_week_demographic_uc',
                }
                constraint_name = constraint_map.get(Model)
                if not constraint_name:
                     err_msg = f"Шаг 2: Не найдено имя unique constraint для модели {Model.__name__}. Пропуск UPSERT."
                     current_app.logger.error(err_msg)
                     step2_errors_by_slice.setdefault("DB_UPSERT_DETAIL", []).append(f"Account {account.login}: DB Error for {Model.__name__} - {err_msg}")
                     step2_success = False
                     continue # К следующему срезу

                try:
                    stmt = pg_insert(Model).values(valid_rows_for_model)
                    # Определяем поля для обновления (все метрики и weekly_campaign_stat_id)
                    update_dict = {
                        'impressions': stmt.excluded.impressions,
                        'clicks': stmt.excluded.clicks,
                        'cost': stmt.excluded.cost,
                        'conversions': stmt.excluded.conversions,
                        'weekly_campaign_stat_id': stmt.excluded.weekly_campaign_stat_id,
                        'updated_at': stmt.excluded.updated_at
                    }
                    # Добавляем специфичные поля среза, если они могут меняться (query?)
                    # if Model == WeeklySearchQueryStat: update_dict['query'] = stmt.excluded.query # Если надо
                    
                    update_stmt = stmt.on_conflict_do_update(
                        constraint=constraint_name,
                        set_=update_dict
                    )
                    result = db.session.execute(update_stmt)
                    db.session.commit() # Коммитим после каждого среза?
                    account_rows_upserted += len(valid_rows_for_model)
                    current_app.logger.debug(f"      UPSERT {Model.__name__}: {len(valid_rows_for_model)} записей (затронуто {result.rowcount}).")
                except Exception as e_upsert_detail:
                    db.session.rollback()
                    err_msg = f"Шаг 2: Ошибка DB UPSERT {Model.__name__} для аккаунта {account.login}: {e_upsert_detail}"
                    current_app.logger.exception(err_msg)
                    step2_errors_by_slice.setdefault("DB_UPSERT_DETAIL", []).append(f"Account {account.login}: DB UPSERT Error - {e_upsert_detail}")
                    step2_success = False
                    # Можно прервать обработку аккаунта
                    # break 

            # Фиксируем общее количество строк, сохраненных для аккаунта в Шаге 2
            total_rows_upserted_step2 += account_rows_upserted
            current_app.logger.info(f"    Шаг 2: Завершение UPSERT для аккаунта {account.login}. Сохранено строк: {account_rows_upserted}.")

        except (YandexDirectAuthError, YandexDirectClientError) as e_api_outer_s2:
            err_msg = f"Шаг 2: Ошибка API при обработке аккаунта {account.login}: {e_api_outer_s2}"
            current_app.logger.error(err_msg)
            step2_errors_by_slice.setdefault("ACCOUNT_API_ERROR", []).append(f"Account {account.login}: {err_msg}")
            # Не считаем критичной для *всего* процесса, если другие аккаунты могут обработаться
        except Exception as e_generic_s2:
            err_msg = f"Шаг 2: Непредвиденная ошибка при обработке аккаунта {account.login}: {e_generic_s2}"
            current_app.logger.exception(err_msg)
            step2_errors_by_slice.setdefault("ACCOUNT_UNEXPECTED_ERROR", []).append(f"Account {account.login}: {err_msg}")
            step2_success = False # Непредвиденная ошибка может быть критичной

    # --- Конец цикла по аккаунтам Шага 2 --- 
    total_step2_errors = sum(len(v) for v in step2_errors_by_slice.values())
    current_app.logger.info(f"--- Завершение Шага 2. Успешно UPSERT: {total_rows_upserted_step2} записей. Общее кол-во ошибок: {total_step2_errors}. Критические ошибки: {not step2_success} ---")
    
    # --- Финальное сообщение ---
    end_time = time.time()
    duration = end_time - start_time
    
    # Определяем общий успех (Шаг 1 без крит. ошибок И Шаг 2 без крит. ошибок)
    final_success = step1_success and step2_success 
    
    # --- Формирование детального сообщения об ошибках Шага 2 ---
    step2_error_details = []
    if step2_errors_by_slice:
        step2_error_details.append("Детализация ошибок Шага 2:")
        # Определяем срезы, которые были в плане
        planned_slices = list(slices_to_fetch_step2.keys())
        
        for slice_key in planned_slices:
            errors = step2_errors_by_slice.get(slice_key)
            if errors:
                # Показываем только первую ошибку для краткости
                first_error = str(errors[0])[:150] # Ограничиваем длину
                step2_error_details.append(f"  - Срез '{slice_key}': Ошибка ({len(errors)} шт.): {first_error}...")
            else:
                # Если для среза нет ошибок, проверяем, были ли вообще ошибки в других местах, влияющие на него
                if not final_success and (step2_errors_by_slice.get("FETCH_WCS_IDS") or step2_errors_by_slice.get("ACCOUNT_API_ERROR") or step2_errors_by_slice.get("ACCOUNT_UNEXPECTED_ERROR")):
                     step2_error_details.append(f"  - Срез '{slice_key}': Вероятно, не обновлен из-за ошибок на уровне аккаунта или получения ID.")
                # Убрал сообщение об успехе для среза, чтобы не перегружать вывод
                # else:
                #     step2_error_details.append(f"  - Срез '{slice_key}': OK")
                    
        # Добавляем ошибки, не привязанные к срезу
        for error_key, errors in step2_errors_by_slice.items():
            if error_key not in planned_slices and errors:
                 first_error = str(errors[0])[:150]
                 step2_error_details.append(f"  - Ошибка '{error_key}': ({len(errors)} шт.): {first_error}...")
                 
    step2_error_summary = "\n".join(step2_error_details)

    # --- Формирование основного сообщения --- 
    summary_msg_parts = [f"Обновление статистики завершено за {duration:.2f} сек."]
    summary_msg_parts.append(f"Шаг 1 (Список кампаний): UPSERT ~{campaigns_upserted_total} записей.")
    if step1_errors:
        # Показываем первую ошибку Шага 1
        first_s1_error = str(step1_errors[0])[:150]
        summary_msg_parts.append(f"Ошибок Шага 1: {len(step1_errors)} (первая: {first_s1_error}...)")
        
    summary_msg_parts.append(f"Шаг 2 (Детализация): UPSERT ~{total_rows_upserted_step2} записей.")
    if step2_errors_by_slice:
        summary_msg_parts.append(f"Ошибок Шага 2: {total_step2_errors}.\n{step2_error_summary}") # Добавляем детализацию

    final_message = " ".join(summary_msg_parts)
    
    if final_success:
        current_app.logger.info(final_message)
    else:
        current_app.logger.error(final_message)
        
    return final_success, final_message