---
name: SCANNER_ICMP
module_class: '[[ScannerIcmpManager.class]]'
tier: '[[Scanners.tier]]'
thread: '[[scanner_icmp.thread]]'
is_persistent: true
needs_decision: []
roadmap_idea: ["изменение темпа сканировавания по команде анализатора"]
---

# Юнит: SCANNER_ICMP

## Данные
Модульный класс: [ScannerIcmpManager](../spec/module_classes/scanner_icmp_manager.md)
Поток: SCANNER_ICMP
Слой: SCANNERS

## Описание
Сканирует сеть по протоколу ICMP и отправляет сообщения-события с результатами сканирования в главную шину фреймворка [[sanapo.fw]].

Данные для сканирования получает по событию `NEW_NETWORK_VER`  из юнита сети [[network.unit.md]] в словаре snapshot `dict[str, any] = {"ver":0, "tab":{}}`, где `tab` это словарь словарей с данными о хостах: кюч это `uid` интерфейса девайса сети, а значение это данные о хосте (uid_dev, ip, mac, priority, timeout, interval).

По команде пользователя может ускорять темп (уменьшать интервал) и замедлять темп (увеличивать интервал) сканирования в два раза (событие `NEW_ICMP_RATE`).

Модуль содержит цикл с таймером, который генерирует события тиков (тики от 0.5 до 120 сек) а так же "каледарные" 10-минутки.

Содержит вспомогательный класс собственно сканера [ScannerICMP](../spec/utility_classes/scanner_icmp.md) и вспомогательные объекты менеджера потоков (класс [ThreadPoolManager](../spec/utility_classes/scanners.md#threadpoolmanager))и Сторожевого пса этих потоков (класс [PoolWatchdog](../spec/utility_classes/scanners.md#poolwatchdog)).

Поддерживает сканирование разных устройств с разным интервалом и таймаутом.

В будущем планируется добавление функционала динамического изменения темпа сканирования для всех, или группы, или одного конкретного устройства по команде внешнего юнита - например, анализатора [[analysator.unit.md]] (#future).
