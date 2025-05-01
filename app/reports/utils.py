import time
import io
import csv
from datetime import date, timedelta, datetime
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Импорты из приложения
from app import db
from app.models import (
    Client, YandexAccount,
    WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat, 
    WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat
)
from flask import current_app

# Импортируем клиент API и его исключения
from ..api_clients.yandex_direct import YandexDirectClient, YandexDirectClientError, YandexDirectAuthError, YandexDirectTemporaryError, YandexDirectReportError

# URL API Отчетов и Кампаний будут браться из конфигурации приложения
# REPORTS_API_SANDBOX_URL = os.getenv('DIRECT_API_SANDBOX_URL_REPORTS', 'https://api-sandbox.direct.yandex.com/json/v5/reports')
# DIRECT_API_CAMPAIGNS_URL = os.getenv('DIRECT_API_SANDBOX_URL_CAMPAIGNS', 'https://api-sandbox.direct.yandex.com/json/v5/campaigns')

# Задержка между запросами к API Отчетов
API_CALL_DELAY = 2

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

# ----------------------------------------------------------------------
# --- Старая функция fetch_report - БУДЕТ УДАЛЕНА ---
# def fetch_report(api_client: YandexDirectClient, campaign_ids: list[int], 
#                  date_from: date, date_to: date, field_names: list[str], report_name: str, 
#                  report_type: str = 'CUSTOM_REPORT', goals: list[str] | None = None) -> tuple[list[dict] | None, str | None, str | None]:
#     """Заказывает, ожидает и парсит отчет из API Яндекс.Директ v5."""
#     # ... (ВЕСЬ КОД ЭТОЙ ФУНКЦИИ УДАЛЯЕТСЯ) ...
#     pass 
# --- Конец старой функции fetch_report ---
# ----------------------------------------------------------------------


