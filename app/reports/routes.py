import requests
import json
from flask import redirect, url_for, session, flash, render_template, request, Response, current_app
from flask_login import login_required, current_user
from markupsafe import escape
import traceback
from datetime import datetime, timedelta
import io
import csv

from . import reports_bp
from .. import Config
from .utils import (
    fetch_report, FIELDS_PLACEMENT, get_monday_and_sunday, get_week_start_dates,
    update_client_statistics
)
from .. import db
from ..models import (
    User, Client, YandexAccount,
    WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat, 
    WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat
)
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Импортируем наш новый клиент и его исключение
from ..api_clients.yandex_direct import YandexDirectClient, YandexDirectClientError, YandexDirectAuthError

ROWS_PER_PAGE = 25 # Количество строк на странице для пагинации

@reports_bp.route('/campaigns')
@login_required
def campaigns():
    """Отображает список кампаний пользователя, используя YandexDirectClient."""
    user = current_user # Получаем текущего пользователя
    current_app.logger.info(f"[reports.campaigns] User {user.yandex_login} (ID: {user.id}) authenticated. Fetching campaigns.")

    campaign_list = []
    error_message = None
    processed_accounts_count = 0

    try:
        # Находим ВСЕ YandexAccount, связанные с этим пользователем
        # (через его клиентов)
        accounts_to_process = db.session.query(YandexAccount).join(Client).filter(Client.user_id == user.id, YandexAccount.is_active == True).all()
        
        if not accounts_to_process:
             flash("У вас нет подключенных и активных рекламных аккаунтов. Подключите их в настройках.", "info")
             # Можно редиректнуть на страницу добавления аккаунтов или просто показать пустой список
             return render_template('reports/campaign_list.html', campaigns=[], client_login=user.yandex_login, error_message=None, last_update_time_str="N/A")

        current_app.logger.info(f"Found {len(accounts_to_process)} active Yandex accounts for user {user.id}")

        all_campaigns = []
        # Обрабатываем каждый аккаунт
        for account in accounts_to_process:
            current_app.logger.info(f"Processing account ID: {account.id}, Login: {account.login}")
            try:
                # Создаем клиент API для конкретного аккаунта, передавая ID аккаунта и ID пользователя
                api_client = YandexDirectClient(yandex_account_id=account.id, current_user_id=user.id)
                
                # Определяем параметры запроса (можно вынести в константы или настройки)
                selection_criteria = {}
                field_names = [
                    "Id", "Name", "State", "Status", "Type",
                    "StartDate", "EndDate" # Убрали DailyBudget, Funds, Statistics для скорости
                ]

                # Получаем кампании через клиент
                account_campaigns = api_client.get_campaigns(selection_criteria=selection_criteria, field_names=field_names)
                
                # Добавляем информацию об аккаунте к каждой кампании для отображения
                for camp in account_campaigns:
                    camp['yandex_account_login'] = account.login 
                    camp['yandex_account_id'] = account.id
                    all_campaigns.append(camp)
                
                processed_accounts_count += 1
                current_app.logger.info(f"Successfully fetched {len(account_campaigns)} campaigns for account {account.login}")

            except YandexDirectAuthError as e_auth:
                 # Ошибка авторизации для КОНКРЕТНОГО аккаунта
                 error_message = f"Ошибка доступа к аккаунту {account.login}: {e_auth}. Возможно, нужно обновить токен или права доступа."
                 current_app.logger.error(error_message)
                 flash(error_message, 'warning') # Показываем пользователю
                 # Помечаем аккаунт как неактивный?
                 # account.is_active = False
                 # db.session.commit()
                 continue # Продолжаем со следующим аккаунтом
            except YandexDirectClientError as e_api:
                 error_message = f"Ошибка API при получении кампаний для аккаунта {account.login}: {e_api}"
                 current_app.logger.error(error_message)
                 flash(error_message, 'warning')
                 continue # Продолжаем со следующим аккаунтом
            except Exception as e_inner:
                 error_message = f"Непредвиденная ошибка при обработке аккаунта {account.login}: {e_inner}"
                 current_app.logger.exception(error_message) # Логируем с трейсбеком
                 flash(f"Внутренняя ошибка при обработке аккаунта {account.login}.", 'danger')
                 continue # Продолжаем со следующим аккаунтом

        # Сортируем общий список по имени кампании
        campaign_list = sorted(all_campaigns, key=lambda c: c.get('Name', ''))
        current_app.logger.info(f"Total campaigns fetched: {len(campaign_list)} from {processed_accounts_count} accounts.")

    except Exception as e:
        error_message = f"Непредвиденная ошибка при получении списка кампаний: {e}"
        current_app.logger.exception(error_message)
        traceback.print_exc()

    # Вычисляем время "последнего обновления"
    # TODO: Сделать осмысленное время последнего обновления
    try:
        last_update_time = datetime.utcnow() # Пока текущее время
        last_update_time_str = last_update_time.strftime('%d.%m.%Y %H:%M UTC')
    except Exception:
        last_update_time_str = "N/A"

    # Рендерим шаблон
    return render_template(
        'reports/campaign_list.html', 
        campaigns=campaign_list, 
        client_login=user.yandex_login, # Передаем логин основного пользователя
        error_message=error_message, # Передаем последнее сообщение об ошибке (если было)
        last_update_time_str=last_update_time_str
    )

