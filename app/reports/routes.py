import requests
import json
from flask import redirect, url_for, session
from markupsafe import escape

from . import reports_bp
from app.auth.utils import get_valid_token
from app.auth.routes import DIRECT_API_SANDBOX_URL
from .utils import fetch_placement_report

@reports_bp.route('/campaigns')
def campaigns():
    """Отображает список кампаний пользователя."""
    client_login = session.get('yandex_client_login')
    if not client_login:
        return redirect(url_for('auth.index', message="Пожалуйста, войдите для просмотра кампаний."))

    access_token = get_valid_token(client_login)
    if not access_token:
        return redirect(url_for('auth.index', message="Ошибка токена. Пожалуйста, войдите снова."))

    # --- Запрос к API для получения списка кампаний --- 
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Login": client_login,
        "Accept-Language": "ru",
        # "Use-Operator-Units": "true" # Для отладки баллов API
    }
    campaigns_url = f"{DIRECT_API_SANDBOX_URL}campaigns"
    payload = json.dumps({
        "method": "get",
        "params": {
            "SelectionCriteria": {}, # Пустой фильтр = все кампании
            "FieldNames": ["Id", "Name", "State", "Status", "Type"] # Запрашиваемые поля
        }
    })

    campaign_list = []
    error_message = None

    try:
        result = requests.post(campaigns_url, headers=headers, data=payload)
        # print(f"Units: {result.headers.get('Units')}") # Отладка баллов
        result.raise_for_status()
        data = result.json()

        if "error" in data:
            error = data['error']
            error_message = f"Ошибка API при получении кампаний: Код {error.get('error_code', 'N/A')}, {error.get('error_string', 'N/A')}: {error.get('error_detail', 'N/A')}"
            print(error_message)
        elif data.get('result') and 'Campaigns' in data['result']:
            campaign_list = sorted(data['result']['Campaigns'], key=lambda c: c.get('Name', '')) # Сортируем по имени
            print(f"Получено {len(campaign_list)} кампаний для {client_login}")
        else:
            error_message = "Неожиданный формат ответа API при получении кампаний."
            print(error_message, data)

    except requests.exceptions.RequestException as e:
        error_message = f"Сетевая ошибка при запросе кампаний: {e}"
        print(error_message)
    except json.JSONDecodeError as e:
        error_message = f"Ошибка декодирования JSON при запросе кампаний: {e}"
        print(error_message)
        print("Raw response:", result.text if 'result' in locals() else "No response")
    except Exception as e:
        error_message = f"Непредвиденная ошибка при запросе кампаний: {e}"
        print(error_message)

    # --- Генерация HTML --- 
    html_body = f"<h1>Список Кампаний для {escape(client_login)}</h1>"
    html_body += f"<p><a href=\"{url_for('auth.index')}\">На главную</a></p>"

    if error_message:
        html_body += f'<p style="color:red;">{escape(error_message)}</p>'

    if campaign_list:
        html_body += "<ul>"
        for campaign in campaign_list:
            campaign_id = campaign.get('Id')
            campaign_name = campaign.get('Name', 'Без имени')
            campaign_state = campaign.get('State', 'N/A')
            campaign_status = campaign.get('Status', 'N/A')
            campaign_type = campaign.get('Type', 'N/A')
            
            # Генерируем ссылку на будущий роут отчета по площадкам
            # Эндпоинт 'reports.platforms_report' будет создан позже
            try:
                platforms_link = url_for('reports.platforms_report', campaign_id=campaign_id)
                link_html = f'<a href="{platforms_link}">Отчет по площадкам</a>'
            except Exception as e_url:
                # Обработка на случай, если эндпоинт еще не определен (хотя он должен быть в этом же блюпринте)
                print(f"Ошибка генерации URL для platforms_report (campaign_id={campaign_id}): {e_url}")
                link_html = "(Не удалось создать ссылку на отчет)"

            html_body += (
                f"<li>"
                f"<b>{escape(campaign_name)}</b> (ID: {campaign_id}) - {escape(campaign_state)} / {escape(campaign_status)} ({escape(campaign_type)}) | "
                f"{link_html}"
                f"</li>"
            )
        html_body += "</ul>"
    elif not error_message:
        html_body += "<p>Кампании не найдены.</p>"

    return html_body 