# --- Вспомогательная функция для парсинга отчета ---
def _parse_tsv_report(report_data_raw: str, field_names: list[str], report_name: str) -> tuple[list[dict], str | None]:
    """Парсит сырые данные отчета TSV."""
    parsed_data = []
    parsing_error_msg = None
    rows_processed = 0 
    try:
        current_app.logger.debug(f"Парсинг TSV данных отчета {report_name} ({len(report_data_raw)} байт)...")
        # current_app.logger.debug(f"Raw report data (first 500 chars) for {report_name}:\n{report_data_raw[:500]}") # Опционально для отладки
        
        # Используем StringIO для обработки строки как файла
        report_file = io.StringIO(report_data_raw)
        
        # Пропускаем строки заголовков (название отчета и заголовки столбцов)
        # Яндекс добавляет 2 строки заголовков, если не указаны skipReportHeader/skipColumnHeader
        # Мы не указывали их пропуск в клиенте, так что пропускаем 2 строки
        next(report_file, None) 
        next(report_file, None) 
        
        # Используем csv.DictReader, fieldnames должны точно совпадать с теми, что в API запросе
        tsv_reader = csv.DictReader(report_file, fieldnames=field_names, delimiter='\t')
        
        for i, row in enumerate(tsv_reader):
            rows_processed += 1
            # current_app.logger.debug(f"  Парсинг строки {i+1}: {row}") # Отладка
            parsed_row = {}
            valid_row = True # Флаг валидности строки (например, если нет CampaignId там, где он нужен)
            for header, value in row.items():
                if header is None: # Пропускаем пустые колонки, если вдруг есть
                    continue
                
                clean_value = None
                raw_value = value.strip() if isinstance(value, str) else value
                
                if raw_value == '--' or raw_value is None or raw_value == '':
                    clean_value = None
                elif header in ('Impressions', 'Clicks', 'Conversions', 'Bounces', # Целочисленные
                                'CampaignId', 'AdGroupId', 'CriteriaId', 'LocationOfPresenceId', 'RlAdjustmentId'): 
                    try:
                        clean_value = int(raw_value)
                    except (ValueError, TypeError):
                        current_app.logger.warning(f"Ошибка конвертации в int для поля '{header}' значение '{raw_value}' в отчете '{report_name}', строка {i+1}. Установлено None.")
                        clean_value = None
                        if header == 'CampaignId': # Если не можем спарсить ID кампании, строка может быть бесполезна
                             valid_row = False
                elif header in ('Cost', 'AvgCpc', 'AvgCpm', 'AvgEffectiveBid', # Числа с плавающей точкой
                                'CostPerConversion', 'Revenue', 'GoalsRoi', 'Profit',
                                'BounceRate', 'ConversionRate', 'Ctr', 'WeightedCtr',
                                'AvgImpressionFrequency', 'AvgClickPosition', 'AvgImpressionPosition',
                                'AvgPageviews', 'AvgTrafficVolume'): 
                    try:
                        clean_value = float(raw_value)
                    except (ValueError, TypeError):
                        current_app.logger.warning(f"Ошибка конвертации в float для поля '{header}' значение '{raw_value}' в отчете '{report_name}', строка {i+1}. Установлено None.")
                        clean_value = None
                else: # Строковые значения
                    clean_value = raw_value
                    
                parsed_row[header] = clean_value
                
            if valid_row: # Добавляем строку, только если она валидна (например, есть CampaignId)
                parsed_data.append(parsed_row)
            else:
                current_app.logger.warning(f"Пропуск невалидной строки {i+1} при парсинге отчета '{report_name}': {row}")

        current_app.logger.info(f"  Парсинг отчета {report_name} завершен. Всего строк прочитано: {rows_processed}. Успешно спарсено: {len(parsed_data)}.")

    except Exception as e_parse:
        parsing_error_msg = f"Критическая ошибка парсинга отчета {report_name}: {e_parse}"
        current_app.logger.exception(parsing_error_msg)
        # Не возвращаем частично спарсенные данные при критической ошибке
        return [], parsing_error_msg 

    return parsed_data, None


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
    step1_success = True
    step1_errors = []   
    campaigns_upserted_total = 0
    step1_field_names = ['CampaignId', 'CampaignName', 'CampaignType', 'Impressions', 'Clicks', 'Cost']

    for account in accounts:
        current_app.logger.info(f"  Шаг 1: Обработка аккаунта {account.login} (ID: {account.id})")
        try:
            api_client = YandexDirectClient(yandex_account_id=account.id, current_user_id=user_id)
            
            report_date_suffix = last_week_monday.strftime('%Y%m%d')
            report_name = f"client{client_id}_acc{account.id}_step1_camp_list_{report_date_suffix}"
            
            # ---> ИЗМЕНЕНИЕ: Формируем report_definition и вызываем api_client.get_report() <---
            selection_criteria_s1 = {
                'DateFrom': last_week_monday.strftime('%Y-%m-%d'),
                'DateTo': last_week_sunday.strftime('%Y-%m-%d')
                # Фильтр по CampaignId не нужен здесь, т.к. отчет CAMPAIGN_PERFORMANCE_REPORT
            }
            
            report_definition_s1 = {
                'params': {
                    'SelectionCriteria': selection_criteria_s1,
                    'FieldNames': step1_field_names,
                    'ReportName': report_name,
                    'ReportType': 'CAMPAIGN_PERFORMANCE_REPORT', # Используем стандартный тип
                    'DateRangeType': 'CUSTOM_DATE',
                    'Format': 'TSV',
                    'IncludeVAT': 'NO',
                    'IncludeDiscount': 'NO' 
                    # Goals не нужны для Шага 1
                }
            }
            
            report_data_raw = None
            parsed_data = None
            error_msg = None
            
            try:
                 # Вызываем новый метод клиента
                 report_data_raw = api_client.get_report(report_definition_s1)
                 
                 # Парсим результат здесь же
                 if report_data_raw:
                      parsed_data, parsing_error = _parse_tsv_report(report_data_raw, step1_field_names, report_name)
                      if parsing_error:
                           error_msg = f"Ошибка парсинга отчета Шага 1 для {account.login}: {parsing_error}"
                           current_app.logger.error(error_msg)
                           # Считаем ошибку парсинга некритичной для аккаунта, но логируем
                           step1_errors.append(error_msg)
                           parsed_data = None # Не используем частично спарсенные данные
                 else:
                      # Если get_report вернул пустую строку (теоретически возможно?)
                      current_app.logger.warning(f"  Шаг 1: Метод get_report для аккаунта {account.login} вернул пустые данные.")
                      parsed_data = [] # Пустой список

            except (YandexDirectAuthError, YandexDirectReportError, YandexDirectTemporaryError, YandexDirectClientError) as e_report:
                 # Ловим ошибки от get_report()
                 error_msg = f"Шаг 1: Ошибка API/Отчета для аккаунта {account.login}: {e_report}"
                 current_app.logger.error(error_msg)
                 step1_errors.append(error_msg)
                 continue # Переходим к следующему аккаунту
            except ValueError as e_val: # Ошибка в report_definition
                 error_msg = f"Шаг 1: Ошибка конфигурации запроса отчета для {account.login}: {e_val}"
                 current_app.logger.error(error_msg)
                 step1_errors.append(error_msg)
                 continue # Ошибка конфигурации, пропускаем аккаунт
            except Exception as e_generic_inner:
                 # Другие неожиданные ошибки при вызове/парсинге
                 error_msg = f"Шаг 1: Неожиданная ошибка при получении/парсинге отчета для {account.login}: {e_generic_inner}"
                 current_app.logger.exception(error_msg)
                 step1_errors.append(error_msg)
                 step1_success = False # Считаем критичной? Да.
                 break # Прерываем цикл по аккаунтам
            # ---> КОНЕЦ ИЗМЕНЕНИЯ <---

            # Дальнейшая логика Шага 1 остается почти без изменений, 
            # но использует `parsed_data` и `error_msg` из нового блока
            if error_msg and parsed_data is None: # Если была ошибка API/парсинга и данных нет
                 continue # Уже залогировали, идем дальше

            if parsed_data is None: # Если отчет не был получен (ошибка выше) или не спарсился
                current_app.logger.warning(f"  Шаг 1: Отчет для аккаунта {account.login} не содержит данных после получения/парсинга.")
                continue
                
            # Фильтруем строки без CampaignId (логика парсера _parse_tsv_report может это делать)
            valid_parsed_data = [row for row in parsed_data if row.get('CampaignId') is not None]
            if not valid_parsed_data:
                 current_app.logger.info(f"  Шаг 1: Нет валидных строк (с CampaignId) в отчете для аккаунта {account.login}.")
                 continue
                 
            # Готовим данные для UPSERT 
            upsert_data = []
            for campaign_data in valid_parsed_data: 
                # ... (формирование словаря для UPSERT) ...
                upsert_data.append({
                    'week_start_date': last_week_monday, 
                    'user_id': user_id,
                    'client_id': client_id,
                    'yandex_account_id': account.id,
                    'campaign_id': campaign_data.get('CampaignId'), # Берем ID из валидных данных
                    'campaign_name': campaign_data.get('CampaignName'),
                    'campaign_type': campaign_data.get('CampaignType'),
                    'impressions': campaign_data.get('Impressions'),
                    'clicks': campaign_data.get('Clicks'),        
                    'cost': campaign_data.get('Cost'),            
                    'updated_at': datetime.utcnow()
                })
            
            if not upsert_data:
                current_app.logger.info(f"    Шаг 1: Нет данных для UPSERT для аккаунта {account.login}, неделя {last_week_monday}.")
                continue
                
            # ---> ИСПРАВЛЕНИЕ: Восстанавливаем определение stmt и update_stmt <---
            stmt = pg_insert(WeeklyCampaignStat).values(upsert_data)
            update_stmt = stmt.on_conflict_do_update(
                constraint='uq_weekly_campaign_stat', 
                set_={
                    'campaign_name': stmt.excluded.campaign_name,
                    'campaign_type': stmt.excluded.campaign_type,
                    'impressions': stmt.excluded.impressions,
                    'clicks': stmt.excluded.clicks,
                    'cost': stmt.excluded.cost,
                    'updated_at': stmt.excluded.updated_at 
                }
            )
            # ---> КОНЕЦ ИСПРАВЛЕНИЯ <---
            
            # Выполняем UPSERT 
            try:
                result = db.session.execute(update_stmt) # Теперь update_stmt определена
                db.session.commit()
                campaigns_upserted_total += len(upsert_data)
                current_app.logger.info(f"    Шаг 1: Успешно UPSERT {len(upsert_data)} записей (затронуто строк: {result.rowcount}) для аккаунта {account.login}, неделя {last_week_monday}.") 
            except Exception as e_upsert:
                # ... (rollback, log error) ...
                db.session.rollback()
                err_msg = f"Шаг 1: Ошибка DB UPSERT для аккаунта {account.login}, неделя {last_week_monday}: {e_upsert}"
                current_app.logger.exception(err_msg)
                step1_errors.append(err_msg)
                step1_success = False
                # break # Можно раскомментировать, если ошибка критична для всего Шага 1
                
        except (YandexDirectAuthError, YandexDirectClientError) as e_api_outer:
            # Эти ошибки теперь должны ловиться внутри блока try/except для get_report
            # Но оставим на случай ошибок инициализации клиента
            err_msg = f"Шаг 1: Ошибка API (внешняя) при обработке аккаунта {account.login}: {e_api_outer}"
            current_app.logger.error(err_msg)
            step1_errors.append(err_msg)
            # Не прерываем цикл, т.к. ошибка может быть только с одним аккаунтом
        except Exception as e_generic:
            # Эти ошибки теперь должны ловиться внутри блока try/except для get_report/парсинга
            # Но оставим на случай других непредвиденных ошибок
            err_msg = f"Шаг 1: Непредвиденная ошибка (внешняя) при обработке аккаунта {account.login}: {e_generic}"
            current_app.logger.exception(err_msg)
            step1_errors.append(err_msg)
            step1_success = False # Считаем внешнюю ошибку критичной
            break # Прерываем цикл по аккаунтам

    current_app.logger.info(f"--- Завершение Шага 1. Успешно UPSERT: {campaigns_upserted_total} записей. Ошибок аккаунтов: {len(step1_errors)}. Общий успех: {step1_success} ---")

    # --- Проверка успеха Шага 1 --- 
    if not step1_success:
        # ... (обработка критической ошибки Шага 1) ...
        error_details = "; ".join(step1_errors[:3])
        msg = f"Критическая ошибка на Шаге 1 (обновление списка кампаний): {error_details}... Обновление прервано."
        current_app.logger.error(msg)
        return False, msg
    elif step1_errors: 
        # ... (лог некритических ошибок Шага 1) ...
        current_app.logger.warning(f"Во время Шага 1 были некритические ошибки ({len(step1_errors)}). Продолжаем Шаг 2...")

    # --- Шаг 2: Полная загрузка детальной статистики за 4 НЕДЕЛИ --- 
    current_app.logger.info(f"--- Начало Шага 2: Полная загрузка статистики за {len(step2_weeks)} недели ---")
    step2_success = True 
    step2_errors_by_slice = {}
    total_rows_upserted_step2 = 0
    processed_campaign_ids_step2 = set()

    # Получаем цели клиента
    metrika_goals_list = _parse_metrika_goals(client.metrika_goals)
    current_app.logger.info(f"Используемые цели Метрики для Шага 2: {metrika_goals_list}")
    
    # ---> ИСПРАВЛЕНИЕ: Восстанавливаем блок определения campaigns_to_update и account_campaign_map <---
    # Определяем, какие именно кампании нужно обновить 
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
        end_time = time.time()
        duration = end_time - start_time
        # Считаем это успехом, так как Шаг 1 мог пройти, а данных для Шага 2 просто нет
        return True, f"Шаг 1 завершен ({campaigns_upserted_total} записей). {msg} Общее время: {duration:.2f} сек."
        
    # Группируем campaign_id по yandex_account_id для удобства
    account_campaign_map = {}
    for acc_id, camp_id in campaigns_to_update_list:
        if acc_id not in account_campaign_map:
            account_campaign_map[acc_id] = []
        account_campaign_map[acc_id].append(camp_id)
        processed_campaign_ids_step2.add(camp_id) # Добавляем в общий сет
        
    current_app.logger.info(f"Шаг 2: Найдено {len(campaigns_to_update_list)} пар (аккаунт, кампания) для обновления детальной статистики.")
    # ---> КОНЕЦ ИСПРАВЛЕНИЯ <---
    
    # Определяем срезы для Шага 2 
    base_metrics_step2 = BASE_METRICS + ['Conversions'] # Добавляем поле Conversions
    slices_to_fetch_step2 = {
        'campaign': {'fields': ['CampaignId', 'CampaignName', 'CampaignType'] + base_metrics_step2, 'model': WeeklyCampaignStat, 'report_type': 'CAMPAIGN_PERFORMANCE_REPORT'},
        'placement': {'fields': ['CampaignId', 'Placement', 'AdNetworkType'] + base_metrics_step2, 'model': WeeklyPlacementStat, 'report_type': 'CUSTOM_REPORT'},
        'query': {'fields': ['Date', 'CampaignId', 'AdGroupId', 'CriteriaId', 'CriteriaType', 'SearchQuery', 'Impressions', 'Clicks', 'Cost'], 
                  'model': WeeklySearchQueryStat, 
                  'report_type': 'SEARCH_QUERY_PERFORMANCE_REPORT'},
        'geo': {'fields': ['CampaignId', 'CriteriaId'] + base_metrics_step2, 'model': WeeklyGeoStat, 'report_type': 'CUSTOM_REPORT'},
        'device': {'fields': ['CampaignId', 'Device'] + base_metrics_step2, 'model': WeeklyDeviceStat, 'report_type': 'CUSTOM_REPORT'},
        'demographic': {'fields': ['CampaignId', 'Gender', 'Age'] + base_metrics_step2, 'model': WeeklyDemographicStat, 'report_type': 'CUSTOM_REPORT'},
    }

    # --- Цикл по аккаунтам Шага 2 ---
    for account in accounts:
        if account.id not in account_campaign_map: # Пропускаем аккаунты без кампаний к обновлению
            current_app.logger.debug(f"  Шаг 2: Пропуск аккаунта {account.login} (ID: {account.id}), нет кампаний для обновления в этом аккаунте.")
            continue

        account_campaign_ids = account_campaign_map[account.id] # Теперь account_campaign_map определена
        current_app.logger.info(f"--- Шаг 2: Обработка аккаунта {account.login} (ID: {account.id}). Кампании: {len(account_campaign_ids)} ---")
        
        try:
            api_client = YandexDirectClient(yandex_account_id=account.id, current_user_id=user_id)
            
            all_data_to_upsert = {model_details['model']: [] for model_details in slices_to_fetch_step2.values()}
            
            # --- Цикл по срезам для данного аккаунта ---
            for slice_key, slice_details in slices_to_fetch_step2.items():
                report_date_suffix = step2_first_monday.strftime('%Y%m%d')
                report_name = f"client{client_id}_acc{account.id}_step2_{slice_key}_{report_date_suffix}"
                current_app.logger.info(f"    Шаг 2: Запрос среза '{slice_key}' для аккаунта {account.login} ({len(account_campaign_ids)} кампаний) за период {step2_first_monday} - {step2_last_sunday}")
                
                # ---> ИЗМЕНЕНИЕ: Формируем report_definition и вызываем api_client.get_report() <---
                selection_criteria_s2 = {
                    'DateFrom': step2_first_monday.strftime('%Y-%m-%d'),
                    'DateTo': step2_last_sunday.strftime('%Y-%m-%d'),
                    # Добавляем фильтр по CampaignId, если кампании есть
                    'Filter': [{ 
                        'Field': 'CampaignId', 
                        'Operator': 'IN', 
                        'Values': [str(cid) for cid in account_campaign_ids] 
                    }] if account_campaign_ids else [] # Пустой фильтр, если список кампаний пуст
                }
                
                report_definition_s2 = {
                    'params': {
                        'SelectionCriteria': selection_criteria_s2,
                        'FieldNames': slice_details['fields'],
                        'ReportName': report_name,
                        'ReportType': slice_details['report_type'],
                        'DateRangeType': 'CUSTOM_DATE',
                        'Format': 'TSV',
                        'IncludeVAT': 'NO',
                        'IncludeDiscount': 'NO',
                    }
                }
                # Добавляем цели, если они есть
                if metrika_goals_list:
                     report_definition_s2['params']['Goals'] = metrika_goals_list
                     
                report_data_raw = None
                parsed_data = None
                error_msg = None
                
                try:
                     report_data_raw = api_client.get_report(report_definition_s2)
                     if report_data_raw:
                          # Передаем поля из slice_details['fields'] для парсинга
                          parsed_data, parsing_error = _parse_tsv_report(report_data_raw, slice_details['fields'], report_name)
                          if parsing_error:
                               error_msg = f"Ошибка парсинга отчета Шага 2 ({slice_key}) для {account.login}: {parsing_error}"
                               current_app.logger.error(error_msg)
                               step2_errors_by_slice.setdefault(slice_key, []).append(f"Account {account.login}: Parsing Error - {error_msg}")
                               parsed_data = None 
                     else:
                          current_app.logger.warning(f"  Шаг 2: Метод get_report для аккаунта {account.login}, срез '{slice_key}' вернул пустые данные.")
                          parsed_data = []
                          
                except (YandexDirectAuthError, YandexDirectReportError, YandexDirectTemporaryError, YandexDirectClientError) as e_report_s2:
                     error_msg = f"Шаг 2: Ошибка API/Отчета для аккаунта {account.login}, срез '{slice_key}': {e_report_s2}"
                     current_app.logger.error(error_msg)
                     step2_errors_by_slice.setdefault(slice_key, []).append(f"Account {account.login}: API Error - {error_msg}")
                     continue # Переходим к следующему срезу
                except ValueError as e_val_s2:
                     error_msg = f"Шаг 2: Ошибка конфигурации запроса отчета ({slice_key}) для {account.login}: {e_val_s2}"
                     current_app.logger.error(error_msg)
                     step2_errors_by_slice.setdefault(slice_key, []).append(f"Account {account.login}: Config Error - {error_msg}")
                     continue # К следующему срезу
                except Exception as e_generic_inner_s2:
                     error_msg = f"Шаг 2: Неожиданная ошибка при получении/парсинге отчета ({slice_key}) для {account.login}: {e_generic_inner_s2}"
                     current_app.logger.exception(error_msg)
                     step2_errors_by_slice.setdefault(slice_key, []).append(f"Account {account.login}: Unexpected Error - {error_msg}")
                     step2_success = False # Критичная ошибка
                     break # Прерываем цикл по срезам для этого аккаунта
                # ---> КОНЕЦ ИСПРАВЛЕНИЯ ВНУТРЕННИХ EXCEPT <---
                
                if error_msg and parsed_data is None:
                     continue # Ошибка уже залогирована

                if parsed_data is None:
                    current_app.logger.warning(f"    Шаг 2: Отчет для аккаунта {account.login}, срез '{slice_key}' не содержит данных после получения/парсинга.")
                    continue
                    
                # Обработка и подготовка данных для UPSERT 
                Model = slice_details['model']
                
                # Фильтруем строки без CampaignId (на всякий случай)
                valid_slice_data = [row for row in parsed_data if row.get('CampaignId') is not None]
                if not valid_slice_data:
                     current_app.logger.info(f"    Шаг 2: Нет валидных строк (с CampaignId) в отчете среза '{slice_key}' для аккаунта {account.login}.")
                     continue
                     
                # Группируем данные по неделям (если отчет содержит поле 'Date')
                # или просто создаем одну запись с датой начала последней недели периода
                # TODO: Решить, как правильно агрегировать данные за 4 недели для детальных срезов. 
                # Пока что будем записывать данные с датой начала *каждой* недели, если есть 'Date',
                # или с датой начала *последней* недели, если 'Date' нет.
                
                data_for_model = []
                # Примерная логика: пройтись по valid_slice_data и сформировать словари для UPSERT
                # Нужно адаптировать под конкретные поля каждой модели!
                for row_data in valid_slice_data:
                    # Определяем дату начала недели
                    # Если в отчете есть 'Date', используем ее. Иначе - last_week_monday? Нет, лучше step2_last_monday
                    row_date_str = row_data.get('Date')
                    week_start = None
                    if row_date_str:
                        try:
                            report_date = datetime.strptime(row_date_str, '%Y-%m-%d').date()
                            week_start, _ = get_monday_and_sunday(report_date)
                        except ValueError:
                           current_app.logger.warning(f"Не удалось спарсить дату '{row_date_str}' в срезе '{slice_key}', строка: {row_data}. Используется {step2_last_monday}.")
                           week_start = step2_last_monday
                    else:
                       # Если поля 'Date' нет (например, CAMPAIGN_PERFORMANCE_REPORT), 
                       # используем дату начала последней недели периода для WeeklyCampaignStat
                       if Model == WeeklyCampaignStat:
                           week_start = step2_last_monday 
                       else:
                           # Для других срезов без Date - это странно. Логируем и используем последнюю неделю.
                           current_app.logger.warning(f"Отсутствует поле 'Date' в срезе '{slice_key}' для модели {Model.__name__}. Используется {step2_last_monday}.")
                           week_start = step2_last_monday
                    
                    # Формируем базовый словарь для модели
                    # Важно: Ключи словаря должны ТОЧНО совпадать с именами полей в модели SQLAlchemy!
                    stat_entry = {
                        'week_start_date': week_start,
                        'campaign_id': row_data.get('CampaignId'),
                        'yandex_account_id': account.id,
                        'user_id': user_id,
                        'client_id': client_id,
                        'impressions': row_data.get('Impressions'),
                        'clicks': row_data.get('Clicks'),
                        'cost': row_data.get('Cost'),
                        'conversions': row_data.get('Conversions'), # Может быть None
                        # 'updated_at': datetime.utcnow() # Добавляем, если поле есть в модели
                    }
                    
                    # Добавляем специфичные поля для каждой модели
                    if Model == WeeklyCampaignStat:
                        stat_entry['campaign_name'] = row_data.get('CampaignName')
                        stat_entry['campaign_type'] = row_data.get('CampaignType')
                        stat_entry['updated_at'] = datetime.utcnow() # Обновляем время
                    elif Model == WeeklyPlacementStat:
                        stat_entry['placement'] = row_data.get('Placement')
                        stat_entry['ad_network_type'] = row_data.get('AdNetworkType')
                    elif Model == WeeklySearchQueryStat:
                        stat_entry['ad_group_id'] = row_data.get('AdGroupId')
                        stat_entry['query'] = row_data.get('SearchQuery') # Изменили поле в запросе
                        # Добавляем поля CriteriaId и CriteriaType, если они нужны в модели
                        # stat_entry['criteria_id'] = row_data.get('CriteriaId')
                        # stat_entry['criteria_type'] = row_data.get('CriteriaType')
                    elif Model == WeeklyGeoStat:
                        stat_entry['location_id'] = row_data.get('CriteriaId') # CriteriaId -> location_id
                    elif Model == WeeklyDeviceStat:
                        stat_entry['device_type'] = row_data.get('Device') # Device -> device_type
                    elif Model == WeeklyDemographicStat:
                        stat_entry['gender'] = row_data.get('Gender')
                        stat_entry['age_group'] = row_data.get('Age') # Age -> age_group
                        
                    # Добавляем готовый словарь в список для UPSERT
                    all_data_to_upsert[Model].append(stat_entry)

                current_app.logger.debug(f"    Подготовлено {len(all_data_to_upsert[Model])} записей для UPSERT в {Model.__name__} из среза '{slice_key}'.")
                # ---> КОНЕЦ БЛОКА ОБРАБОТКИ ДАННЫХ <---
                
                # Добавляем задержку между запросами разных срезов
                time.sleep(API_CALL_DELAY) 
                
            # --- Конец цикла по срезам ---
            if not step2_success: # Если была критическая ошибка в цикле по срезам, прерываем аккаунт
                 current_app.logger.error(f"  Шаг 2: Прерывание обработки аккаунта {account.login} из-за критической ошибки в срезах.")
                 break # Выход из цикла по аккаунтам
                 
            # ---> ДОБАВЛЕНО: UPSERT данных для всех срезов аккаунта < ---
            current_app.logger.info(f"    Шаг 2: Начало UPSERT данных для аккаунта {account.login}")
            account_upsert_count = 0
            for Model, data_list in all_data_to_upsert.items():
                 if not data_list:
                     current_app.logger.debug(f"      Нет данных для UPSERT в модель {Model.__tablename__} для аккаунта {account.login}")
                     continue
                     
                 # ---> ИСПРАВЛЕНИЕ: Правильный блок try/except и if/elif/else <---
                 try:
                     stmt = pg_insert(Model).values(data_list)
                     # Определяем constraint и поля для обновления
                     # TODO: Перепроверить constraint и set_ для каждой модели!
                     update_stmt = None # Инициализируем
                     
                     if Model == WeeklyPlacementStat:
                         update_stmt = stmt.on_conflict_do_update(
                             constraint='_week_placement_uc', # Имя ограничения уникальности
                             set_={
                                 'impressions': stmt.excluded.impressions,
                                 'clicks': stmt.excluded.clicks,
                                 'cost': stmt.excluded.cost,
                                 'conversions': stmt.excluded.conversions 
                                 # 'updated_at': datetime.utcnow() # Если есть поле updated_at
                             }
                         )
                     elif Model == WeeklySearchQueryStat:
                         update_stmt = stmt.on_conflict_do_update(
                             constraint='_week_query_uc', 
                             set_={
                                 'impressions': stmt.excluded.impressions,
                                 'clicks': stmt.excluded.clicks,
                                 'cost': stmt.excluded.cost,
                                 # 'conversions': stmt.excluded.conversions # В отчете query нет conversions
                             }
                         )
                     elif Model == WeeklyGeoStat:
                         update_stmt = stmt.on_conflict_do_update(
                             constraint='_week_geo_uc', 
                             set_={ 
                                 'impressions': stmt.excluded.impressions,
                                 'clicks': stmt.excluded.clicks,
                                 'cost': stmt.excluded.cost,
                                 'conversions': stmt.excluded.conversions
                             }
                         )
                     elif Model == WeeklyDeviceStat:
                         update_stmt = stmt.on_conflict_do_update(
                             constraint='_week_device_uc', 
                             set_={ 
                                 'impressions': stmt.excluded.impressions,
                                 'clicks': stmt.excluded.clicks,
                                 'cost': stmt.excluded.cost,
                                 'conversions': stmt.excluded.conversions
                             }
                         )
                     elif Model == WeeklyDemographicStat:
                         update_stmt = stmt.on_conflict_do_update(
                             constraint='_week_demographic_uc', 
                             set_={ 
                                 'impressions': stmt.excluded.impressions,
                                 'clicks': stmt.excluded.clicks,
                                 'cost': stmt.excluded.cost,
                                 'conversions': stmt.excluded.conversions
                             }
                         )
                     elif Model == WeeklyCampaignStat: # Шаг 2 тоже обновляет эту таблицу!
                         update_stmt = stmt.on_conflict_do_update(
                             constraint='uq_weekly_campaign_stat', 
                             set_={
                                 'campaign_name': stmt.excluded.campaign_name, # Обновляем имя/тип на всякий случай
                                 'campaign_type': stmt.excluded.campaign_type,
                                 'impressions': stmt.excluded.impressions,
                                 'clicks': stmt.excluded.clicks,
                                 'cost': stmt.excluded.cost,
                                 'conversions': stmt.excluded.conversions, # Добавляем конверсии
                                 'updated_at': datetime.utcnow()
                             }
                         ) 
                     else:
                         current_app.logger.error(f"      Неизвестная модель {Model.__tablename__} для UPSERT в Шаге 2.")
                         continue # Пропускаем неизвестную модель
                     
                     # Выполняем UPSERT, если update_stmt было создано
                     if update_stmt is not None:
                         result = db.session.execute(update_stmt)
                         db.session.commit()
                         rows_affected = result.rowcount
                         # Считаем по data_list, так как rowcount может быть 0 при обновлении теми же данными
                         account_upsert_count += len(data_list) 
                         current_app.logger.info(f"      Успешно UPSERT {len(data_list)} записей (затронуто строк: {rows_affected}) в {Model.__tablename__} для аккаунта {account.login}")
                     else:
                          # Эта ветка не должна выполняться из-за continue выше, но на всякий случай
                          current_app.logger.error(f"      Не удалось создать update_stmt для модели {Model.__tablename__}")
                         
                 except Exception as e_upsert_s2:
                     db.session.rollback()
                     err_msg = f"Шаг 2: Ошибка DB UPSERT для аккаунта {account.login}, модель {Model.__tablename__}: {e_upsert_s2}"
                     current_app.logger.exception(err_msg)
                     step2_errors_by_slice.setdefault(f"UPSERT_{Model.__tablename__}", []).append(f"Account {account.login}: {err_msg}")
                     step2_success = False
                     break # Критичная ошибка UPSERT - прерываем обработку аккаунта
            
            if not step2_success: # Если ошибка была в цикле UPSERT
                break # Выход из цикла по аккаунтам

            total_rows_upserted_step2 += account_upsert_count # Добавляем к общему счетчику
            current_app.logger.info(f"    Шаг 2: Завершение UPSERT для аккаунта {account.login}. Всего записей: {account_upsert_count}")
            # ---> КОНЕЦ БЛОКА UPSERT < ---

        except (YandexDirectAuthError, YandexDirectClientError) as e_api_outer_s2:
            # Ошибки инициализации клиента
            err_msg = f"Шаг 2: Ошибка API (внешняя) при обработке аккаунта {account.login}: {e_api_outer_s2}"
            current_app.logger.error(err_msg)
            step2_errors_by_slice.setdefault("OuterAPIError", []).append(f"Account {account.login}: {err_msg}")
            step2_success = False # Считаем ошибку инициализации критичной для Шага 2
        except Exception as e_generic_s2:
            # Другие внешние ошибки
            err_msg = f"Шаг 2: Непредвиденная ошибка (внешняя) при обработке аккаунта {account.login}: {e_generic_s2}"
            current_app.logger.exception(err_msg)
            step2_errors_by_slice.setdefault("OuterGenericError", []).append(f"Account {account.login}: {err_msg}")
            step2_success = False # Считаем внешнюю ошибку критичной для Шага 2

    # --- Конец цикла по аккаунтам Шага 2 --- 
    current_app.logger.info(f"--- Завершение Шага 2. Успешно UPSERT (суммарно): {total_rows_upserted_step2} записей. Ошибок по срезам/UPSERT: {len(step2_errors_by_slice)}. Общий успех Шага 2: {step2_success} ---")
    # Логируем детали ошибок Шага 2, если они были
    if step2_errors_by_slice:
        for key, errors in step2_errors_by_slice.items():
            current_app.logger.error(f"  Детали ошибок Шага 2 для '{key}': {'; '.join(errors[:3])}...")
    
    # --- Финальное сообщение ---
    end_time = time.time()
    duration = end_time - start_time
    
    final_success = step1_success and step2_success 
    # Улучшаем финальное сообщение
    final_message_parts = [
        f"Шаг 1: Успех={step1_success}, Записей={campaigns_upserted_total}, Ошибок={len(step1_errors)}.",
        f"Шаг 2: Успех={step2_success}, Записей={total_rows_upserted_step2}, Ошибок={len(step2_errors_by_slice)}.",
        f"Время: {duration:.2f} сек."
    ]
    if not final_success:
        final_message_parts.append("Смотрите логи для деталей ошибок.")
        
    final_message = " ".join(final_message_parts)
        
    return final_success, final_message

# Убрал лишние константы и комментарий про fetch_report