@reports_bp.route('/campaign/<int:campaign_id>/platforms')
@login_required
def platforms_report(campaign_id):
    """Отображает отчет по площадкам для указанной кампании (ЗАГЛУШКА)."""
    current_app.logger.debug(f"Запрос страницы отчета по площадкам (заглушка) для campaign_id={campaign_id}")

    error_message = None
    return render_template(
        'reports/platforms_report_stub.html',
        campaign_id=campaign_id,
        error_message=error_message 
    )

@reports_bp.route('/campaign/<int:campaign_id>/view')
@login_required
def view_campaign_detail(campaign_id):
    """Отображает детальную статистику по кампании из локальной БД."""
    user = current_user
    current_app.logger.info(f"[reports.view_campaign_detail] User {user.yandex_login} viewing campaign {campaign_id}")

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
    weekly_campaign_stats = [] # Добавлено для сводки по неделям
    weekly_summary_data = [] # Инициализируем здесь, вне try
    
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
            WeeklyCampaignStat.user_id == user.id,
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
            WeeklyPlacementStat.user_id == user.id,
            WeeklyPlacementStat.campaign_id == campaign_id,
            WeeklyPlacementStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyPlacementStat.cost.desc()).paginate(page=page, per_page=ROWS_PER_PAGE, error_out=False)

        # Запросы - с пагинацией
        queries_pagination = db.session.query(WeeklySearchQueryStat).filter(
            WeeklySearchQueryStat.user_id == user.id,
            WeeklySearchQueryStat.campaign_id == campaign_id,
            WeeklySearchQueryStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklySearchQueryStat.cost.desc()).paginate(page=page, per_page=ROWS_PER_PAGE, error_out=False)

        # Гео - без пагинации (обычно немного данных)
        geo_stats = db.session.query(WeeklyGeoStat).filter(
            WeeklyGeoStat.user_id == user.id,
            WeeklyGeoStat.campaign_id == campaign_id,
            WeeklyGeoStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyGeoStat.cost.desc()).all()

        # Устройства - без пагинации
        device_stats = db.session.query(WeeklyDeviceStat).filter(
            WeeklyDeviceStat.user_id == user.id,
            WeeklyDeviceStat.campaign_id == campaign_id,
            WeeklyDeviceStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyDeviceStat.cost.desc()).all()

        # Демография - без пагинации
        demographic_stats = db.session.query(WeeklyDemographicStat).filter(
            WeeklyDemographicStat.user_id == user.id,
            WeeklyDemographicStat.campaign_id == campaign_id,
            WeeklyDemographicStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyDemographicStat.cost.desc()).all()
        
        # Добавляем запрос для Сводки по неделям
        weekly_campaign_stats = db.session.query(WeeklyCampaignStat).filter(
            WeeklyCampaignStat.user_id == user.id,
            WeeklyCampaignStat.campaign_id == campaign_id,
            WeeklyCampaignStat.week_start_date.in_(week_start_dates)
        ).order_by(WeeklyCampaignStat.week_start_date).all()
        
        # Преобразуем недельные данные для удобства в шаблоне
        for stat in weekly_campaign_stats:
            _, week_end_date = get_monday_and_sunday(stat.week_start_date)
            weekly_summary_data.append({
                'week_start': stat.week_start_date,
                'week_end': week_end_date,
                'impressions': stat.impressions,
                'clicks': stat.clicks,
                'cost': stat.cost
            })
        
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
        weekly_campaign_stats=weekly_summary_data, # Передаем обработанную еженедельную статистику
        error_message=error_message,
        weeks_count=weeks_count,                     # Для заголовка
        first_week_start=first_week_start,
        last_week_end=last_week_end,
        current_page=page                            # Передаем текущую страницу для пагинации
    )

