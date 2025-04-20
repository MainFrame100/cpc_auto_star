/**
 * CPC Auto Helper - Основные интерактивные функции
 */

// Инициализация при загрузке DOM
document.addEventListener('DOMContentLoaded', function() {
    initTabs();
    initPeriodSelector();
    initTableControls();
    initPagination();
    initSortableTables();
    initFlashMessages();
});

/**
 * Функция инициализации табов
 */
function initTabs() {
    const tabs = document.querySelectorAll('.tab');
    if (tabs.length === 0) return;
    
    tabs.forEach(tab => {
        tab.addEventListener('click', function() {
            // Удаляем active со всех вкладок
            tabs.forEach(t => t.classList.remove('active'));
            
            // Добавляем active к текущей вкладке
            this.classList.add('active');
            
            // Скрываем все содержимое вкладок
            const tabContents = document.querySelectorAll('.tab-content');
            tabContents.forEach(content => content.classList.remove('active'));
            
            // Показываем содержимое текущей вкладки
            const tabId = 'tab-' + this.getAttribute('data-tab');
            const activeContent = document.getElementById(tabId);
            if (activeContent) {
                activeContent.classList.add('active');
            }
        });
    });
}

/**
 * Функция инициализации переключателя периодов
 */
function initPeriodSelector() {
    const periodOptions = document.querySelectorAll('.period-option');
    if (periodOptions.length === 0) return;
    
    periodOptions.forEach(option => {
        option.addEventListener('click', function() {
            // Удаляем active со всех опций
            periodOptions.forEach(o => o.classList.remove('active'));
            
            // Добавляем active к текущей опции
            this.classList.add('active');
            
            // Получаем выбранный период
            const selectedPeriod = this.getAttribute('data-period');
            
            // Скрываем все содержимое периодов
            const periodContents = document.querySelectorAll('.period-data');
            periodContents.forEach(content => content.style.display = 'none');
            
            // Показываем содержимое выбранного периода
            document.querySelectorAll(`[data-period-content="${selectedPeriod}"]`).forEach(content => {
                content.style.display = 'block';
            });
        });
    });
}

/**
 * Функции для работы с таблицами (чекбоксы, поиск, фильтры)
 */
function initTableControls() {
    // Обработка чекбоксов "Выбрать все"
    const selectAllCheckboxes = document.querySelectorAll('.select-all');
    selectAllCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            const table = this.closest('table');
            const checkboxes = table.querySelectorAll('tbody input[type="checkbox"]');
            checkboxes.forEach(cb => cb.checked = this.checked);
        });
    });
    
    // Простой поиск по таблице площадок
    const placementsSearch = document.getElementById('placements-search');
    if (placementsSearch) {
        placementsSearch.addEventListener('keyup', function() {
            filterTable(this, '.placements-table', 2); // 2 - индекс колонки с названием площадки
        });
    }
    
    // Поиск по таблице запросов
    const queriesSearch = document.getElementById('queries-search');
    if (queriesSearch) {
        queriesSearch.addEventListener('keyup', function() {
            filterTable(this, '.queries-table', 1); // 1 - индекс колонки с текстом запроса
        });
    }
    
    // Поиск по таблице кампаний
    const campaignSearch = document.getElementById('campaign-search');
    if (campaignSearch) {
        campaignSearch.addEventListener('keyup', function() {
            filterTable(this, '#campaigns-table', 0); // 0 - индекс колонки с названием кампании
        });
    }
    
    // Изменение количества строк на странице
    const rowsPerPageSelectors = document.querySelectorAll('select[id$="-per-page"]');
    rowsPerPageSelectors.forEach(selector => {
        selector.addEventListener('change', function() {
            const tableSelector = '.' + this.id.replace('-per-page', '-table');
            const table = this.closest('.tab-content').querySelector(tableSelector);
            if (!table) return;
            
            // В реальном приложении здесь была бы логика пагинации
            // Для демо просто выводим сообщение
            console.log(`Изменено количество строк на странице для ${tableSelector}: ${this.value}`);
        });
    });
    
    // Фильтрация по типу кампании и статусу
    const campaignTypeFilter = document.getElementById('campaign-filter');
    const campaignStatusFilter = document.getElementById('campaign-status');
    
    if (campaignTypeFilter) {
        campaignTypeFilter.addEventListener('change', function() {
            applyTableFilters();
        });
    }
    
    if (campaignStatusFilter) {
        campaignStatusFilter.addEventListener('change', function() {
            applyTableFilters();
        });
    }
}

/**
 * Функция фильтрации таблицы
 */
