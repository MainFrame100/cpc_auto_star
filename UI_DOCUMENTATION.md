# Документация по интерфейсу CPC Auto Helper

## Содержание
1. [Введение](#введение)
2. [Архитектура интерфейса](#архитектура-интерфейса)
3. [Компоненты UI](#компоненты-ui)
4. [CSS-структура](#css-структура)
5. [JavaScript функционал](#javascript-функционал)
6. [Инструкция по интеграции](#инструкция-по-интеграции)
7. [Рекомендации по расширению](#рекомендации-по-расширению)

## Введение

Этот документ описывает архитектуру, компоненты и принципы работы пользовательского интерфейса CPC Auto Helper. Документация предназначена для разработчиков, которые будут поддерживать и расширять функциональность приложения.

Интерфейс основан на следующих принципах:
- **Структурированность данных** - использование вкладок, карточек и иерархии для улучшения восприятия
- **Интерактивность** - базовые интерактивные элементы без сложного JS-фреймворка
- **Адаптивность** - корректное отображение на различных устройствах
- **Расширяемость** - модульная структура, позволяющая легко добавлять новые элементы

## Архитектура интерфейса

### Общая структура приложения

Интерфейс состоит из следующих основных страниц:
1. **Главная страница** (`auth/index.html`) - точка входа в приложение
2. **Список кампаний** (`reports/campaign_list.html`) - отображает список доступных кампаний
3. **Детализация кампании** (`reports/campaign_detail.html`) - показывает подробную статистику по кампании

Все страницы наследуются от базового шаблона `base.html`, который определяет общую структуру: шапку, футер и область основного содержимого.

### Шаблонизация

Приложение использует шаблонизатор Jinja2. Основные принципы:
- Наследование от `base.html` через `{% extends 'base.html' %}`
- Определение блоков `{% block content %}{% endblock %}` и `{% block scripts %}{% endblock %}`
- Использование условных конструкций и циклов для динамического формирования контента

## Компоненты UI

### 1. Карточки (Cards)

Карточки - основной контейнер для группировки контента.

```html
<div class="card">
    <div class="card-header">
        <h2 class="my-0">Заголовок карточки</h2>
    </div>
    <!-- Содержимое карточки -->
</div>
```

### 2. Метрики (Metrics)

Метрики используются для отображения ключевых показателей.

```html
<div class="metric-cards">
    <div class="metric-card">
        <div class="metric-title">Название метрики</div>
        <div class="metric-value">Значение</div>
        <div class="metric-change positive">+5.2%</div>
    </div>
</div>
```

### 3. Вкладки (Tabs)

Вкладки используются для переключения между различными срезами данных.

```html
<!-- Заголовки вкладок -->
<div class="tabs">
    <div class="tab active" data-tab="tab1">Вкладка 1</div>
    <div class="tab" data-tab="tab2">Вкладка 2</div>
</div>

<!-- Содержимое вкладок -->
<div class="tab-content active" id="tab-tab1">
    Содержимое вкладки 1
</div>
<div class="tab-content" id="tab-tab2">
    Содержимое вкладки 2
</div>
```

### 4. Переключатель периодов (Period Selector)

Переключатель периодов используется для выбора временного интервала.

```html
<div class="period-selector">
    <button class="period-option active" data-period="all">Все периоды</button>
    <button class="period-option" data-period="period1">Период 1</button>
</div>

<!-- Контент для разных периодов -->
<div class="period-data" data-period-content="all">
    Данные за все периоды
</div>
<div class="period-data" data-period-content="period1" style="display:none;">
    Данные за период 1
</div>
```

### 5. Таблицы (Tables)

Таблицы используются для отображения детальной статистики.

```html
<div class="table-controls">
    <div class="table-filters">
        <div class="table-search">
            <input type="text" id="table-search" placeholder="Поиск">
        </div>
        <select id="rows-per-page">
            <option value="25">25 на странице</option>
        </select>
    </div>
    <div>
        <button class="button button-small">Действие</button>
    </div>
</div>

<div class="table-container">
    <table>
        <thead>
            <tr>
                <th class="sortable" data-sort="column1">Колонка 1</th>
                <th class="sortable numeric" data-sort="column2">Колонка 2</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Значение 1</td>
                <td class="numeric">123.45</td>
            </tr>
        </tbody>
    </table>
</div>

<div class="pagination">
    <ul>
        <li><a href="#" class="prev-page">« Назад</a></li>
        <li class="active"><a href="#">1</a></li>
        <li><a href="#" class="next-page">Вперед »</a></li>
    </ul>
</div>
```

### 6. Flash-сообщения (Flash Messages)

Flash-сообщения используются для отображения уведомлений пользователю.

```html
<div class="flash-message flash-success">
    <div>Сообщение об успешной операции</div>
    <button class="close">×</button>
</div>
```

## CSS-структура

CSS-файл `style.css` имеет модульную структуру и включает следующие секции:

1. **Переменные** - CSS-переменные для цветов, размеров, теней и т.д.
2. **Основные стили** - базовые стили для body, header, main, footer
3. **Типографика** - стили для заголовков, абзацев, текста
4. **Элементы форм** - стили для кнопок, инпутов, селектов
5. **Контейнеры** - стили для карточек и других контейнеров
6. **Таблицы** - стили для таблиц, строк, ячеек
7. **Табы** - стили для вкладок и их содержимого
8. **Фильтры и навигация** - стили для элементов управления таблицами
9. **Пагинация** - стили для навигации по страницам
10. **Метрики** - стили для карточек с метриками
11. **Переключатель периодов** - стили для выбора временного периода
12. **Flash-сообщения** - стили для уведомлений
13. **Утилиты** - вспомогательные классы для текста, цвета, отступов
14. **Адаптивность** - медиа-запросы для различных размеров экрана

### Цветовая палитра

Основные цвета определены через CSS-переменные:
- `--color-primary`: #3366cc - Основной цвет
- `--color-accent`: #ff9900 - Акцентный цвет
- `--color-success`: #27ae60 - Цвет успеха
- `--color-danger`: #e74c3c - Цвет ошибки
- `--color-warning`: #f39c12 - Цвет предупреждения
- `--color-info`: #3498db - Цвет информации

### Размеры и отступы

- `--spacing-xs`: 4px
- `--spacing-sm`: 8px
- `--spacing-md`: 16px
- `--spacing-lg`: 24px
- `--spacing-xl`: 32px

### Утилитарные классы

В CSS включены вспомогательные классы для быстрого применения стилей:
- `.text-success`, `.text-danger`, `.text-warning`, `.text-info` - цвета текста
- `.bg-success`, `.bg-danger`, `.bg-warning`, `.bg-info` - цвета фона
- `.text-center`, `.text-right`, `.text-left` - выравнивание текста
- `.mb-0`, `.mt-0`, `.my-0` - отступы
- `.hidden` - скрытие элемента

## JavaScript функционал

JavaScript-код `main.js` организован в виде отдельных модулей-функций:

### 1. Инициализация

```javascript
document.addEventListener('DOMContentLoaded', function() {
    initTabs();
    initPeriodSelector();
    initTableControls();
    initPagination();
    initSortableTables();
    initFlashMessages();
});
```

### 2. Вкладки (Tabs)

Функция `initTabs()` обеспечивает переключение между вкладками.
- Атрибут `data-tab` на `.tab` указывает ID содержимого вкладки
- ID содержимого формируется как `tab-{data-tab}`

### 3. Переключатель периодов (Period Selector)

Функция `initPeriodSelector()` обеспечивает переключение между периодами.
- Атрибут `data-period` на `.period-option` указывает ID периода
- Атрибут `data-period-content` на `.period-data` соответствует `data-period`

### 4. Таблицы и их контролы

Функции для работы с таблицами:
- `initTableControls()` - инициализация поиска, фильтров, чекбоксов
- `filterTable()` - фильтрация таблицы по поисковому запросу
- `applyTableFilters()` - применение составных фильтров

### 5. Пагинация

Функция `initPagination()` обеспечивает работу пагинации (для демонстрации).

### 6. Сортировка

Функция `initSortableTables()` обеспечивает сортировку таблиц по столбцам.
- Атрибут `data-sort` на `.sortable` указывает имя поля для сортировки
- Класс `.numeric` на `.sortable` указывает на числовой тип данных

### 7. Flash-сообщения

Функция `initFlashMessages()` обеспечивает закрытие и автоматическое скрытие уведомлений.

### 8. Вспомогательные функции

- `exportCSV()` - экспорт данных в CSV
- `performAction()` - выполнение действий (блокировка площадок, добавление минус-слов)

## Инструкция по интеграции

### Шаг 1: Обновление зависимостей

1. Убедитесь, что в проекте есть папки для статических файлов:
   ```
   static/
   ├── css/
   │   └── style.css
   └── js/
       └── main.js
   ```

2. Рекомендуется добавить шрифты Roboto в `base.html`:
   ```html
   <link rel="preconnect" href="https://fonts.googleapis.com">
   <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
   <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Roboto+Mono&display=swap" rel="stylesheet">
   ```

### Шаг 2: Обновление базового шаблона

1. Обновите `base.html`, добавив блок для скриптов:
   ```html
   <!DOCTYPE html>
   <html lang="ru">
   <head>
       <meta charset="UTF-8">
       <meta name="viewport" content="width=device-width, initial-scale=1.0">
       <title>{% block title %}CPC Auto Helper{% endblock %}</title>
       <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
       <!-- Шрифты Roboto -->
   </head>
   <body>
       <header>
           <!-- Шапка -->
       </header>

       <main>
           <!-- Flash-сообщения -->
           {% with messages = get_flashed_messages(with_categories=true) %}
               {% if messages %}
                   <div class="flash-messages">
                   {% for category, message in messages %}
                       <div class="flash-message flash-{{ category }}">
                           <div>{{ message }}</div>
                           <button class="close">×</button>
                       </div>
                   {% endfor %}
                   </div>
               {% endif %}
           {% endwith %}

           <!-- Основной контент -->
           {% block content %}{% endblock %}
       </main>

       <footer>
           <!-- Футер -->
       </footer>

       <!-- Скрипты -->
       {% block scripts %}{% endblock %}
       <script src="{{ url_for('static', filename='js/main.js') }}"></script>
   </body>
   </html>
   ```

### Шаг 3: Обновление шаблонов страниц

1. Замените содержимое `reports/campaign_list.html` и `reports/campaign_detail.html` на новые версии.

2. Убедитесь, что шаблоны правильно наследуются от `base.html` и используют блоки `content` и `scripts`.

### Шаг 4: Проверка работоспособности

1. Запустите приложение и проверьте корректность отображения страниц.
2. Протестируйте интерактивные элементы: вкладки, переключатель периодов, сортировку таблиц.
3. Проверьте адаптивность интерфейса на разных устройствах.

## Рекомендации по расширению

### 1. Добавление новой страницы

Для добавления новой страницы:
1. Создайте файл шаблона в соответствующей директории
2. Наследуйте шаблон от `base.html`
3. Определите блоки `content` и `scripts` (при необходимости)
4. Используйте существующие компоненты UI

```html
{% extends 'base.html' %}

{% block title %}Название страницы - CPC Auto Helper{% endblock %}

{% block content %}
    <div class="card">
        <div class="card-header">
            <h2 class="my-0">Заголовок страницы</h2>
        </div>
        
        <!-- Содержимое страницы -->
    </div>
{% endblock %}

{% block scripts %}
    <!-- Дополнительные скрипты -->
{% endblock %}
```

### 2. Добавление новой вкладки на странице детализации

Для добавления новой вкладки на странице детализации кампании:
1. Добавьте новый заголовок вкладки в блок `.tabs`
2. Добавьте содержимое вкладки

```html
<!-- Добавление в блок tabs -->
<div class="tab" data-tab="new_tab">Название новой вкладки</div>

<!-- Добавление содержимого вкладки -->
<div class="tab-content" id="tab-new_tab">
    <h4>Содержимое новой вкладки</h4>
    <!-- ... -->
</div>
```

### 3. Добавление новой метрики

Для добавления новой метрики:
1. Добавьте новую карточку в блок `.metric-cards`

```html
<div class="metric-card">
    <div class="metric-title">Название метрики</div>
    <div class="metric-value">{{ "%.2f"|format(value) }}</div>
    <div class="metric-change {% if change > 0 %}positive{% else %}negative{% endif %}">
        {{ "%.1f"|format(change) }}%
    </div>
</div>
```

### 4. Добавление новой таблицы

Для добавления новой таблицы используйте существующую структуру:
1. Блок с элементами управления `.table-controls`
2. Контейнер таблицы `.table-container`
3. Таблица с заголовком и телом
4. Блок пагинации `.pagination`

### 5. Расширение JavaScript-функциональности

При добавлении нового JavaScript-кода:
1. Следуйте модульной структуре, создавая отдельные функции
2. Регистрируйте обработчики в функции инициализации
3. Используйте существующие функции в качестве образца

### 6. Добавление модальных окон

Для добавления модальных окон:
1. Добавьте HTML-код модального окна
2. Добавьте CSS-стили в `style.css`
3. Добавьте JavaScript-функции для открытия/закрытия окна

```html
<!-- Модальное окно -->
<div class="modal" id="example-modal">
    <div class="modal-content">
        <div class="modal-header">
            <h4>Заголовок модального окна</h4>
            <button class="close">&times;</button>
        </div>
        <div class="modal-body">
            <!-- Содержимое модального окна -->
        </div>
        <div class="modal-footer">
            <button class="button">Подтвердить</button>
            <button class="button button-secondary modal-close">Отмена</button>
        </div>
    </div>
</div>
```

### 7. Рекомендации по валидации форм

Для валидации форм:
1. Используйте атрибуты HTML5 (`required`, `pattern`, `min`, `max`)
2. Добавьте классы для стилизации состояний валидации
3. Добавьте JavaScript-функции для проверки данных перед отправкой

### 8. Рекомендации по адаптивности

При разработке новых страниц и компонентов:
1. Используйте относительные единицы измерения (%, em, rem)
2. Тестируйте на различных устройствах и разрешениях
3. Используйте медиа-запросы для адаптации интерфейса

```css
@media (max-width: 768px) {
    /* Стили для планшетов */
}

@media (max-width: 480px) {
    /* Стили для мобильных устройств */
}
```

---

### Заключение

Данная архитектура интерфейса обеспечивает хорошую основу для расширения функциональности приложения. При разработке новых компонентов рекомендуется следовать существующим паттернам и принципам, чтобы сохранить целостность и единообразие интерфейса.

При возникновении вопросов или необходимости в дополнительной документации, обращайтесь к автору документации или обновляйте данный документ по мере развития проекта.