# --- Роуты для загрузки/обновления данных --- 

@reports_bp.route('/load_initial_data', methods=['POST'])
@login_required
def load_initial_data():
    """Запускает первоначальный сбор статистики за последние N недель (для теста N=1)."""
    user = current_user
    print(f"Запуск load_initial_data для пользователя {user.yandex_login}...") # Заменил logger на print для примера
    try:
        # Вызываем функцию сбора статистики, передавая ID пользователя
        success, message = collect_weekly_stats_for_last_n_weeks(current_user.id, n_weeks=1) # Используем user_id
        if success:
            flash(f"Сбор данных запущен. {message}", 'success')
        else:
            flash(f"Ошибка при сборе данных: {message}", "danger")
    except Exception as e:
        error_message = f"Непредвиденная ошибка при запуске load_initial_data: {e}"
        print(f"  {error_message}")
        traceback.print_exc()
        flash(f"Не удалось запустить сбор данных. {error_message}", "danger")
    
    # Перенаправляем обратно на страницу кампаний (пока что)
    # TODO: Возможно, лучше перенаправлять на отдельную страницу статуса или дашборд
    return redirect(url_for('.campaigns')) # '.' означает текущий блюпринт

@reports_bp.route('/update_data', methods=['POST'])
@login_required
def update_data():
    """Запускает обновление статистики за последние N недель (для теста N=1)."""
    client_login = current_user.yandex_login
    print(f"Запуск update_data для пользователя {client_login}...")
    # Для MVP обновление делает то же самое, ДЛЯ ТЕСТА ставим n_weeks=1
    success, message = collect_weekly_stats_for_last_n_weeks(yandex_login=client_login, n_weeks=1)
    
    if success:
        flash(f"Обновление данных запущено/завершено: {message}", "success")
    else:
        flash(f"Ошибка при обновлении данных: {message}", "danger")
        
    return redirect(url_for('.campaigns'))

# --- Роут для скачивания CSV --- 

