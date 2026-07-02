# Спецификация: Вспомогательные классы, для ManagerDbNetwork (CsvStorageNetwork, JsonStorageNetwork, SqliteStorageNetwork)



# CsvStorageNetwork
файл: modules/db_network/csv_storage_network.py

## Общее
Класс отвечает за сериализацию иерархического объекта Network в три плоские CSV‑таблицы и обратное восстановление графа сети из этих таблиц.
Формат: UTF‑8, разделитель — запятая, первая строка — заголовки столбцов.

## Методы
- `save_network_to_csv(network: Network, folder_path: str) -> bool`
Создаёт в указанной папке три файла:
- `devices.csv`, `ifaces.csv`, `links.csv`
Каждый файл содержит все поля соответствующего дата‑класса (Device, Iface, Link).
Ссылочные поля записываются в виде целых чисел или строк с разделителями.
Возвращает True при успешной записи всех файлов.

- `load_network_from_csv(folder_path: str) -> Network`
Читает три CSV‑файла из папки, восстанавливает объекты Device, Iface, Link и строит объект Network с корректными связями.
При отсутствии какого‑либо файла или нарушении структуры выбрасывает исключение (или возвращает None с предварительным логированием ошибки).

- `dict_to_device(row: dict) -> Device` (внутренний)
- `dict_to_iface(row: dict, devices: dict[int, Device]) -> Iface`
- `dict_to_link(row: dict, ifaces: dict[int, Iface]) -> Link`
Вспомогательные методы для преобразования словаря (строки CSV) в объекты дата‑классов с восстановлением перечислений и связей.

## Особенности реализации
- Значения Enum записываются как их .value (строка), при чтении выполняется обратное преобразование.
- Связь Iface → Device хранится в виде колонки device_uid.
- Связь Link → Iface хранится в колонке iface_uids, где UID интерфейсов перечислены через пробел.
- Порядок восстановления: сначала загружаются устройства, затем интерфейсы (с привязкой к устройствам), затем линки (с привязкой к интерфейсам).
- При экспорте порядок записей не гарантирован, но заголовки столбцов строго фиксированы.



# JsonStorageNetwork
файл: modules/db_network/json_storage_network.py

## Общее
Отвечает за корректную сериализацию Network в JSON-формат и обратное преобразование. Учитывает особенности дата-классов (Device, Iface, Link) и вложенных объектов (enums, ссылки на другие объекты).

## Методы
- `network_to_dict(network: Network) -> dict`
Рекурсивно обходит граф сети и строит словарь, пригодный для json.dump. Включает метаданные: версия схемы, временная метка, идентификаторы сети.
Пример структуры:
```json
{
    "schema_version": "1.0",
    "network_uid": 1,
    "network_name": "example",
    "devices": [ ... ],
    "ifaces": [ ... ],
    "links": [ ... ]
}
```
- `dict_to_network(data: dict) -> Network`
Восстанавливает Network из словаря, выполняя валидацию версии и целостности ссылок.
- `save_json(network: Network, filepath: str)` — открывает файл и записывает JSON с отступами.
- `load_json(filepath: str) -> Network` — читает файл и возвращает Network.

## Особенности
- При сериализации объектов типа Enum записывается их значение (value).
- Взаимные ссылки между объектами заменяются на UID с последующим восстановлением.
- Поддерживается потоковая запись больших сетей (по желанию).



# SqliteStorageNetwork
файл: modules/db_network/sqlite_storage_network.py

## Общее
Дополняет SqlStorageNetwork функциями, специфичными для SQLite: управление файлом БД, настройка PRAGMA, резервное копирование, проверка целостности.

## Методы
- `open_db(filepath: str) -> sqlite3.Connection` — открывает (или создаёт) файл БД, применяет рекомендованные настройки (WAL-режим, foreign_keys=ON).
- `close_db(conn: sqlite3.Connection)` — корректно закрывает соединение.
- `backup_db(source_path: str, backup_path: str)` — создаёт резервную копию БД через SQLite Backup API.
- `vacuum_db(conn)` — оптимизирует файл БД.
- `import_from_sqlite(db_path: str) -> Network` — высокоуровневый метод, объединяющий открытие БД, вызов SqlStorageNetwork для загрузки данных и закрытие.
- `export_to_sqlite(network: Network, db_path: str) -> bool` — аналогично для экспорта.


[список вспомогательных классов](./index.md)