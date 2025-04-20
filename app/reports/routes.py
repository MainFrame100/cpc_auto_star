import requests
import json
from flask import redirect, url_for, session, flash, render_template, request
from markupsafe import escape
import traceback
from datetime import datetime, timedelta

from . import reports_bp
from app.auth.utils import get_valid_token
from app.auth.routes import DIRECT_API_SANDBOX_URL
from .utils import (
    fetch_report, FIELDS_PLACEMENT, get_monday_and_sunday, get_week_start_dates,
    collect_weekly_stats_for_last_n_weeks
)
from app import db
from app.models import (
    Token, WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat, 
    WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat
)
from sqlalchemy import func

ROWS_PER_PAGE = 25 # Количество строк на странице для пагинации

@reports_bp.route('/campaigns')
def campaigns():
    """Отображает список кампаний пользователя."""
    client_login = session.get('yandex_client_login')
    if not client_login:
        flash("Пожалуйста, войдите для просмотра кампаний.", "warning")
        return redirect(url_for('auth.index'))

    access_token = get_valid_token(client_login)
    if not access_token:
        flash("Ошибка токена. Пожалуйста, войдите снова.", "danger")
        return redirect(url_for('auth.index'))

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

    # Вычисляем время "последнего обновления" (пока просто текущее время - 3 часа)
    try:
        # Используем UTC, так как now() в Jinja обычно UTC
        last_update_time = datetime.utcnow() - timedelta(hours=3) 
        last_update_time_str = last_update_time.strftime('%d.%m.%Y %H:%M')
    except Exception:
        last_update_time_str = "Ошибка времени"

    # Рендерим шаблон вместо генерации HTML
    return render_template(
        'reports/campaign_list.html', 
        campaigns=campaign_list, 
        client_login=client_login,
        error_message=error_message,
        last_update_time_str=last_update_time_str # Передаем строку в шаблон
    )

@reports_bp.route('/campaign/<int:campaign_id>/platforms')
def platforms_report(campaign_id):
    """Отображает отчет по площадкам для указанной кампании (ЗАГЛУШКА)."""
    client_login = session.get('yandex_client_login')
    if not client_login:
        flash("Пожалуйста, войдите для просмотра отчета.", "warning")
        return redirect(url_for('auth.index'))

    # Токен пока не нужен для заглушки, но оставим проверку
    access_token = get_valid_token(client_login)
    if not access_token:
        flash("Ошибка токена. Пожалуйста, войдите снова.", "danger")
        return redirect(url_for('auth.index'))

    print(f"Запрос страницы отчета по площадкам (заглушка) для campaign_id={campaign_id}")

    # --- ВРЕМЕННАЯ ЗАГЛУШКА --- 
    # В этой версии мы не запрашиваем отчет, а просто рендерим шаблон-заглушку.
    # Логика запроса отчета удалена.
    error_message = None # Можно передать сообщение об ошибке, если оно возникло где-то раньше
    
    return render_template(
        'reports/platforms_report_stub.html',
        campaign_id=campaign_id,
        error_message=error_message 
    )
    # --- КОНЕЦ ВРЕМЕННОЙ ЗАГЛУШКИ ---

# --- Роут для просмотра детальной статистики кампании --- 