@reports_bp.route('/campaign/<int:campaign_id>/download_csv', methods=['POST'])
@login_required
def download_csv(campaign_id):
    """Формирует и отдает CSV файл с выбранными срезами данных за последние 4 недели."""
    client_login = current_user.yandex_login
    if not client_login:
        flash("Пожалуйста, войдите для скачивания отчета.", "warning")
        return redirect(url_for('auth.index'))

    selected_slices = request.form.getlist('selected_slices')
    if not selected_slices:
        flash("Не выбрано ни одного среза для скачивания.", "warning")
        return redirect(url_for('.view_campaign_detail', campaign_id=campaign_id))

    print(f"Запрос на скачивание CSV для campaign_id={campaign_id}, срезы: {selected_slices}")

    try:
        # Определяем период (последние 4 недели)
        weeks_count = 4
        week_start_dates = get_week_start_dates(weeks_count)
        if not week_start_dates:
            raise ValueError("Не удалось определить даты недель для отчета.")
        first_week_start = week_start_dates[0]
        _, last_week_end = get_monday_and_sunday(week_start_dates[-1])
        
        # Используем StringIO для записи CSV в память
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';') # Используем точку с запятой для Excel
        
        writer.writerow([f"Отчет по кампании ID: {campaign_id}"])
        writer.writerow([f"Период: {first_week_start.strftime('%d.%m.%Y')} - {last_week_end.strftime('%d.%m.%Y')} ({weeks_count} нед.)"])
        writer.writerow([f"Срезы: {', '.join(selected_slices)}"])
        writer.writerow([]) # Пустая строка

        # Заголовки и данные для каждого среза
        slice_map = {
            'summary': { # Добавлен срез для сводки по неделям
                'model': WeeklyCampaignStat,
                'title': '--- Сводка по неделям ---',
                'headers': ['Неделя', 'Показы', 'Клики', 'CTR %', 'Расход', 'CPC'],
                'columns': ['week_start_date', 'impressions', 'clicks', None, 'cost', None] 
            },
            'placements': {
                'model': WeeklyPlacementStat,
                'title': '--- Площадки ---',
                'headers': ['Дата начала недели', 'Площадка', 'Тип сети', 'Показы', 'Клики', 'CTR %', 'Расход', 'CPC'],
                'columns': ['week_start_date', 'placement', 'ad_network_type', 'impressions', 'clicks', None, 'cost', None]
            },
            'queries': {
                'model': WeeklySearchQueryStat,
                'title': '--- Поисковые запросы ---',
                'headers': ['Дата начала недели', 'Запрос', 'Показы', 'Клики', 'CTR %', 'Расход', 'CPC'],
                'columns': ['week_start_date', 'query', 'impressions', 'clicks', None, 'cost', None]
            },
            'geo': {
                'model': WeeklyGeoStat,
                'title': '--- География ---',
                'headers': ['Дата начала недели', 'ID Региона', 'Показы', 'Клики', 'CTR %', 'Расход', 'CPC'],
                'columns': ['week_start_date', 'location_id', 'impressions', 'clicks', None, 'cost', None]
            },
            'devices': {
                'model': WeeklyDeviceStat,
                'title': '--- Устройства ---',
                'headers': ['Дата начала недели', 'Тип устройства', 'Показы', 'Клики', 'CTR %', 'Расход', 'CPC'],
                'columns': ['week_start_date', 'device_type', 'impressions', 'clicks', None, 'cost', None]
            },
            'demographics': {
                'model': WeeklyDemographicStat,
                'title': '--- Пол и возраст ---',
                'headers': ['Дата начала недели', 'Пол', 'Возраст', 'Показы', 'Клики', 'CTR %', 'Расход', 'CPC'],
                'columns': ['week_start_date', 'gender', 'age_group', 'impressions', 'clicks', None, 'cost', None]
            }
        }

        for slice_key in selected_slices:
            if slice_key in slice_map:
                details = slice_map[slice_key]
                Model = details['model']
                
                writer.writerow([details['title']])
                writer.writerow(details['headers'])
                
                # Запрашиваем ВСЕ данные за период, без пагинации
                stats_query = db.session.query(Model).filter(
                    Model.user_id == user.id,
                    Model.campaign_id == campaign_id,
                    Model.week_start_date.in_(week_start_dates)
                ).order_by(Model.week_start_date, Model.cost.desc()).all()

                for stat in stats_query:
                    row = []
                    for i, col_name in enumerate(details['columns']):
                        if col_name:
                            value = getattr(stat, col_name)
                            # Форматируем дату
                            if isinstance(value, datetime):
                                # Особая обработка для колонки с датой начала недели
                                if col_name == 'week_start_date':
                                    _, week_end_date = get_monday_and_sunday(value)
                                    value = f"{value.strftime('%d.%m.%Y')} - {week_end_date.strftime('%d.%m.%Y')}"
                                else:
                                    value = value.strftime('%d.%m.%Y')
                            # Заменяем точку на запятую для числовых полей
                            elif isinstance(value, (int, float)):
                                value = str(value).replace('.', ',')
                            row.append(value)
                        else: # Вычисляемые поля CTR и CPC
                            ctr = 0.0
                            if stat.impressions > 0:
                                ctr = (stat.clicks / stat.impressions) * 100
                            
                            cpc = 0.0
                            if stat.clicks > 0:
                                cpc = stat.cost / stat.clicks
                                
                            header_lower = details['headers'][i].lower()
                            if 'ctr' in header_lower:
                                row.append(f"{ctr:.2f}".replace('.', ','))
                            elif 'cpc' in header_lower:
                                row.append(f"{cpc:.2f}".replace('.', ','))
                            else:
                                row.append('') # На всякий случай
                    writer.writerow(row)
                
                writer.writerow([]) # Пустая строка после среза
            else:
                print(f"Предупреждение: Неизвестный срез '{slice_key}' для скачивания.")

        output.seek(0)
        
        # Формируем имя файла
        filename = f"campaign_{campaign_id}_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        # Создаем Response объект
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={ "Content-Disposition": f"attachment;filename={filename}" }
        )

    except Exception as e_csv:
        error_message = f"Ошибка при генерации CSV файла: {e_csv}"
        print(f"  {error_message}")
        traceback.print_exc()
        flash(f"Не удалось сгенерировать CSV файл. {error_message}", "danger")
        return redirect(url_for('.view_campaign_detail', campaign_id=campaign_id))