@reports_bp.route('/campaign/<int:campaign_id>/platforms')
def platforms_report(campaign_id):
    """Отображает отчет по площадкам для указанной кампании."""
    client_login = session.get('yandex_client_login')
    if not client_login:
        return redirect(url_for('auth.index', message="Пожалуйста, войдите для просмотра отчета."))

    access_token = get_valid_token(client_login)
    if not access_token:
        return redirect(url_for('auth.index', message="Ошибка токена. Пожалуйста, войдите снова."))

    print(f"Запрос отчета по площадкам для campaign_id={campaign_id}")
    # Получаем теперь 3 значения
    report_data_parsed, report_data_raw, error_message = fetch_placement_report(access_token, client_login, campaign_id)

    # --- Генерация HTML --- 
    html_body = f"<h1>Отчет по площадкам для кампании {campaign_id}</h1>"
    html_body += f"<p><a href=\"{url_for('reports.campaigns')}\">Назад к списку кампаний</a> | <a href=\"{url_for('auth.index')}\">На главную</a></p>"

    if error_message:
        html_body += f'<p style="color:red;"><b>Ошибка при получении/обработке отчета:</b> {escape(error_message)}</p>'
    
    # Отображаем распарсенную таблицу, если она есть
    if report_data_parsed:
        html_body += "<h3>Результаты отчета:</h3>"
        html_body += "<table border='1' style='border-collapse: collapse; width: 80%;'>"
        html_body += "<thead><tr>"
        
        # Словарь для перевода заголовков
        COLUMN_NAMES_RU = {
            'Placement': 'Площадка',
            'Impressions': 'Показы',
            'Clicks': 'Клики',
            'Cost': 'Расход (руб.)',
            'BounceRate': 'Отказы (%)'
            # Добавить переводы для других полей, если они будут добавляться
        }

        # Генерируем заголовки таблицы из ключей первого словаря (если данные есть)
        headers_in_order = [] # Сохраним порядок ключей
        if report_data_parsed:
            headers_in_order = list(report_data_parsed[0].keys())
            for header_key in headers_in_order:
                # Берем русское название из словаря, или оставляем ключ если перевода нет
                header_ru = COLUMN_NAMES_RU.get(header_key, header_key)
                html_body += f"<th>{escape(header_ru)}</th>"
        html_body += "</tr></thead>"
        
        html_body += "<tbody>"
        for row_dict in report_data_parsed:
            html_body += "<tr>"
            # Используем сохраненный порядок заголовков (headers_in_order)
            for header_key in headers_in_order: 
                value = row_dict.get(header_key, 'N/A')
                # Форматируем числа для лучшей читаемости
                if isinstance(value, float):
                    # Расход форматируем как валюту, отказы - как проценты
                    if header_key == 'Cost':
                         value_str = f"{value:.2f}" # 2 знака после запятой
                    elif header_key == 'BounceRate':
                         value_str = f"{value:.2f}%" # Добавляем знак процента
                    else:
                         value_str = f"{value:.2f}"
                elif header_key == 'Placement' and not value:
                    value_str = "(Не указана)"
                else:
                    value_str = str(value) # Остальное как строка
                # Выравнивание числовых столбцов по правому краю для лучшей читаемости
                td_style = "style='text-align: right;'" if header_key not in ['Placement'] else ""
                html_body += f"<td {td_style}>{escape(value_str)}</td>"
            html_body += "</tr>"
        html_body += "</tbody>"
        html_body += "</table>"
    elif not error_message: # Если нет ошибки и нет распарсенных данных
        html_body += "<p>Нет данных по площадкам для этой кампании за выбранный период (после парсинга).</p>"

    return html_body 