function filterTable(inputElement, tableSelector, columnIndex) {
    const searchValue = inputElement.value.toLowerCase();
    const table = inputElement.closest('.tab-content, .card')
        .querySelector(tableSelector);
    
    if (!table) return;
    
    const rows = table.querySelectorAll('tbody tr');
    
    rows.forEach(row => {
        if (row.cells.length <= columnIndex) return;
        
        const cellText = row.cells[columnIndex].textContent.toLowerCase();
        if (cellText.includes(searchValue)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

/**
 * Функция применения составных фильтров для таблицы кампаний
 */
function applyTableFilters() {
    const typeFilter = document.getElementById('campaign-filter');
    const statusFilter = document.getElementById('campaign-status');
    
    if (!typeFilter || !statusFilter) return;
    
    const typeValue = typeFilter.value;
    const statusValue = statusFilter.value;
    
    const rows = document.querySelectorAll('#campaigns-table tbody tr');
    
    rows.forEach(row => {
        const rowType = row.getAttribute('data-campaign-type');
        const rowStatus = row.getAttribute('data-campaign-status');
        
        const typeMatch = typeValue === 'all' || rowType === typeValue;
        const statusMatch = statusValue === 'all' || rowStatus === statusValue;
        
        if (typeMatch && statusMatch) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

/**
 * Функция инициализации пагинации
 */
function initPagination() {
    const paginationLinks = document.querySelectorAll('.pagination a');
    if (paginationLinks.length === 0) return;
    
    paginationLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const pageItems = document.querySelectorAll('.pagination li');
            pageItems.forEach(item => item.classList.remove('active'));
            
            // Если это не кнопки "Назад" и "Вперед"
            if (!this.classList.contains('prev-page') && !this.classList.contains('next-page')) {
                this.parentElement.classList.add('active');
            }
            
            // В реальном приложении здесь была бы логика обработки пагинации
            console.log(`Переход на страницу: ${this.textContent}`);
        });
    });
}

/**
 * Функция для сортируемых таблиц
 */
function initSortableTables() {
    const sortableHeaders = document.querySelectorAll('.sortable');
    if (sortableHeaders.length === 0) return;
    
    sortableHeaders.forEach(header => {
        header.addEventListener('click', function() {
            const table = this.closest('table');
            const sortBy = this.getAttribute('data-sort');
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            
            // Проверяем текущее направление сортировки
            const isAscending = !this.classList.contains('sort-asc');
            
            // Сбрасываем все классы сортировки
            table.querySelectorAll('.sortable').forEach(h => {
                h.classList.remove('sort-asc', 'sort-desc');
            });
            
            // Устанавливаем новый класс сортировки
            this.classList.add(isAscending ? 'sort-asc' : 'sort-desc');
            
            // Сортируем строки
            rows.sort((a, b) => {
                const headerIndex = Array.from(header.parentNode.children).indexOf(header);
                let aValue = a.cells[headerIndex] ? a.cells[headerIndex].textContent.trim() : '';
                let bValue = b.cells[headerIndex] ? b.cells[headerIndex].textContent.trim() : '';
                
                // Для числовых колонок
                if (header.classList.contains('numeric')) {
                    // Удаляем все нечисловые символы
                    aValue = parseFloat(aValue.replace(/[^\d.-]/g, '')) || 0;
                    bValue = parseFloat(bValue.replace(/[^\d.-]/g, '')) || 0;
                }
                
                if (isAscending) {
                    return aValue > bValue ? 1 : -1;
                } else {
                    return aValue < bValue ? 1 : -1;
                }
            });
            
            // Перестраиваем таблицу
            const tbody = table.querySelector('tbody');
            rows.forEach(row => tbody.appendChild(row));
        });
    });
}

/**
 * Обработка flash-сообщений
 */
function initFlashMessages() {
    const closeButtons = document.querySelectorAll('.flash-message .close');
    if (closeButtons.length === 0) return;
    
    closeButtons.forEach(button => {
        button.addEventListener('click', function() {
            const flashMessage = this.closest('.flash-message');
            if (flashMessage) {
                flashMessage.style.display = 'none';
            }
        });
    });
    
    // Автоматическое скрытие flash-сообщений через 5 секунд
    setTimeout(() => {
        document.querySelectorAll('.flash-message:not(.flash-danger)').forEach(message => {
            message.style.opacity = '0';
            message.style.transition = 'opacity 0.5s ease';
            setTimeout(() => {
                message.style.display = 'none';
            }, 500);
        });
    }, 5000);
}

/**
 * Функция для кнопки экспорта CSV
 * @param {string} endpoint - URL для запроса CSV
 * @param {Array} selectedIds - Массив ID выбранных элементов
 */
function exportCSV(endpoint, selectedIds = []) {
    // В реальном приложении здесь был бы запрос на скачивание CSV
    console.log(`Запрос на экспорт CSV: ${endpoint}, выбранные ID: ${selectedIds.join(',')}`);
    
    // Имитация клика по скрытой ссылке для скачивания
    const link = document.createElement('a');
    link.href = endpoint + (selectedIds.length > 0 ? `?ids=${selectedIds.join(',')}` : '');
    link.target = '_blank';
    link.download = 'export.csv';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * Функция для блокировки площадок / добавления минус-слов
 * @param {string} action - Тип действия ('block_placements' или 'add_negative_keywords')
 * @param {Array} selectedItems - Массив выбранных элементов
 */
function performAction(action, selectedItems = []) {
    if (selectedItems.length === 0) {
        alert('Не выбрано ни одного элемента');
        return;
    }
    
    const confirmMessage = action === 'block_placements' 
        ? `Вы уверены, что хотите заблокировать ${selectedItems.length} площадок?`
        : `Вы уверены, что хотите добавить ${selectedItems.length} запросов в минус-слова?`;
    
    if (confirm(confirmMessage)) {
        // В реальном приложении здесь был бы AJAX-запрос
        console.log(`Выполнение действия ${action} для элементов: ${selectedItems.join(', ')}`);
        alert('Действие успешно выполнено!');
    }
}