# Проект: CPC Auto Helper (Стартовый этап MVP)

## 1. Общее Описание

**Цель:** Разработка веб-приложения (SaaS) для помощи специалистам по контекстной рекламе Яндекс.Директ. Сервис должен автоматизировать рутинные задачи сбора/анализа статистики и предоставлять рекомендации.

**Технологический стек (Старт MVP):**
*   **Backend:** Python 3.x, Flask
*   **Работа с БД:** Flask-SQLAlchemy (ORM), SQLAlchemy
*   **База данных:** SQLite (файл `tokens.db`) - **ДОБАВЛЕНО**
*   **HTTP Запросы:** Requests
*   **Конфигурация:** python-dotenv (для `.env` файла)
*   **Frontend:** Простейший HTML, генерируемый напрямую из Flask (без JS-фреймворков на данном этапе).

**Окружение Разработки:**
*   **ОС:** Windows 10/11
*   **Python:** Версия 3.x (установлен)
*   **Виртуальное окружение:** Используется `venv`, расположено в `C:\python\cpc_auto_star\venv\`
*   **Менеджер пакетов:** `pip`

**Структура проекта:**
C:\python\cpc_auto_star
├── venv\ # Виртуальное окружение
├── .env # Ключи API Яндекса (YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET) - СОЗДАН, ЗАПОЛНЕН
├── .gitignore # Правила игнорирования для Git - СОЗДАН
├── app.py # Основной файл приложения Flask - РЕАЛИЗОВАН OAuth флоу
├── requirements.txt # Список зависимостей - ОБНОВЛЕН (содержит flask, requests, python-dotenv, flask-sqlalchemy, sqlalchemy)
├── tokens.db # Файл базы данных SQLite - БУДЕТ СОЗДАН
└── PROJECT_README.md # Этот файл

## 2. Текущий Статус (Что уже сделано)

*   [x] Создана структура папок проекта.
*   [x] Инициализировано виртуальное окружение `venv`.
*   [x] Установлены базовые зависимости: `Flask`, `requests`, `python-dotenv`, `Flask-SQLAlchemy`.
*   [x] Зафиксированы зависимости в `requirements.txt`.
*   [x] Создан и заполнен файл `.env` с `YANDEX_CLIENT_ID` и `YANDEX_CLIENT_SECRET`.
*   [x] Создан файл `.gitignore` (игнорирует `venv/`, `__pycache__/`, `*.pyc`, `.env`, `*.db` - **добавить `*.db` в .gitignore!**).
*   [x] Создан файл `app.py`.
*   [x] Получены Client ID и Client Secret от Яндекс OAuth.
*   [x] Реализован базовый Flask сервер.
*   [x] Реализован редирект на страницу авторизации Яндекс OAuth.
*   [x] Реализован callback-обработчик для получения `code` от Яндекса.
*   [x] Реализован обмен `code` на `access_token` и `refresh_token`.
*   [x] Токены временно сохранялись/читались из Flask `session`.
*   [x] Реализовано получение `client_login` через API Яндекс ID.
*   [x] Реализован первый тестовый запрос к API Директа (песочница) с использованием `access_token` из сессии.
*   [ ] Настроена интеграция Flask-SQLAlchemy.
*   [ ] Определена модель данных `Token` для SQLAlchemy.
*   [ ] Создана база данных SQLite (`tokens.db`) с таблицей `token`.
*   [ ] Логика сохранения/обновления токенов перенесена из `session` в БД.
*   [ ] Логика чтения токенов перенесена из `session` в БД.
*   [ ] Реализована проверка истечения `access_token` (`expires_at`).
*   [ ] Реализована логика автоматического обновления `access_token` с помощью `refresh_token`.

**ВАЖНО:** Не забудь добавить `*.db` в файл `.gitignore`, чтобы случайно не добавить файл базы данных в систему контроля версий Git.

## 3. ЗАДАЧА ДЛЯ CURSOR НА СЕЙЧАС: Интеграция БД и Хранение Токенов

**Цель:** Заменить временное хранение OAuth-токенов в сессии Flask на постоянное хранение в базе данных SQLite с использованием Flask-SQLAlchemy. Реализовать базовую логику чтения/записи и подготовки к обновлению токенов.

**Разбивка на подзадачи (для последовательной работы):**

**Подзадача 3.1: Настройка Flask-SQLAlchemy и Модель Данных**

*   **В файле `app.py`:**
    1.  Импортировать `SQLAlchemy` из `flask_sqlalchemy`.
    2.  Импортировать `datetime` из `datetime`.
    3.  Добавить конфигурацию для SQLAlchemy *после* `app = Flask(__name__)`:
        ```python
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tokens.db'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db = SQLAlchemy(app)
        ```
    4.  Определить класс модели `Token`, наследующийся от `db.Model`:
        ```python
        class Token(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            yandex_login = db.Column(db.String(80), unique=True, nullable=False)
            access_token = db.Column(db.String(200), nullable=False)
            refresh_token = db.Column(db.String(200), nullable=True)
            expires_at = db.Column(db.DateTime, nullable=False)

            def __repr__(self):
                return f'<Token for {self.yandex_login}>'
        ```
    5.  **Важно:** Пока не меняй существующие роуты.

**Подзадача 3.2: Создание Базы Данных**

*   **В файле `app.py`:** Временно добавь следующий код *после* определения модели `Token` и *перед* определением роутов (или перед `if __name__ == '__main__':`). Этот код создаст файл `tokens.db` и таблицу `token`, если их еще нет.
    ```python
    with app.app_context():
        db.create_all()
    print("База данных и таблицы проверены/созданы.") # Для отладки
    ```
*   **Действие:** Запусти приложение один раз (`flask run`). Убедись, что сообщение "База данных и таблицы проверены/созданы" появилось в консоли и в папке проекта появился файл `tokens.db`. **После этого можешь закомментировать или удалить этот блок `with app.app_context(): ...`, чтобы он не выполнялся при каждом запуске.**

**Подзадача 3.3: Перенос Сохранения Токенов в БД**

*   **В роуте `/get_token`:**
    1.  *После* успешного получения `token_data` от Яндекс OAuth (в блоке `try`):
    2.  Получи `client_login`, как это сейчас делается в `/test_api_call` (этот кусок кода нужно будет или перенести сюда, или вынести в отдельную функцию, чтобы не дублировать). **Важно:** обработай ошибки получения логина. Если логин не получен, не сохраняй токен.
    3.  Рассчитай `expires_at`: `expires_at_dt = datetime.utcnow() + timedelta(seconds=token_data['expires_in'])`. Убедись, что `datetime` и `timedelta` импортированы (`from datetime import datetime, timedelta`).
    4.  Найди существующий токен в БД по логину: `existing_token = Token.query.filter_by(yandex_login=client_login).first()`.
    5.  **Если `existing_token` найден:**
        *   Обнови его поля: `existing_token.access_token = token_data['access_token']`, `existing_token.expires_at = expires_at_dt`.
        *   Обнови `refresh_token`, *только если* он пришел в ответе Яндекса: `if 'refresh_token' in token_data: existing_token.refresh_token = token_data['refresh_token']`.
    6.  **Если `existing_token` НЕ найден:**
        *   Создай новый объект: `new_token = Token(...)`, заполнив все поля (`yandex_login`, `access_token`, `refresh_token`, `expires_at`).
        *   Добавь его в сессию SQLAlchemy: `db.session.add(new_token)`.
    7.  Сохрани изменения в БД: `db.session.commit()`.
    8.  **УДАЛИ** строки, сохраняющие токены и `expires_in` в `session` Flask (`session['yandex_access_token'] = ...` и т.д.).
    9.  **УДАЛИ** строку `session.pop('yandex_auth_code', None)` - код больше не нужен в сессии.
    10. Временно сохрани `client_login` в сессию Flask: `session['yandex_client_login'] = client_login`. Это нужно, чтобы другие роуты знали, для какого пользователя искать токен в БД.
    11. Обнови возвращаемый HTML, чтобы он сообщал об успешном сохранении в БД и по-прежнему содержал ссылку на `/test_api`.

**Подзадача 3.4: Перенос Чтения Токенов из БД**

*   **В роуте `/test_api_call`:**
    1.  Получи `client_login` из сессии: `client_login = session.get('yandex_client_login')`. Если его нет, верни ошибку или редирект на главную (`/`).
    2.  **УДАЛИ** код, который получал `client_login` через API Яндекс ID (он теперь получается и сохраняется в сессию в `/get_token`).
    3.  Найди токен в БД: `token_entry = Token.query.filter_by(yandex_login=client_login).first()`.
    4.  **Если `token_entry` НЕ найден:** Верни ошибку "Токен для пользователя не найден в БД".
    5.  **Если `token_entry` найден:** Получи `access_token` из него: `access_token = token_entry.access_token`.
    6.  **УДАЛИ** строку, получавшую токен из сессии Flask (`access_token = session.get('yandex_access_token')`).
    7.  Используй полученный `access_token` для дальнейшего вызова API Директа.
    8.  **Пока не добавляй проверку `expires_at`**. Сначала убедись, что базовое чтение из БД работает.

**Важные Замечания для Cursor:**
*   Двигайся по подзадачам последовательно.
*   Используй `db.session.add()`, `db.session.commit()`, `Token.query.filter_by().first()` для работы с БД через SQLAlchemy.
*   Обрабатывай возможные ошибки (токен не найден, логин не получен).
*   Не забывай импортировать `datetime`, `timedelta`.
*   Вынос получения `client_login` в отдельную функцию – хорошая практика, чтобы избежать дублирования кода между `/get_token` и (ранее) `/test_api_call`.

## 4. Следующие Шаги (После выполнения текущей задачи)

*   [ ] Реализовать проверку `expires_at` в `/test_api_call`.
*   [ ] Реализовать логику автоматического обновления `access_token` с помощью `refresh_token` (запрос к `/token` с `grant_type=refresh_token`, обновление записи в БД).
*   [ ] Обработать случай невалидного `refresh_token` (требуется повторная авторизация).
*   [ ] Продумать и реализовать шифрование токенов в БД (Технический долг!).
*   [ ] Начать реализацию основного функционала MVP (выгрузка/анализ площадок и запросов).