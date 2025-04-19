import requests
import json
import time
import io
import csv
from datetime import date, timedelta

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
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Client-Login': client_login,
        'Accept-Language': 'ru',
        'Content-Type': 'application/json',
        'returnMoneyInMicros': 'false', # Получать денежные значения в валюте клиента
        # 'skipReportHeader': 'true', # Можно раскомментировать, чтобы пропустить шапку
        # 'skipReportSummary': 'true' # Можно раскомментировать, чтобы пропустить итоги
    }

    # Определяем диапазон дат (например, последние 14 дней)
    date2 = date.today()
    date1 = date2 - timedelta(days=14)

    # Формируем тело запроса (ReportDefinition)
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
            'ReportName': f'Custom Placement Report for Campaign {campaign_id} - Last 30 days',
            'ReportType': 'CUSTOM_REPORT',
            'DateRangeType': 'LAST_30_DAYS',
            'Format': 'TSV',
            'IncludeVAT': 'YES',
            'IncludeDiscount': 'NO',
            # Potentially add Page/Limit later if needed, but API might handle defaults
            # 'Page': { 'Limit': 10000 } # Example
        }
    }

    try:
        print("Отправка запроса на заказ отчета...")
        # Используем параметр json вместо data, requests сам сделает dumps и поставит Content-Type
        response = requests.post(REPORTS_API_SANDBOX_URL, headers=headers, json=report_definition)
        
        # Проверяем статус ответа СРАЗУ
        # Успешные статусы для постановки в очередь: 201, 202. 
        # Статус 200 здесь маловероятен, но допустим.
        if response.status_code in [200, 201, 202]:
             print(f"Запрос на отчет успешно отправлен или уже обрабатывается. Статус: {response.status_code}")
        else:
            # Если статус другой, это ошибка - пытаемся обработать ее как HTTPError
            response.raise_for_status() 

    # Ловим конкретно HTTP ошибки (4xx, 5xx)
    except requests.exceptions.HTTPError as e_http:
        error_msg = f"Ошибка HTTP при заказе отчета: {e_http}. "
        try:
            # Пытаемся получить JSON с деталями ошибки
            error_details = response.json().get('error')
            if error_details:
                 error_msg += f"API Error: Код {error_details.get('error_code', 'N/A')}, {error_details.get('error_string', 'N/A')}: {error_details.get('error_detail', 'N/A')}"
            else:
                error_msg += f"Тело ответа: {response.text}" # Если JSON не содержит 'error'
        except json.JSONDecodeError:
             error_msg += f"Не удалось разобрать JSON из тела ответа: {response.text}" # Если ответ не JSON
        except Exception as e_json:
            error_msg += f"Ошибка при обработке JSON из тела ответа: {e_json}. Тело: {response.text}"
        print(error_msg)
        return None, None, error_msg # Возвращаем (None, None, ошибка)

    except requests.exceptions.RequestException as e:
        # Ловим остальные сетевые ошибки (timeout, connection error и т.д.)
        error_msg = f"Сетевая ошибка при заказе отчета (не HTTP): {e}"
        print(error_msg)
        return None, None, error_msg
    except Exception as e:
        # Ловим совсем непредвиденные ошибки
        error_msg = f"Непредвиденная ошибка при заказе отчета: {e}"
        print(error_msg)
        return None, None, error_msg

    # --- 2. Ожидание готовности отчета --- 
    report_data_raw = None
    for i in range(MAX_RETRIES):
        try:
            print(f"Попытка {i + 1}/{MAX_RETRIES}: Проверка статуса отчета...")
            # Повторно отправляем тот же запрос
            response = requests.post(REPORTS_API_SANDBOX_URL, headers=headers, data=json.dumps(report_definition))

            # Код 200: Отчет готов и содержится в теле ответа
            if response.status_code == 200:
                print("Отчет готов!")
                report_data_raw = response.text # Получаем сырой текст отчета
                break # Выходим из цикла ожидания
            
            # Код 201/202: Отчет еще формируется, ждем
            elif response.status_code in [201, 202]:
                print(f"Отчет еще не готов (статус {response.status_code}). Ожидание {RETRY_DELAY_SECONDS} сек...")
                time.sleep(RETRY_DELAY_SECONDS)
                continue # Переходим к следующей попытке
            
            # Другие коды состояния HTTP = ошибка
            else:
                response.raise_for_status() # Вызовет HTTPError для обработки ниже

        except requests.exceptions.HTTPError as e_http:
            # Пытаемся извлечь ошибку API Директа из тела ответа
            try:
                error_details = response.json().get('error')
                if error_details:
                     error_msg = f"Ошибка API при проверке статуса отчета: Код {error_details.get('error_code', 'N/A')}, {error_details.get('error_string', 'N/A')}: {error_details.get('error_detail', 'N/A')}"
                else:
                    error_msg = f"Ошибка HTTP {response.status_code} при проверке статуса отчета. Тело ответа: {response.text}"
            except json.JSONDecodeError:
                error_msg = f"Ошибка HTTP {response.status_code} при проверке статуса отчета. Не удалось разобрать тело ответа: {response.text}"
            
            print(error_msg)
            return None, None, error_msg
        
        except requests.exceptions.RequestException as e:
            error_msg = f"Сетевая ошибка при проверке статуса отчета: {e}"
            print(error_msg)
            # Возможно, стоит продолжить попытки при временных сетевых сбоях
            # Но для простоты пока выходим
            return None, None, error_msg
        except Exception as e:
            error_msg = f"Непредвиденная ошибка при ожидании отчета: {e}"
            print(error_msg)
            return None, None, error_msg

    if report_data_raw is None:
        error_msg = f"Отчет не был готов после {MAX_RETRIES} попыток."
        print(error_msg)
        return None, None, error_msg

    # --- 3. Парсинг отчета (TSV) --- 
    parsed_data = None
    parsing_error_msg = None
    try:
        print("Парсинг TSV данных...")
        report_file = io.StringIO(report_data_raw)
        
        # --- Улучшенное определение заголовков --- 
        headers_list = []
        lines_to_skip = 0
        expected_headers = report_definition['params']['FieldNames']

        # Читаем первые несколько строк, чтобы найти заголовки
        line1_raw = report_file.readline().strip()
        line2_raw = report_file.readline().strip()
        
        print(f"Line 1 raw: {line1_raw}")
        print(f"Line 2 raw: {line2_raw}")

        # Пытаемся распарсить вторую строку как TSV
        try:
            line2_reader = csv.reader([line2_raw], delimiter='\t')
            potential_headers = next(line2_reader)
            # Проверяем, содержит ли вторая строка ожидаемые заголовки
            if all(header in potential_headers for header in expected_headers):
                print("Обнаружены заголовки во второй строке.")
                headers_list = potential_headers
                lines_to_skip = 2 # Пропустили 2 строки (титул + заголовки)
            else:
                 print("Вторая строка не похожа на заголовки. Попробуем первую.")
                 # Если вторая не подошла, пробуем первую
                 line1_reader = csv.reader([line1_raw], delimiter='\t')
                 potential_headers_1 = next(line1_reader)
                 if all(header in potential_headers_1 for header in expected_headers):
                     print("Обнаружены заголовки в первой строке.")
                     headers_list = potential_headers_1
                     lines_to_skip = 1 # Пропустили только строку заголовков
                     # Нужно "вернуть" вторую строку для чтения как данные
                     report_file = io.StringIO(line2_raw + '\n' + report_file.read())
                 else:
                     print("Не удалось найти строку заголовков в первых двух строках.")
                     # Можно либо вызвать ошибку, либо попробовать использовать expected_headers
                     # error_msg = "Не найдена строка заголовков в отчете."
                     # print(error_msg)
                     # return None, error_msg
                     print("Предупреждение: Используем ожидаемые заголовки FieldNames.")
                     headers_list = expected_headers
                     # Пытаемся определить, сколько строк пропустить
                     if report_definition['params']['ReportName'] in line1_raw:
                         lines_to_skip = 2 # Пропускаем титул и предполагаемые данные
                         report_file = io.StringIO(report_file.read()) # Начать читать с 3й строки
                     else:
                         lines_to_skip = 0 # Ничего не пропускаем, читаем всё с начала
                         report_file = io.StringIO(report_data_raw) # Начать читать с начала
        except Exception as e_header:
            error_msg = f"Ошибка при определении заголовков: {e_header}"
            print(error_msg)
            return None, None, error_msg

        # Если строки пропускались, создаем новый reader с правильной позиции
        # (Если lines_to_skip = 1 или 2, report_file уже был пересоздан выше)
        if lines_to_skip == 0:
             tsv_reader = csv.reader(report_file, delimiter='\t')
        elif lines_to_skip == 1:
             # Пропускаем заголовки (которые были первой строкой)
             # report_file уже содержит line2 + остаток
             tsv_reader = csv.reader(report_file, delimiter='\t')
        elif lines_to_skip == 2:
             # Пропускаем 2 строки (титул+заголовки)
             # report_file уже содержит остаток начиная с 3й строки
             tsv_reader = csv.reader(report_file, delimiter='\t')
        # Если заголовки не были найдены, но мы решили продолжить
        elif not headers_list: # На случай, если логика выше изменится и headers_list будет пуст
             error_msg = "Критическая ошибка: не удалось определить заголовки для парсинга."
             print(error_msg)
             return None, None, error_msg
             
        print(f"Используемые заголовки: {headers_list}")
        print(f"Пропущено строк перед данными: {lines_to_skip}")
        
        # Читаем остальные строки с данными
        parsed_data = []
        rows_processed = 0
        for row in tsv_reader:
            rows_processed += 1
            # ИСПРАВЛЕНИЕ: Пропускаем только полностью пустые строки
            if not row: 
                continue
            # Пропускаем строку итогов (проверка остается)
            # Используем безопасный доступ к первому элементу на случай коротких строк
            first_cell = row[0].strip().lower() if len(row) > 0 else ""
            if first_cell.startswith('total') or first_cell.startswith('итого'):
                print(f"Пропущена строка итогов: {row}")
                continue
                
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

        print(f"Парсинг завершен. Обработано строк ридером: {rows_processed}. Сохранено строк данных: {len(parsed_data)}.")
        return parsed_data, report_data_raw, None # Успех!

    except csv.Error as e_csv:
        parsing_error_msg = f"Ошибка CSV парсинга: {e_csv}"
        print(parsing_error_msg)
        return None, None, parsing_error_msg
    except Exception as e:
        parsing_error_msg = f"Непредвиденная ошибка при парсинге отчета: {e}"
        print(parsing_error_msg)
        return None, None, parsing_error_msg 