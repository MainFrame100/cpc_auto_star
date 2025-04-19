import requests
import json
import time
import io
import csv
from datetime import date, timedelta, datetime

# URL API Отчетов (песочница)
REPORTS_API_SANDBOX_URL = 'https://api-sandbox.direct.yandex.com/json/v5/reports'

# Константы для ожидания отчета
MAX_RETRIES = 15
RETRY_DELAY_SECONDS = 5

def fetch_placement_report(access_token: str, client_login: str, campaign_id: int) -> tuple[list[dict] | None, str | None, str | None]:
    """Заказывает, ожидает и парсит отчет PLACEMENT_REPORT из API Яндекс.Директ.

    Args:
        access_token: Действительный OAuth-токен.
        client_login: Логин клиента в Яндекс.Директе.
        campaign_id: ID кампании, для которой нужен отчет.

    Returns:
        Кортеж: (parsed_data, raw_data, error_message).
        parsed_data: Список словарей с данными отчета или None.
        raw_data: Сырой текст отчета (TSV) или None.
        error_message: Строка с описанием ошибки (заказа, ожидания или парсинга) или None.
    """
    print(f"Запуск fetch_placement_report для campaign_id={campaign_id}, client_login={client_login}")

    # --- 1. Заказ отчета --- 
    headers_post = {
        'Authorization': f'Bearer {access_token}',
        'Client-Login': client_login,
        'Accept-Language': 'ru',
        'Content-Type': 'application/json',
        'returnMoneyInMicros': 'false', 
        'skipReportHeader': 'true',
        'skipReportSummary': 'true'
    }
    if not client_login:
        headers_post.pop('Client-Login', None)

    # Уникальное имя отчета
    timestamp_unique = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    report_definition = {
        'params': {
            'SelectionCriteria': {
                'Filter': [{
                    'Field': 'CampaignId',
                    'Operator': 'EQUALS',
                    'Values': [str(campaign_id)]
                }],
                # Даты убираем, т.к. используем DateRangeType
                # 'DateFrom': date1.strftime('%Y-%m-%d'),
                # 'DateTo': date2.strftime('%Y-%m-%d')
            },
            'FieldNames': [
                # Dimension first (usually good practice)
                'Placement',
                # Metrics
                'Impressions',
                'Clicks',
                'Cost',
                'BounceRate'
            ],
            'ReportName': f'Custom Placement Report for Campaign {campaign_id} - {timestamp_unique}',
            'ReportType': 'CUSTOM_REPORT',
            'DateRangeType': 'LAST_30_DAYS',
            'Format': 'TSV',
            'IncludeVAT': 'YES',
            'IncludeDiscount': 'NO',
            # Potentially add Page/Limit later if needed, but API might handle defaults
            # 'Page': { 'Limit': 10000 } # Example
        }
    }

    report_data_raw = None
    retries = 0 # Добавим счетчик попыток для отладки/ограничения
    MAX_REPORT_RETRIES = 20 # Ограничим общее число попыток

    while retries < MAX_REPORT_RETRIES:
        retries += 1
        print(f"Попытка {retries}/{MAX_REPORT_RETRIES}: Отправка POST-запроса для заказа/проверки отчета...")
        try:
            # ВСЕГДА отправляем POST
            response = requests.post(REPORTS_API_SANDBOX_URL, headers=headers_post, json=report_definition)
            
            status_code = response.status_code
            request_id = response.headers.get("RequestId", "N/A")
            print(f"  Статус ответа: {status_code}. RequestId: {request_id}")

            # Код 200: Отчет готов
            if status_code == 200:
                print("Отчет готов!")
                report_data_raw = response.text
                break # Выходим из цикла

            # Код 201/202: Отчет формируется, ждем
            elif status_code in [201, 202]:
                retry_interval = int(response.headers.get("retryIn", 30))
                print(f"Отчет формируется. Повторная проверка через {retry_interval} секунд...")
                time.sleep(retry_interval)
                continue # Продолжаем цикл (снова отправим POST)
            
            # Любой другой статус = Ошибка
            else:
                response.raise_for_status()

        except requests.exceptions.HTTPError as e_http:
            error_msg = f"Ошибка HTTP: {e_http}. "
            try: error_msg += response.text 
            except Exception: pass
            print(error_msg)
            # Выходим при ошибке (можно добавить логику повтора для 5xx)
            return None, None, error_msg 
        except requests.exceptions.RequestException as e:
            error_msg = f"Сетевая ошибка: {e}. Повтор через 60 сек..."
            print(error_msg)
            time.sleep(60)
            # Не сбрасываем флаг, продолжаем тот же POST
            continue # Продолжаем цикл
        except Exception as e:
            error_msg = f"Непредвиденная ошибка: {e}"
            print(error_msg)
            return None, None, error_msg

    # Сюда попадаем после break (успех) или исчерпания retries
    if report_data_raw is None:
         error_msg = f"Отчет не был готов после {MAX_REPORT_RETRIES} попыток."
         print(error_msg)
         return None, None, error_msg

    # --- 3. Парсинг отчета (TSV) --- 
    parsed_data = [] # Инициализируем пустой список
    parsing_error_msg = None
    try:
        print("Парсинг TSV данных (упрощенный)...")
        report_file = io.StringIO(report_data_raw)
        
        # Создаем csv.reader
        tsv_reader = csv.reader(report_file, delimiter='\t')
        
        # Первая строка теперь - это заголовки
        try:
            headers_list = next(tsv_reader)
            print(f"Заголовки столбцов из отчета: {headers_list}")
        except StopIteration:
            error_msg = "Ошибка парсинга: Отчет не содержит строку с заголовками столбцов (пустой отчет?)."
            print(error_msg)
            # Возвращаем пустой список данных, сырые данные и ошибку парсинга
            return [], report_data_raw, error_msg 
        except csv.Error as e_header_csv:
             error_msg = f"Ошибка CSV при чтении заголовков: {e_header_csv}"
             print(error_msg)
             return [], report_data_raw, error_msg

        # Остальные строки - данные
        rows_processed = 0
        for row in tsv_reader:
            rows_processed += 1
            if not row: # Пропускаем пустые строки (на всякий случай)
                continue
                
            # Строку итогов проверять не нужно, так как включен skipReportSummary
            
            row_dict = {}
            for i, header in enumerate(headers_list):
                if i < len(row):
                    value = row[i]
                    if value == '--':
                        row_dict[header] = 0.0
                    else:
                        try:
                            row_dict[header] = float(value)
                        except ValueError:
                            try:
                                row_dict[header] = int(value)
                            except ValueError:
                                row_dict[header] = value
                else:
                    row_dict[header] = None
            parsed_data.append(row_dict)

        print(f"Парсинг завершен. Прочитано строк данных: {rows_processed}. Сохранено строк данных: {len(parsed_data)}.")
        # Успех: возвращаем распарсенные данные, сырые данные, None (нет ошибки)
        return parsed_data, report_data_raw, None 

    except csv.Error as e_csv:
        parsing_error_msg = f"Ошибка CSV парсинга данных: {e_csv}"
        print(parsing_error_msg)
        # Возвращаем None (т.к. данные некорректны), сырые данные и ошибку
        return None, report_data_raw, parsing_error_msg 
    except Exception as e:
        parsing_error_msg = f"Непредвиденная ошибка при парсинге отчета: {e}"
        print(parsing_error_msg)
        # Возвращаем None, сырые данные и ошибку
        return None, report_data_raw, parsing_error_msg 