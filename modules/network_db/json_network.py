# modules/network_db/json_network.py
from modules.network.network import Network
from modules.network_db.support_thing import Support
import json

class NetworkJSON():

    def _dict_to_network(self, data: dict) -> Network:
        support = Support()
        return support.create_network(data)

    def save_json(self, network: Network, filepath: str):
        support = Support()
        network_table = support.network_to_dict(network)

        with open(filepath, "w") as file:
            json.dump(network_table, file, indent=4)

    def load_json(self, filepath: str) -> Network:
        with open(filepath, "r", encoding="utf-8") as file:
            data = json.load(file)

        return self.dict_to_network(data)