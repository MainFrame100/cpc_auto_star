from datetime import datetime, timedelta
from app import db, login_manager
from flask_login import UserMixin
from sqlalchemy import (
    Date, Integer, String, Float, DateTime, Boolean, LargeBinary, Text,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from cryptography.fernet import Fernet
import os

# --- Модели для аутентификации и управления доступом ---

class User(db.Model, UserMixin):
    """Модель пользователя сервиса CPC Auto Helper."""
    __tablename__ = 'user'
    id = db.Column(Integer, primary_key=True)
    yandex_login = db.Column(String(80), unique=True, nullable=False, index=True) # Логин основного Я.Аккаунта
    # Доп. поля из OAuth можно добавить здесь (email, name, avatar_id и т.д.)
    # email = db.Column(String(120), unique=True, nullable=True)
    # first_name = db.Column(String(80), nullable=True)
    # last_name = db.Column(String(80), nullable=True)
    created_at = db.Column(DateTime, default=datetime.utcnow)

    # Связи: один User может иметь много Clients
    clients = relationship("Client", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f'<User {self.yandex_login}>'

# Определяем user_loader здесь, так как он работает с моделью User
@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except ValueError:
        return None

class Client(db.Model):
    """Модель "Клиента" (проекта) внутри сервиса."""
    __tablename__ = 'client'
    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(100), nullable=False)
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True) # Связь с User
    created_at = db.Column(DateTime, default=datetime.utcnow)
    # Можно добавить поле для хранения ID целей Метрики (список через запятую или JSON)
    metrika_goals = db.Column(Text, nullable=True)

    # Связи: один Client принадлежит одному User, у одного Client много YandexAccounts
    user = relationship("User", back_populates="clients")
    yandex_accounts = relationship("YandexAccount", back_populates="client", cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Client {self.name} (User ID: {self.user_id})>'


class YandexAccount(db.Model):
    """Модель рекламного аккаунта Яндекс.Директ, подключенного к клиенту."""
    __tablename__ = 'yandex_account'
    id = db.Column(Integer, primary_key=True)
    login = db.Column(String(80), nullable=False, index=True) # Логин рекламного аккаунта Яндекса
    client_id = db.Column(Integer, ForeignKey('client.id'), nullable=False, index=True) # Связь с Client
    is_active = db.Column(Boolean, default=True) # Флаг активности (для временного отключения)
    created_at = db.Column(DateTime, default=datetime.utcnow)

    # Связи: один YandexAccount принадлежит одному Client, у одного YandexAccount один Token
    client = relationship("Client", back_populates="yandex_accounts")
    token = relationship("Token", back_populates="yandex_account", uselist=False, cascade="all, delete-orphan") # uselist=False для one-to-one

    # Уникальность логина в рамках одного клиента
    __table_args__ = (UniqueConstraint('client_id', 'login', name='_client_login_uc'),)

    def __repr__(self):
        return f'<YandexAccount {self.login} (Client ID: {self.client_id})>'


class Token(db.Model):
    """Модель для хранения OAuth токенов рекламного аккаунта YandexAccount."""
    __tablename__ = 'token'
    id = db.Column(Integer, primary_key=True)
    yandex_account_id = db.Column(Integer, ForeignKey('yandex_account.id'), unique=True, nullable=False) # Связь с YandexAccount (one-to-one)
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True) # Связь с User для проверки прав!
    encrypted_access_token = db.Column(LargeBinary, nullable=False) # Шифрованный токен доступа
    encrypted_refresh_token = db.Column(LargeBinary, nullable=True) # Шифрованный токен обновления
    expires_at = db.Column(DateTime, nullable=False) # Время истечения access_token
    updated_at = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связь: один Token принадлежит одному YandexAccount
    yandex_account = relationship("YandexAccount", back_populates="token")

    # Утилиты для шифрования/дешифрования (лучше вынести в utils, но пока здесь для простоты)
    # Ключ должен быть загружен из конфигурации
    @staticmethod
    def _get_cipher():
        key = os.environ.get('ENCRYPTION_KEY')
        if not key:
            raise ValueError("ENCRYPTION_KEY not set in environment variables")
        return Fernet(key.encode())

    @staticmethod
    def encrypt_data(data: str) -> bytes:
        if not data: return None
        cipher = Token._get_cipher()
        return cipher.encrypt(data.encode())

    @staticmethod
    def decrypt_data(encrypted_data: bytes) -> str:
        if not encrypted_data: return None
        cipher = Token._get_cipher()
        return cipher.decrypt(encrypted_data).decode()

    # Свойства для удобного доступа к расшифрованным токенам
    @property
    def access_token(self):
        return Token.decrypt_data(self.encrypted_access_token)

    @property
    def refresh_token(self):
        return Token.decrypt_data(self.encrypted_refresh_token)

    def __repr__(self):
        return f'<Token for YandexAccount ID: {self.yandex_account_id}>'


