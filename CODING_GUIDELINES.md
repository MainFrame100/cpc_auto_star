**CODING_GUIDELINES.md (Проект: CPC Auto Helper)**

**Версия:** 1.0 от [Текущая Дата]

**1. Общие Принципы**

*   **Читаемость Превыше Всего (PEP 8):**
    *   Код форматируется с помощью `Black`.
    *   Импорты сортируются с помощью `isort`.
    *   Стиль и потенциальные ошибки проверяются `Flake8`.
    *   Используются осмысленные имена (`snake_case` для функций/переменных, `CamelCase` для классов).
    *   Функции и методы должны быть короткими и выполнять одну задачу (SRP).
    *   Минимизируется вложенность, используется "ранний выход".
*   **Простота и Ясность (KISS):**
    *   Предпочитается простой и понятный код.
    *   Оптимизация производительности – только при наличии реальной проблемы.
    *   Явное лучше неявного.
*   **Не Повторяй Себя (DRY - Don't Repeat Yourself):**
    *   Избегай копипаста. Выноси повторяющуюся логику в функции или классы.
    *   Используй шаблоны Jinja2 и наследование для UI.

**2. Структура Проекта и Кода**

*   **Модульность (Flask Blueprints):** Используется для разделения приложения на логические части (`main`, `auth`, `reports`, `api_clients`, `utils`).
*   **Разделение Ответственности:**
    *   **Роуты (`routes.py`):** Тонкие контроллеры. Принимают запрос, вызывают сервисы/утилиты, готовят контекст, рендерят шаблон. **Без сложной логики и прямых вызовов внешних API.**
    *   **Утилиты/Сервисы (`utils.py`):** Содержат бизнес-логику, не привязанную к конкретному роуту или модели.
    *   **Модели (`models.py`):** Описание схемы БД через SQLAlchemy. Минимум логики.
    *   **API-Клиенты (`api_clients/`):** Инкапсуляция взаимодействия с внешними API (`YandexDirectClient`). Обработка специфики API (URL, заголовки, ошибки, ретраи).
    *   **Конфигурация (`config.py`, `.env`):** Внешняя конфигурация приложения. **Никаких секретов в коде.** Все настройки только в этих файлах

**3. Качество Кода и Инструменты**

*   **Контроль Качества (Минимум для MVP):**
    *   Использовать расширения для форматеров (`Black`) и линтеров (`Flake8`) в IDE.
    *   **(Рекомендовано)** Настроить **pre-commit хуки** для автоматической проверки перед коммитом (`black`, `isort`, `flake8`).
*   **Типизация (Type Hints - PEP 484):**
    *   **(Рекомендовано)** Добавлять аннотации типов **хотя бы** для сигнатур публичных функций и методов (особенно в `utils` и `api_clients`). Это улучшает читаемость и помогает статическим анализаторам и AI-ассистентам.
    *   Пример: `def get_valid_token(client_login: str) -> str | None:`
*   **Документирование (Docstrings):**
    *   **(Рекомендовано)** Писать **докстринги** (в тройных кавычках) для всех нетривиальных функций, классов и модулей, объясняя их назначение, аргументы (`Args:`) и возвращаемое значение (`Returns:`). Стиль Google или NumPy.

**4. Работа с Данными (PostgreSQL + SQLAlchemy)**

*   **ORM:** Использовать SQLAlchemy ORM. Избегать сырых SQL без крайней необходимости.
*   **Миграции (Flask-Migrate):** **Все** изменения схемы БД – **только** через генерацию и применение миграций.
*   **Транзакции:** `db.session.commit()` только после успешного завершения логической операции. `db.session.rollback()` при ошибках.
*   **Расчетные Метрики:** Хранить в БД **сырые данные** (Показы, Клики, Расход, Конверсии). Расчетные показатели (CTR, CPC, CR, CPA) **рассчитывать на лету** в Python (в роутах или утилитах) или в шаблонах Jinja2.

**5. Обработка Ошибок и Логирование**

*   **Обработка Исключений:** Оборачивать потенциально проблемные операции (внешние API, работа с БД, файлами) в `try...except`. Ловить **конкретные** ожидаемые исключения.
*   **Логирование (Минимум для MVP):**
    *   Использовать стандартный модуль `logging`. Настроить базовую конфигурацию в `app/__init__.py` (уровень INFO, вывод в stdout/файл).
    *   Заменить все `print()` для отладки на вызовы `logger.debug()`, `logger.info()`, `logger.warning()`, `logger.error()`.
    *   Логировать важные события и особенно ошибки, включая traceback при исключениях (`logger.exception("Сообщение об ошибке")`).
*   **Ретраи для API (`tenacity`):** Обязательно использовать для вызовов к внешним API (особенно Директ) для повышения надежности.

**6. Безопасность (Минимум для MVP)**

*   **Секреты:** Хранить в `.env`, не коммитить в Git. Использовать надежный `SECRET_KEY`.
*   **Шифрование Токенов:** OAuth-токены в БД **должны быть зашифрованы** (использовать `cryptography`).
*   **Flask-Login:** Использовать `@login_required` для защиты роутов.

**7. Контроль Версий (Git)**

*   **Коммиты:** Атомарные, логически завершенные, с осмысленными сообщениями.
*   **Ветвление:** Использовать ветки для фич и багфиксов (`feature/...`, `fix/...`).

**8. Специфика Проекта**

*   **Универсальная Функция для API Reports:** Учитывая частое использование API Reports для разных срезов, создать максимально универсальную и параметризованную функцию (или метод в `YandexDirectClient`) для формирования `ReportDefinition`, запроса отчета, ожидания и парсинга. Параметризовать: `ReportType`, `FieldNames`, `Filter`, `DateRangeType`/`DateFrom`/`DateTo`, `Goals` и т.д.



Детальное описание компонентов для работы с API Яндекс.Директ, которое можно передать другому разработчику:

**Файл:** `app/api_clients/yandex_direct.py`

Этот модуль содержит классы и методы для взаимодействия с API Яндекс.Директ v5, включая обработку ошибок, авторизацию, выполнение запросов и получение отчетов.

**1. Классы Исключений (Exceptions)**

Эти классы используются для сигнализации о различных проблемах при работе с API.

*   **`YandexDirectClientError(Exception)`**
    *   **Назначение:** Базовый класс для всех специфичных ошибок клиента API. Ловить его можно для обработки любых ошибок, связанных с API Директа.
    *   **Атрибуты:**
        *   `message` (str): Описание ошибки.
        *   `status_code` (int | None): HTTP статус код ответа, если применимо.
        *   `api_error_code` (int | None): Код ошибки из ответа API Директа, если есть.
        *   `api_error_detail` (str | None): Детальное описание ошибки из ответа API Директа, если есть.

*   **`YandexDirectAuthError(YandexDirectClientError)`**
    *   **Назначение:** Указывает на проблемы с аутентификацией или авторизацией. Это может быть невалидный OAuth-токен, истекший токен, недостаточные права доступа у токена или попытка доступа к чужому аккаунту.
    *   **Когда возникает:** При инициализации клиента (`__init__`), если токен не найден, невалиден, или при выполнении запроса, если API возвращает ошибки 401, 403 или специфичные коды ошибок API (52, 53, 54, 56).

*   **`YandexDirectTemporaryError(YandexDirectClientError)`**
    *   **Назначение:** Указывает на временную ошибку на стороне API или сети, из-за которой запрос не удалось выполнить, но есть смысл его повторить позже.
    *   **Когда возникает:** При сетевых проблемах (таймаут, обрыв соединения), или если API возвращает статусы 429 (Too Many Requests), 5xx (Server errors), или специфичные временные коды ошибок API. Клиент (`_make_request` и `get_report`) автоматически пытается повторить запросы при таких ошибках.

*   **`YandexDirectReportError(YandexDirectClientError)`**
    *   **Назначение:** Указывает на ошибку, специфичную для работы с API Отчетов. Это может быть ошибка в параметрах запроса отчета, невалидный формат, или если отчет не был сформирован за отведенное время и количество попыток.
    *   **Когда возникает:** В методе `get_report`, если API Отчетов вернуло ошибку (например, 400) или если отчет не был готов после всех ретраев.

**2. Основной Класс `YandexDirectClient`**

*   **Назначение:** Инкапсулирует логику взаимодействия с API Яндекс.Директ для *конкретного* рекламного аккаунта (`YandexAccount`).
*   **Инициализация `__init__(self, yandex_account_id: int, current_user_id: int)`:**
    *   **Параметры:**
        *   `yandex_account_id` (int): ID записи `YandexAccount` в базе данных, для которого нужно выполнить запрос.
        *   `current_user_id` (int): ID текущего авторизованного пользователя (`User`) в системе. **Критически важно** для проверки прав доступа к токену указанного `yandex_account_id`.
    *   **Действия:**
        1.  Находит токен (`Token`) для `yandex_account_id`.
        2.  **Проверяет, принадлежит ли токен `current_user_id`.** Если нет - выбрасывает `YandexDirectAuthError`.
        3.  Дешифрует `access_token` с помощью ключа `ENCRYPTION_KEY` из переменных окружения.
        4.  (TODO: Добавить проверку срока действия токена и обновление через `refresh_token`).
        5.  Получает логин (`client_login`) связанного `YandexAccount`.
        6.  Получает URL API (v5, v5.01, reports) из конфигурации Flask (`current_app.config`).
        7.  Формирует базовые заголовки (`self.headers`) и заголовки для API Отчетов (`self.report_headers`), включая `Authorization: Bearer ...` и `Client-Login: ...`.
    *   **Исключения:**
        *   `YandexDirectAuthError`: Токен не найден, принадлежит другому пользователю, ошибка дешифровки.
        *   `ValueError`: Не настроены URL API в конфигурации Flask.
        *   `YandexDirectClientError`: Другие ошибки (например, у `YandexAccount` нет логина).

*   **Приватный Метод `_make_request(self, service_path, payload, api_version='v5')`:**
    *   **Назначение:** Внутренний метод для выполнения **стандартных** запросов к API (не для отчетов). Обрабатывает ретраи для временных ошибок.
    *   **Параметры:**
        *   `service_path` (str): Путь к сервису API (например, `/campaigns`, `/adgroups`).
        *   `payload` (dict): Тело запроса в формате словаря Python (будет преобразовано в JSON). Структура должна соответствовать документации API Директа (обычно содержит ключи `method` и `params`).
        *   `api_version` (str): Версия API (`'v5'` или `'v501'`). По умолчанию `'v5'`.
    *   **Действия:**
        1.  Формирует полный URL.
        2.  Выполняет POST-запрос с использованием `self.headers`.
        3.  Применяет декоратор `@retry` (библиотека `tenacity`) для автоматического повтора запроса при временных ошибках (`YandexDirectTemporaryError`, `requests.exceptions.Timeout`, `requests.exceptions.ConnectionError`, статусы 429, 5xx). Используется экспоненциальная задержка между попытками.
        4.  Проверяет HTTP статус ответа и генерирует соответствующие исключения (`YandexDirectAuthError`, `YandexDirectTemporaryError`, `YandexDirectClientError`).
        5.  Парсит JSON ответа.
        6.  Проверяет наличие поля `"error"` в ответе API и генерирует соответствующие исключения.
        7.  Логирует запрос и ответ (частично).
    *   **Возвращает:** Содержимое ключа `"result"` из успешного ответа API (обычно словарь или список).
    *   **Исключения:** Любое из описанных выше (`YandexDirectAuthError`, `YandexDirectTemporaryError`, `YandexDirectClientError`).

*   **Метод `get_report(self, report_definition: dict) -> str`:**
    *   **Назначение:** Запрашивает, ожидает готовности и скачивает отчет из API Отчетов.
    *   **Параметры:**
        *   `report_definition` (dict): Словарь, описывающий параметры отчета. Должен иметь структуру, как в документации API (например, `{'params': {'SelectionCriteria': {...}, 'FieldNames': [...], 'ReportName': '...', 'ReportType': '...', ...}}`).
    *   **Действия:**
        1.  Использует специальный URL API Отчетов и заголовки `self.report_headers`.
        2.  Выполняет POST-запрос к API Отчетов.
        3.  Обрабатывает статусы ответа:
            *   **200 OK:** Отчет готов. Метод завершается и возвращает тело отчета.
            *   **201 Created / 202 Accepted:** Отчет формируется. Метод ожидает время, указанное в заголовке `retryIn` (или использует экспоненциальную задержку), и повторяет запрос статуса (переходит к шагу 2).
            *   **400 Bad Request:** Ошибка в параметрах отчета. Выбрасывает `YandexDirectReportError`.
            *   **401 Unauthorized / 403 Forbidden:** Ошибка авторизации. Выбрасывает `YandexDirectAuthError`.
            *   **429 Too Many Requests / 5xx Server Error:** Временная ошибка. Метод ожидает и повторяет запрос (с ограниченным числом ретраев для этих ошибок внутри цикла). Если лимит ретраев превышен, выбрасывает `YandexDirectTemporaryError`.
            *   **Другие ошибки:** Выбрасывает `YandexDirectReportError`.
        4.  Обрабатывает сетевые ошибки (`Timeout`, `ConnectionError`) аналогично временным ошибкам API (ретраи с ожиданием).
        5.  Если максимальное количество попыток ожидания (`MAX_ATTEMPTS`) превышено, а отчет так и не получен, выбрасывает `YandexDirectReportError`.
    *   **Возвращает:** (str) Сырые данные готового отчета в формате TSV.
    *   **Исключения:** `ValueError` (некорректный `report_definition`), `YandexDirectAuthError`, `YandexDirectTemporaryError`, `YandexDirectReportError`, `YandexDirectClientError`.

*   **Методы для получения данных (используют `_make_request`):**
    *   **`get_campaigns(self, selection_criteria=None, field_names=None)`**
        *   Получает список кампаний.
        *   `selection_criteria` (dict | None): Критерии отбора (см. API Campaigns).
        *   `field_names` (list[str] | None): Запрашиваемые поля (по умолчанию: Id, Name, Type, State, Status).
        *   Возвращает: list[dict] - список кампаний.
    *   **`get_clients(self)`**
        *   Получает информацию о клиенте (для прямого рекламодателя, не агентства). Использует API v5.01.
        *   Возвращает: dict - информация о клиенте.
    *   **`get_agency_clients(self)`**
        *   Получает список клиентов агентства.
        *   Возвращает: list[dict] - список клиентов агентства.
    *   **`get_adgroups(self, campaign_ids: list[int], field_names: list[str] = ...)`**
        *   Получает группы объявлений для указанных ID кампаний.
        *   `campaign_ids` (list[int]): Список ID кампаний.
        *   `field_names` (list[str]): Запрашиваемые поля (по умолчанию: Id, Name, CampaignId, Status, Type).
        *   Возвращает: list[dict] - список групп объявлений.

*   **Методы для управления (используют `_make_request`):**
    *   **`set_adgroup_bids(self, bids: list[dict])`**
        *   Устанавливает ставки для групп объявлений.
        *   `bids` (list[dict]): Список словарей, каждый вида `{"AdGroupId": id, "Bid": ставка}`.
        *   Возвращает: dict - результат операции от API.
    *   **`suspend_adgroups(self, adgroup_ids: list[int])`**
        *   Останавливает показы для указанных групп объявлений.
        *   `adgroup_ids` (list[int]): Список ID групп.
        *   Возвращает: dict - результат операции от API.
    *   **`resume_adgroups(self, adgroup_ids: list[int])`**
        *   Возобновляет показы для указанных групп объявлений.
        *   `adgroup_ids` (list[int]): Список ID групп.
        *   Возвращает: dict - результат операции от API.

*   **Вспомогательные методы:**
    *   **`_is_retryable_exception(self, exception)`:** Внутренний метод, используемый `@retry` для определения, нужно ли повторять запрос после конкретного исключения.
    *   **`_get_error_detail(self, response: requests.Response) -> str`:** Внутренний метод для извлечения текста ошибки из ответа API.
    *   **`get_campaign_type_display_name(self, campaign_type_api_name: str) -> str`:** Возвращает русское название типа кампании по его API-имени (например, "TEXT_CAMPAIGN" -> "Текстово-графические объявления").

**Пример использования:**

```python
from flask import current_app
from .yandex_direct import YandexDirectClient, YandexDirectAuthError, YandexDirectClientError, YandexDirectReportError

def get_campaigns_for_account(yandex_account_id: int, user_id: int):
    try:
        # Инициализируем клиент для нужного аккаунта и текущего пользователя
        api_client = YandexDirectClient(yandex_account_id=yandex_account_id, current_user_id=user_id)
        
        # Запрашиваем кампании
        campaigns = api_client.get_campaigns(field_names=["Id", "Name", "State"])
        current_app.logger.info(f"Successfully fetched {len(campaigns)} campaigns for account {api_client.client_login}")
        return campaigns, None

    except YandexDirectAuthError as e:
        error_msg = f"Authorization error for account {yandex_account_id}: {e}"
        current_app.logger.error(error_msg)
        return None, error_msg
    except YandexDirectClientError as e:
        error_msg = f"API client error for account {yandex_account_id}: {e}"
        current_app.logger.error(error_msg)
        return None, error_msg
    except Exception as e:
        # Общая непредвиденная ошибка
        error_msg = f"Unexpected error processing account {yandex_account_id}: {e}"
        current_app.logger.exception(error_msg) # Логируем с трейсбеком
        return None, error_msg

def get_weekly_report(yandex_account_id: int, user_id: int, report_def: dict):
    try:
        api_client = YandexDirectClient(yandex_account_id=yandex_account_id, current_user_id=user_id)
        report_data_tsv = api_client.get_report(report_def)
        current_app.logger.info(f"Report '{report_def.get('params',{}).get('ReportName')}' received for account {api_client.client_login}, size: {len(report_data_tsv)} bytes.")
        # Дальнейшая обработка TSV данных...
        return report_data_tsv, None
    except YandexDirectReportError as e:
        error_msg = f"Report error for account {yandex_account_id}: {e}"
        current_app.logger.error(error_msg)
        return None, error_msg
    # ... (обработка других исключений как в примере выше) ...
    except Exception as e:
         error_msg = f"Unexpected error getting report for account {yandex_account_id}: {e}"
         current_app.logger.exception(error_msg)
         return None, error_msg

```

