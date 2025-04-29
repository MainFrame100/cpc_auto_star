from app import create_app, db
# Импортируем модели, чтобы Flask-Migrate их видел, но их не обязательно импортировать все здесь
# Достаточно, чтобы они были импортированы где-то, когда create_app() вызывается.
# Например, они импортируются в app/__init__.py через user_loader или внутри blueprints.
# from app.models import User, Client, YandexAccount, Token, WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat, WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat

app = create_app()

# УДАЛЕНО: db.create_all() - Управляется через Flask-Migrate
# with app.app_context():
#     print("Creating database tables if they don't exist...")
#     db.create_all()
#     print("Database tables checked/created.")

if __name__ == '__main__':
    # host='0.0.0.0' делает сервер доступным извне контейнера
    # debug=True - для разработки, автоперезагрузка и отладчик
    app.run(host='0.0.0.0', debug=True) # Используем переменные окружения для порта и отладки позже 