# --- Роут для общей статистики по клиенту (Заглушка) --- 

@reports_bp.route('/client/<int:client_id>/summary')
@login_required
def client_summary(client_id):
    """Отображает сводную страницу статистики для клиента (ЗАГЛУШКА)."""
    client = Client.query.filter_by(id=client_id, user_id=current_user.id).first_or_404()
    # Пока просто рендерим заглушку
    return render_template('reports/client_summary_stub.html', client=client)

# --- Новый роут для запуска обновления данных клиента ---
@reports_bp.route('/client/<int:client_id>/update_stats', methods=['POST'])
@login_required
def trigger_client_update(client_id):
    """Запускает процесс обновления статистики для конкретного клиента."""
    current_app.logger.info(f"Получен POST запрос на /client/{client_id}/update_stats от пользователя {current_user.id}")
    
    # Проверяем, что клиент принадлежит пользователю (на всякий случай, хотя utils делает это тоже)
    client = Client.query.filter_by(id=client_id, user_id=current_user.id).first()
    if not client:
        flash("Клиент не найден или у вас нет прав на его обновление.", "danger")
        return redirect(url_for('auth.list_clients')) # Редирект на список клиентов
    
    try:
        # Запускаем фоновый процесс? Пока нет, делаем синхронно.
        current_app.logger.info(f"Запуск update_client_statistics для клиента {client.name} (ID: {client_id}) пользователем {current_user.id}")
        success, message = update_client_statistics(client_id, current_user.id)
        
        if success:
            flash(f"Обновление статистики для клиента '{client.name}' завершено. {message}", 'success')
        else:
            flash(f"Ошибка при обновлении статистики для клиента '{client.name}': {message}", 'danger')
            
    except Exception as e:
        current_app.logger.exception(f"Критическая ошибка при вызове update_client_statistics для client_id={client_id}")
        flash(f"Внутренняя ошибка сервера при запуске обновления для клиента '{client.name}'.", 'danger')

    # Возвращаемся на страницу клиентов
    return redirect(url_for('auth.list_clients'))