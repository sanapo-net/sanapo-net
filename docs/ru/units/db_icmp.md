---
name: DB_ICMP
module_class: '[[DbIcmp.class]]'
tier: '[[db_history.tier]]'
thread: '[[db_icmp.thread]]'
is_persistent: true
needs_decision: []
roadmap_idea:
- после версии 1 добавить поддержку быстрых СУБД
---

# Юнит: DB_ICMP

## Данные
Модульный класс:
Поток:
Слой:

## Описание
Главный интерфейс для работы с базами данных метрик ICMP. 
Отвечает за надежное сохранение, хранение и выдачу истории результатов сканирования сетевых устройств. 
Юнит полностью управляет набором баз данных: [[icmp_raw.database]], [[icmp_10m.database]], [[icmp_hours.database]], [[icmp_days.database]], [[icmp_10m_long.database]], [[icmp_10m_hours.database]].


[список юнитов](./index.md)