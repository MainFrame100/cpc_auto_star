from flask import render_template, redirect, url_for, session
from flask_login import current_user
from . import main_bp

@main_bp.route('/')
def index():
    """Главная страница приложения."""
    # Проверяем аутентификацию через Flask-Login
    if current_user.is_authenticated:
        print(f"[main.index] User {current_user.yandex_login} is authenticated. Redirecting to reports.")
        # current_user здесь - это объект Token, загруженный user_loader'ом
        return redirect(url_for('reports.campaigns'))
    else:
        print("[main.index] User is not authenticated. Redirecting to login.")
        # Если нет, показываем страницу входа (из auth blueprint)
        return redirect(url_for('auth.index'))

# Можно добавить другие общие маршруты сюда, если нужно 