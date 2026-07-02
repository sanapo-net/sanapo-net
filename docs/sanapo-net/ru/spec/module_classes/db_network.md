# Спецификация: Модульный класс, ManagerDbNetwork

# Данные
файл: modules/db_network/manager_db_network.py
юнит: [DB_NETWORK](../../units/db_network.md)

# Основной класс DbManagerNetwork
Наследует BaseModule. Предоставляет следующие методы:

- `export_to_csv(network: Network, folder_path: str) -> bool`
Сохраняет сеть в три CSV-файла (devices.csv, ifaces.csv, links.csv) в указанную папку. Использует вспомогательный класс CsvStorageNetwork (не показан, но предполагается аналогичный).

- `import_from_csv(folder_path: str) -> Network`
Восстанавливает объект Network из CSV-файлов.

- `export_to_sqlite(network: Network, db_path: str) -> bool`
Экспорт в SQLite-базу данных. Создаёт (или перезаписывает) файл БД, вызывает SqlStorageNetwork для формирования таблиц и вставки данных, используя SqliteStorageNetwork для управления соединением.

- `import_from_sqlite(db_path: str) -> Network`
Читает БД SQLite и строит Network.

- `export_to_json(network: Network, file_path: str) -> bool`
Выгружает сеть в один JSON-файл с полной иерархией, используя JsonStorageNetwork.

- `import_from_json(file_path: str) -> Network`
Загружает Network из JSON-файла.

Все методы возвращают True/False или готовый объект Network. При ошибках логируются детали, и возвращается соответствующий признак неудачи.

Также класс может содержать вспомогательный метод `convert_format(input_path, output_path, from_fmt, to_fmt)` для прямой перегонки между форматами (например, CSV в SQLite).

# Внутренняя архитектура
ManagerDbNetwork при старте загружает конфигурацию путей по умолчанию (если требуется), но основная работа происходит в момент вызова методов. Для каждого формата создаётся экземпляр соответствующего хранилища (или используется статический метод), которому делегируется вся низкоуровневая работа.

Вся специфика работы с конкретным хранилищем делегируется вспомогательным классам:
- [CsvStorageNetwork](../utility_classes/network.md#csvstoragenetwork) — общие SQL-операции (создание таблиц, вставка/чтение записей) для любой БД с SQL-интерфейсом.
- [JsonStorageNetwork](../utility_classes/network.md#jsonstoragenetwork) — сериализация/десериализация Network в JSON и обратно.
- [SqliteStorageNetwork](../utility_classes/network.md#sqlitestoragenetwork) — специализированная работа с файловыми базами SQLite (управление соединениями, PRAGMA, бэкап).


[список модульных классов](./index.md)