# --- Модели для хранения еженедельной статистики (Адаптированные) ---

class WeeklyCampaignStat(db.Model):
    __tablename__ = 'weekly_campaign_stat'
    # Составной первичный ключ
    week_start_date = db.Column(Date, primary_key=True, index=True) # Дата начала недели (понедельник)
    campaign_id = db.Column(Integer, primary_key=True, index=True) # ID кампании
    yandex_account_id = db.Column(Integer, ForeignKey('yandex_account.id'), primary_key=True, index=True) # Связь с рекл. аккаунтом

    # Связи для фильтрации и проверки прав
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    client_id = db.Column(Integer, ForeignKey('client.id'), nullable=False, index=True)

    # Статистические данные
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float) # Расход (уточнить с НДС или без)
    conversions = db.Column(Integer, nullable=True) # Сумма конверсий по целевым целям

    # Убираем старый UniqueConstraint, т.к. первичный ключ уже обеспечивает уникальность
    # __table_args__ = (UniqueConstraint('week_start_date', 'campaign_id', name='_week_campaign_uc'),)

    # Добавляем индексы для частых запросов
    Index('idx_campaign_client_week', 'client_id', 'week_start_date')
    Index('idx_campaign_user_week', 'user_id', 'week_start_date')

    def __repr__(self):
        return f'<WeeklyCampaignStat AccID:{self.yandex_account_id} C:{self.campaign_id} W:{self.week_start_date}>'


class WeeklyPlacementStat(db.Model):
    __tablename__ = 'weekly_placement_stat'
    id = db.Column(Integer, primary_key=True) # Простой автоинкрементный ключ

    # Связи и даты
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    yandex_account_id = db.Column(Integer, ForeignKey('yandex_account.id'), nullable=False, index=True)
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    client_id = db.Column(Integer, ForeignKey('client.id'), nullable=False, index=True)

    # Данные среза
    placement = db.Column(String(512)) # Название площадки
    ad_network_type = db.Column(String(50)) # SEARCH / NETWORK

    # Статистика
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)
    conversions = db.Column(Integer, nullable=True)

    # Уникальность записи определяется комбинацией полей
    __table_args__ = (
        UniqueConstraint('week_start_date', 'campaign_id', 'yandex_account_id', 'placement', 'ad_network_type', name='_week_placement_uc'),
        Index('idx_placement_client_camp_week', 'client_id', 'campaign_id', 'week_start_date'),
        Index('idx_placement_user_camp_week', 'user_id', 'campaign_id', 'week_start_date')
    )

    def __repr__(self):
        return f'<WeeklyPlacementStat C:{self.campaign_id} P:{self.placement} W:{self.week_start_date}>'

# ... (Аналогично адаптировать WeeklySearchQueryStat, WeeklyGeoStat, WeeklyDeviceStat, WeeklyDemographicStat) ...
# ... Добавить поля user_id, client_id, yandex_account_id ...
# ... Обновить ForeignKey, UniqueConstraint, Index ...

# Пример адаптации для WeeklySearchQueryStat:
class WeeklySearchQueryStat(db.Model):
    __tablename__ = 'weekly_search_query_stat'
    id = db.Column(Integer, primary_key=True)

    # Связи и даты
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    ad_group_id = db.Column(Integer, nullable=False, index=True) # ID группы объявлений
    yandex_account_id = db.Column(Integer, ForeignKey('yandex_account.id'), nullable=False, index=True)
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    client_id = db.Column(Integer, ForeignKey('client.id'), nullable=False, index=True)

    # Данные среза
    query = db.Column(String(1024)) # Поисковый запрос

    # Статистика
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)
    conversions = db.Column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint('week_start_date', 'campaign_id', 'ad_group_id', 'yandex_account_id', 'query', name='_week_query_uc'),
        Index('idx_query_client_camp_week', 'client_id', 'campaign_id', 'week_start_date'),
        Index('idx_query_user_camp_week', 'user_id', 'campaign_id', 'week_start_date')
    )

    def __repr__(self):
        return f'<WeeklySearchQueryStat C:{self.campaign_id} Q:{self.query[:30]} W:{self.week_start_date}>'

