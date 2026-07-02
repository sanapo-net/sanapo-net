---
name: DB_NETWORK
module_class: '[[DbManagerNetwork.class]]'
tier: '[[db_network.tier]]'
thread: '[[db_network.thread]]'
is_persistent: true
needs_decision: []
roadmap_idea: []
---

# Юнит: NETWORK_DB

# Данные
Модульный класс: [ManagerDbNetwork](../spec/module_classes/db_manager_network.md)
Поток: DB_NETWORK
Слой: DB_NETWORK

# Описание
Модуль DB_NETWORK реализует универсальный механизм конвертации иерархической сетевой топологии (объекта Network) в плоские представления (CSV, SQLite, JSON) и обратное восстановление. Основной класс DbManagerNetwork предоставляет высокоуровневый интерфейс экспорта/импорта, скрывая детали форматов. 

Модуль является ZOMBIE-юнитом (постоянный, событийно-управляемый). Все операции экспорта/импорта вызываются по запросу других модулей через открытые методы.