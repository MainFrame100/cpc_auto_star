from app import create_app, db
# Импортируем все модели, чтобы SQLAlchemy их "увидел"
from app.models import Token, WeeklyCampaignStat, WeeklyPlacementStat, WeeklySearchQueryStat, WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat

app = create_app()

# Создаем таблицы в БД, если они еще не существуют
# Это нужно делать в контексте приложения
with app.app_context():
    print("Creating database tables if they don't exist...")
    db.create_all()
    print("Database tables checked/created.")

if __name__ == '__main__':
    # Запускаем сервер разработки Flask
    # debug=True включает автоматическую перезагрузку при изменениях кода
    # и подробные сообщения об ошибках в браузере.
    # ВНИМАНИЕ: Никогда не используйте debug=True в продакшене!
    app.run(debug=True) 