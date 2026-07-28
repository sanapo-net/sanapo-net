# modules/network_db/csv_network.py
import csv
from modules.network.network import Network
from modules.network_db.support_thing import Support

class NetworkCSV():
    def load_network(self, path: str) -> Network:
        support = Support()
        network_table = {}
        with open(f"{path}/network.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                network_table = {
                    "schema_version": row.get("schema_version"),
                    "uid": row.get("uid"),
                    "name": row.get("name"),
                    "name_u": row.get("name_u"),
                    "devices": [],
                    "ifaces": [],
                    "links": []
                }
                break

        try:
            with open(f"{path}/devices.csv", "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    device_data = {
                        "uid": row.get("uid"),
                        "type": row.get("type"),
                        "priority": int(row["priority"]) if row.get("priority") else 0,
                        "ifaces": row["ifaces"].split(";") if row.get("ifaces") else [],
                        "name": row.get("name"),
                        "name_u": row.get("name_u"),
                        "tags": row["tags"].split(";") if row.get("tags") else [],
                        "os": row.get("os"),
                        "brand": row.get("brand"),
                        "dnsname": row.get("dnsname")
                    }
                    network_table["devices"].append(device_data)
        except FileNotFoundError:
            pass

        try:
            with open(f"{path}/ifaces.csv", "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    iface_data = {
                        "uid": row.get("uid"),
                        "type": row.get("type"),
                        "device": row.get("device"),
                        "speed": int(row["speed"]) if row.get("speed") else 0,
                        "priority": int(row["priority"]) if row.get("priority") else 0,
                        "name": row.get("name"),
                        "name_u": row.get("name_u"),
                        "ip": row.get("ip"),
                        "mac": row.get("mac"),
                        "ip_is_dynamic": row.get("ip_is_dynamic") == "True",
                        "mac_is_dynamic": row.get("mac_is_dynamic") == "True",
                        "icmp_timeout": (
                            int(row["icmp_timeout"]) if row.get("icmp_timeout") else 0
                        ),
                        "icmp_interval": (
                            int(row["icmp_interval"]) if row.get("icmp_interval") else 0
                        ),
                        "links": (
                            row["links"].split(";") if row.get("links") else []
                        ),
                        "opened_ports": (
                            [int(p) for p in row["opened_ports"].split(";")]
                            if row.get("opened_ports") else []
                        )
                    }
                    network_table["ifaces"].append(iface_data)
        except FileNotFoundError:
            pass

        try:
            with open(f"{path}/links.csv", "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    link_data = {
                        "uid": row.get("uid"),
                        "ifaces": row["ifaces"].split(";") if row.get("ifaces") else [],
                        "type": row.get("type"),
                        "speed": int(row["speed"]) if row.get("speed") else 0,
                        "priority": int(row["priority"]) if row.get("priority") else 0,
                        "name": row.get("name")
                    }
                    network_table["links"].append(link_data)
        except FileNotFoundError:
            pass

        return support.create_network(network_table)

    def save_network(self, network: Network, path: str):
        support = Support()
        dicted_network = support.network_to_dict(network)

        dicted_devices = dicted_network.get("devices", [])
        dicted_ifaces = dicted_network.get("ifaces", [])
        dicted_links = dicted_network.get("links", [])
        
        cleared_network = {
            "schema_version": dicted_network.get("schema_version"),
            "uid": dicted_network.get("uid"),
            "name": dicted_network.get("name"),
            "name_u": dicted_network.get("name_u"),
            "devices": ";".join([str(d["uid"]) for d in dicted_devices if "uid" in d]),
            "ifaces": ";".join([str(i["uid"]) for i in dicted_ifaces if "uid" in i]),
            "links": ";".join([str(l["uid"]) for l in dicted_links if "uid" in l])
        }
        
        with open(f"{path}/network.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(cleared_network.keys()), quoting=csv.QUOTE_NONNUMERIC)
            writer.writeheader()
            writer.writerow(cleared_network)

        if dicted_devices:
            flat_devices = []
            for d in dicted_devices:
                flat_d = d.copy()
                flat_d["ifaces"] = ";".join(map(str, d.get("ifaces", [])))
                flat_d["tags"] = ";".join(map(str, d.get("tags", [])))
                flat_devices.append(flat_d)
                
            with open(f"{path}/devices.csv", "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(flat_devices[0].keys()), quoting=csv.QUOTE_NONNUMERIC)
                writer.writeheader()
                writer.writerows(flat_devices)

        if dicted_ifaces:
            flat_ifaces = []
            for i in dicted_ifaces:
                flat_i = i.copy()
                flat_i["links"] = ";".join(map(str, i.get("links", [])))
                flat_i["opened_ports"] = ";".join(map(str, i.get("opened_ports", [])))
                flat_ifaces.append(flat_i)
                
            with open(f"{path}/ifaces.csv", "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(flat_ifaces[0].keys()), quoting=csv.QUOTE_NONNUMERIC)
                writer.writeheader()
                writer.writerows(flat_ifaces)

        if dicted_links:
            flat_links = []
            for l in dicted_links:
                flat_l = l.copy()
                flat_l["ifaces"] = ";".join(map(str, l.get("ifaces", [])))
                flat_links.append(flat_l)
                
            with open(f"{path}/links.csv", "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(flat_links[0].keys()), quoting=csv.QUOTE_NONNUMERIC)
                writer.writeheader()
                writer.writerows(flat_links)