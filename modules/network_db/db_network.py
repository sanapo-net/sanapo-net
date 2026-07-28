# modules/network_db/db_network.py
from modules.network.network import Network
from modules.network_db.csv_network import NetworkCSV
from modules.network_db.json_network import NetworkJSON
from modules.network_db.sqlite_network import NetworkSQlite

class NetworkDB():
    def save_network(self, network: Network, path: str):
        csv = NetworkCSV()
        json = NetworkJSON()
        sql = NetworkSQlite()

        csv.save_network(network, path)
        json.save_json(network, path)
        sql.export_to_sqlite(network, path)

    def load_network(self, path: str) -> Network:
        csv = NetworkCSV()
        json = NetworkJSON()
        sql = NetworkSQlite()

        csv.load_network(path)
        json.load_json(path)
        sql.import_from_sqlite(path)
        # idk what way needed to be return