@reports_bp.route('/campaign/<int:campaign_id>/view')
# TODO: Добавить @login_required
def view_campaign_detail(campaign_id):
    """Отображает детальную статистику по кампании из локальной БД."""
    client_login = session.get('yandex_client_login')
    if not client_login:
        flash("Пожалуйста, войдите для просмотра деталей кампании.", "warning")
        return redirect(url_for('auth.index'))

    print(f"Запрос страницы деталей для campaign_id={campaign_id}, user={client_login}")

    # Получаем номер страницы из GET-параметра, по умолчанию 1
    page = request.args.get('page', 1, type=int)

    error_message = None
    campaign_name = f"Кампания {campaign_id}" # Имя пока не получаем
    # Убираем еженедельную группировку, теперь данные агрегируются за весь период
    # weekly_data = {} # { week_start_date: {'placement': [], 'query': [], ...} }
    aggregated_stats = {}
    placements_pagination = None # Для пагинации площадок
    queries_pagination = None # Для пагинации запросов
    geo_stats = []
    device_stats = []
    demographic_stats = []
    
    weeks_count = 4 
    first_week_start = None
    last_week_end = None
    week_start_dates = [] # Сохраним список дат для заголовка

    try:
        # 1. Определить даты последних 4 недель (оставляем для заголовка)
        week_start_dates = get_week_start_dates(weeks_count)
        if not week_start_dates:
            raise ValueError("Не удалось определить даты недель для отчета.")
        
        first_week_start = week_start_dates[0]
        _, last_week_end = get_monday_and_sunday(week_start_dates[-1])
        
        # Убрали инициализацию weekly_data

        print(f"  Загрузка агрегированных данных из БД за {weeks_count} нед: {week_start_dates}")

        # 2. Запросы к локальной БД 
        
        # Сводная статистика за весь период (оставляем)
        agg_result = db.session.query(
            func.sum(WeeklyCampaignStat.impressions).label('total_impressions'),
            func.sum(WeeklyCampaignStat.clicks).label('total_clicks'),
            func.sum(WeeklyCampaignStat.cost).label('total_cost')
        ).filter(
            WeeklyCampaignStat.yandex_login == client_login,
            WeeklyCampaignStat.campaign_id == campaign_id,
            WeeklyCampaignStat.week_start_date.in_(week_start_dates)
        ).first()
        if agg_result:
            aggregated_stats = {
                'total_impressions': agg_result.total_impressions or 0,
                'total_clicks': agg_result.total_clicks or 0,
                'total_cost': agg_result.total_cost or 0.0
            }

        # --- Загружаем данные по срезам за весь период --- 
        
        # Площадки - с пагинацией
        placements_pagination = db.session.query(WeeklyPlacementStat).filter(
            WeeklyPlacementStat.yandex_login == client_login,
            WeeklyPlacementStat.campaign_id == campaign_id,
            WeeklyPlacementStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyPlacementStat.cost.desc()).paginate(page=page, per_page=ROWS_PER_PAGE, error_out=False)

        # Запросы - с пагинацией
        queries_pagination = db.session.query(WeeklySearchQueryStat).filter(
            WeeklySearchQueryStat.yandex_login == client_login,
            WeeklySearchQueryStat.campaign_id == campaign_id,
            WeeklySearchQueryStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklySearchQueryStat.cost.desc()).paginate(page=page, per_page=ROWS_PER_PAGE, error_out=False)

        # Гео - без пагинации (обычно немного данных)
        geo_stats = db.session.query(WeeklyGeoStat).filter(
            WeeklyGeoStat.yandex_login == client_login,
            WeeklyGeoStat.campaign_id == campaign_id,
            WeeklyGeoStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyGeoStat.cost.desc()).all()

        # Устройства - без пагинации
        device_stats = db.session.query(WeeklyDeviceStat).filter(
            WeeklyDeviceStat.yandex_login == client_login,
            WeeklyDeviceStat.campaign_id == campaign_id,
            WeeklyDeviceStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyDeviceStat.cost.desc()).all()

        # Демография - без пагинации
        demographic_stats = db.session.query(WeeklyDemographicStat).filter(
            WeeklyDemographicStat.yandex_login == client_login,
            WeeklyDemographicStat.campaign_id == campaign_id,
            WeeklyDemographicStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyDemographicStat.cost.desc()).all()
        
        # Убрали распределение по неделям
        print(f"  Данные загружены.")

    except Exception as e_fetch:
        error_message = f"Ошибка при загрузке данных из локальной БД: {e_fetch}"
        print(f"  {error_message}")
        traceback.print_exc()

    # Рендерим шаблон с новыми данными
    return render_template(
        'reports/campaign_detail.html',
        campaign_id=campaign_id,
        campaign_name=campaign_name, 
        aggregated_stats=aggregated_stats,
        placements_pagination=placements_pagination, # Передаем пагинацию площадок
        queries_pagination=queries_pagination,       # Передаем пагинацию запросов
        geo_stats=geo_stats,                         # Остальные данные передаем как списки
        device_stats=device_stats,
        demographic_stats=demographic_stats,
        error_message=error_message,
        weeks_count=weeks_count,                     # Для заголовка
        first_week_start=first_week_start,
        last_week_end=last_week_end,
        current_page=page                            # Передаем текущую страницу для пагинации
    )

# --- Роуты для загрузки/обновления данных --- 

@reports_bp.route('/load_initial_data', methods=['POST'])
# TODO: В будущем добавить декоратор @login_required, если будет Flask-Login
def load_initial_data():
    """Запускает первоначальный сбор статистики за последние N недель (для теста N=1)."""
    client_login = session.get('yandex_client_login')
    if not client_login:
        flash("Пожалуйста, войдите в систему для запуска сбора данных.", "warning")
        return redirect(url_for('auth.index'))
    
    print(f"Запуск load_initial_data для пользователя {client_login}...")
    # Вызываем основную функцию сбора, ДЛЯ ТЕСТА ставим n_weeks=1
    success, message = collect_weekly_stats_for_last_n_weeks(yandex_login=client_login, n_weeks=1)
    
    if success:
        flash(f"Сбор данных запущен/завершен: {message}", "success")
    else:
        flash(f"Ошибка при сборе данных: {message}", "danger")
        
    # Перенаправляем обратно на страницу кампаний (пока что)
    # TODO: Возможно, лучше перенаправлять на отдельную страницу статуса или дашборд
    return redirect(url_for('.campaigns')) # '.' означает текущий блюпринт

@reports_bp.route('/update_data', methods=['POST'])
# TODO: В будущем добавить декоратор @login_required
def update_data():
    """Запускает обновление статистики за последние N недель (для теста N=1)."""
    client_login = session.get('yandex_client_login')
    if not client_login:
        flash("Пожалуйста, войдите в систему для запуска обновления данных.", "warning")
        return redirect(url_for('auth.index'))
        
    print(f"Запуск update_data для пользователя {client_login}...")
    # Для MVP обновление делает то же самое, ДЛЯ ТЕСТА ставим n_weeks=1
    success, message = collect_weekly_stats_for_last_n_weeks(yandex_login=client_login, n_weeks=1)
    
    if success:
        flash(f"Обновление данных запущено/завершено: {message}", "success")
    else:
        flash(f"Ошибка при обновлении данных: {message}", "danger")
        
    return redirect(url_for('.campaigns'))