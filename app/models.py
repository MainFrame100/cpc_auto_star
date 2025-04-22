from datetime import datetime, timedelta
from app import db
from flask_login import UserMixin
from sqlalchemy import Date, Integer, String, Float, Index, UniqueConstraint, ForeignKey

# Определение модели данных для токенов
class Token(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True) # Первичный ключ
    yandex_login = db.Column(db.String(80), unique=True, nullable=False) # Логин Яндекса, уникальный
    access_token = db.Column(db.String(200), nullable=False) # Токен доступа
    refresh_token = db.Column(db.String(200), nullable=True) # Токен обновления (может отсутствовать)
    expires_at = db.Column(db.DateTime, nullable=False) # Время истечения access_token

    # --- Flask-Login required methods ---
    def get_id(self):
        """Возвращает ID для Flask-Login (используем yandex_login)."""
        return str(self.yandex_login) # Flask-Login ожидает строку

    # UserMixin предоставляет is_authenticated, is_active, is_anonymous
    # is_active по умолчанию True, что нам подходит
    # is_authenticated вернет True, если пользователь вошел (через login_user)
    # is_anonymous вернет True, если пользователь не вошел
    # -----------------------------------

    def __repr__(self):
        # Удобное представление объекта для отладки
        return f'<Token for {self.yandex_login}>'

# Модели для хранения еженедельной статистики
# -----------------------------------------

class WeeklyCampaignStat(db.Model):
    __tablename__ = 'weekly_campaign_stat'
    week_start_date = db.Column(Date, primary_key=True, index=True) # Дата начала недели (понедельник)
    campaign_id = db.Column(Integer, primary_key=True, index=True) # ID кампании
    yandex_login = db.Column(String(80), ForeignKey('token.yandex_login'), nullable=False, index=True) # Связь с пользователем
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float) # Расход в у.е. Директа (обычно без НДС)

    __table_args__ = (UniqueConstraint('week_start_date', 'campaign_id', name='_week_campaign_uc'),)
    # Добавляем индекс для ускорения выборок по пользователю и дате
    Index('idx_campaign_user_week', 'yandex_login', 'week_start_date')

    def __repr__(self):
        return f'<WeeklyCampaignStat {self.yandex_login} C:{self.campaign_id} W:{self.week_start_date}>'


class WeeklyPlacementStat(db.Model):
    __tablename__ = 'weekly_placement_stat'
    id = db.Column(Integer, primary_key=True) # Автоинкрементный ID для простоты
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    yandex_login = db.Column(String(80), ForeignKey('token.yandex_login'), nullable=False, index=True)
    placement = db.Column(String(512)) # Название площадки
    ad_network_type = db.Column(String(50)) # SEARCH / NETWORK
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)

    # Уникальность записи определяется комбинацией полей
    __table_args__ = (UniqueConstraint('week_start_date', 'campaign_id', 'placement', 'ad_network_type', name='_week_placement_uc'),
                      Index('idx_placement_user_camp_week', 'yandex_login', 'campaign_id', 'week_start_date'))

    def __repr__(self):
        return f'<WeeklyPlacementStat C:{self.campaign_id} P:{self.placement} W:{self.week_start_date}>'

class WeeklySearchQueryStat(db.Model):
    __tablename__ = 'weekly_search_query_stat'
    id = db.Column(Integer, primary_key=True)
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    ad_group_id = db.Column(Integer, nullable=False, index=True) # ID группы объявлений
    yandex_login = db.Column(String(80), ForeignKey('token.yandex_login'), nullable=False, index=True)
    query = db.Column(String(1024)) # Поисковый запрос
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)

    __table_args__ = (UniqueConstraint('week_start_date', 'campaign_id', 'ad_group_id', 'query', name='_week_query_uc'),
                      Index('idx_query_user_camp_week', 'yandex_login', 'campaign_id', 'week_start_date'))

    def __repr__(self):
        return f'<WeeklySearchQueryStat C:{self.campaign_id} Q:{self.query[:30]} W:{self.week_start_date}>'


class WeeklyGeoStat(db.Model):
    __tablename__ = 'weekly_geo_stat'
    id = db.Column(Integer, primary_key=True)
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    location_id = db.Column(Integer, nullable=False, index=True) # ID региона (CriteriaId)
    yandex_login = db.Column(String(80), ForeignKey('token.yandex_login'), nullable=False, index=True)
    # location_name = db.Column(String(255)) # Опционально, если хотим хранить название
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)

    __table_args__ = (UniqueConstraint('week_start_date', 'campaign_id', 'location_id', name='_week_geo_uc'),
                      Index('idx_geo_user_camp_week', 'yandex_login', 'campaign_id', 'week_start_date'))

    def __repr__(self):
        return f'<WeeklyGeoStat C:{self.campaign_id} L:{self.location_id} W:{self.week_start_date}>'


class WeeklyDeviceStat(db.Model):
    __tablename__ = 'weekly_device_stat'
    id = db.Column(Integer, primary_key=True)
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    device_type = db.Column(String(50), nullable=False) # DESKTOP, MOBILE, TABLET
    yandex_login = db.Column(String(80), ForeignKey('token.yandex_login'), nullable=False, index=True)
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)

    __table_args__ = (UniqueConstraint('week_start_date', 'campaign_id', 'device_type', name='_week_device_uc'),
                      Index('idx_device_user_camp_week', 'yandex_login', 'campaign_id', 'week_start_date'))

    def __repr__(self):
        return f'<WeeklyDeviceStat C:{self.campaign_id} D:{self.device_type} W:{self.week_start_date}>'


class WeeklyDemographicStat(db.Model):
    __tablename__ = 'weekly_demographic_stat'
    id = db.Column(Integer, primary_key=True)
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    gender = db.Column(String(20), nullable=False) # GENDER_MALE, GENDER_FEMALE, GENDER_UNKNOWN
    age_group = db.Column(String(20), nullable=False) # AGE_0_17, AGE_18_24, ..., AGE_55, AGE_UNKNOWN
    yandex_login = db.Column(String(80), ForeignKey('token.yandex_login'), nullable=False, index=True)
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)

    __table_args__ = (UniqueConstraint('week_start_date', 'campaign_id', 'gender', 'age_group', name='_week_demographic_uc'),
                      Index('idx_demographic_user_camp_week', 'yandex_login', 'campaign_id', 'week_start_date'))

    def __repr__(self):
        return f'<WeeklyDemographicStat C:{self.campaign_id} G:{self.gender} A:{self.age_group} W:{self.week_start_date}>' 