# TODO: Адаптировать остальные модели Weekly*Stat по аналогии


class WeeklyGeoStat(db.Model):
    __tablename__ = 'weekly_geo_stat'
    id = db.Column(Integer, primary_key=True)
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    location_id = db.Column(Integer, nullable=False, index=True) # ID региона (CriteriaId)
    # Добавляем связи для фильтрации
    yandex_account_id = db.Column(Integer, ForeignKey('yandex_account.id'), nullable=False, index=True)
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    client_id = db.Column(Integer, ForeignKey('client.id'), nullable=False, index=True)
    # location_name = db.Column(String(255)) # Опционально, если хотим хранить название
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)
    conversions = db.Column(Integer, nullable=True) # Добавляем конверсии

    __table_args__ = (
        UniqueConstraint('week_start_date', 'campaign_id', 'location_id', 'yandex_account_id', name='_week_geo_uc'), # Добавили yandex_account_id
        Index('idx_geo_client_camp_week', 'client_id', 'campaign_id', 'week_start_date'), # Новый индекс
        Index('idx_geo_user_camp_week', 'user_id', 'campaign_id', 'week_start_date') # Новый индекс
        # Старый индекс Index('idx_geo_user_camp_week', 'yandex_account_id', 'campaign_id', 'week_start_date') можно убрать или переименовать
    )

    def __repr__(self):
        return f'<WeeklyGeoStat C:{self.campaign_id} L:{self.location_id} W:{self.week_start_date}>'


class WeeklyDeviceStat(db.Model):
    __tablename__ = 'weekly_device_stat'
    id = db.Column(Integer, primary_key=True)
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    device_type = db.Column(String(50), nullable=False) # DESKTOP, MOBILE, TABLET
    # Добавляем связи для фильтрации
    yandex_account_id = db.Column(Integer, ForeignKey('yandex_account.id'), nullable=False, index=True)
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    client_id = db.Column(Integer, ForeignKey('client.id'), nullable=False, index=True)
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)
    conversions = db.Column(Integer, nullable=True) # Добавляем конверсии

    __table_args__ = (
        UniqueConstraint('week_start_date', 'campaign_id', 'device_type', 'yandex_account_id', name='_week_device_uc'), # Добавили yandex_account_id
        Index('idx_device_client_camp_week', 'client_id', 'campaign_id', 'week_start_date'), # Новый индекс
        Index('idx_device_user_camp_week', 'user_id', 'campaign_id', 'week_start_date') # Новый индекс
    )

    def __repr__(self):
        return f'<WeeklyDeviceStat C:{self.campaign_id} D:{self.device_type} W:{self.week_start_date}>'


class WeeklyDemographicStat(db.Model):
    __tablename__ = 'weekly_demographic_stat'
    id = db.Column(Integer, primary_key=True)
    week_start_date = db.Column(Date, nullable=False, index=True)
    campaign_id = db.Column(Integer, nullable=False, index=True)
    gender = db.Column(String(20), nullable=False) # GENDER_MALE, GENDER_FEMALE, GENDER_UNKNOWN
    age_group = db.Column(String(20), nullable=False) # AGE_0_17, AGE_18_24, ..., AGE_55, AGE_UNKNOWN
    # Добавляем связи для фильтрации
    yandex_account_id = db.Column(Integer, ForeignKey('yandex_account.id'), nullable=False, index=True)
    user_id = db.Column(Integer, ForeignKey('user.id'), nullable=False, index=True)
    client_id = db.Column(Integer, ForeignKey('client.id'), nullable=False, index=True)
    impressions = db.Column(Integer)
    clicks = db.Column(Integer)
    cost = db.Column(Float)
    conversions = db.Column(Integer, nullable=True) # Добавляем конверсии

    __table_args__ = (
        UniqueConstraint('week_start_date', 'campaign_id', 'gender', 'age_group', 'yandex_account_id', name='_week_demographic_uc'), # Добавили yandex_account_id
        Index('idx_demogr_client_camp_week', 'client_id', 'campaign_id', 'week_start_date'), # Новый индекс
        Index('idx_demogr_user_camp_week', 'user_id', 'campaign_id', 'week_start_date') # Новый индекс
    )

    def __repr__(self):
        return f'<WeeklyDemographicStat C:{self.campaign_id} G:{self.gender} A:{self.age_group} W:{self.week_start_date}>' 