# modules/network_db/support_thing.py
from modules.network.network import Network
from modules.network.device import Device
from modules.network.iface import Iface
from modules.network.link import Link
from sanapo.logger import Logger

class Support:
    """Dict -> Network | Network -> Dict\n
    That module needs for remove repeating in another files in modules/network_db/example.py
    """
    def create_network(self, data: dict) -> Network:
        if data.get("schema_version") != "1.0":
            Logger.wrn("Failed to load older version!")

        devices_dict = {}
        ifaces_dict = {}
        links_dict = {}

        # Creating objects from data
        for device_data in data.get("devices", []):
            device = Device(
                uid = device_data["uid"],
                type = device_data["type"],
                priority = device_data["priority"],
                ifaces = [],
                name = device_data["name"],
                name_u = device_data["name_u"],
                tags = device_data["tags"],
                os = device_data["os"],
                brand = device_data["brand"],
                dnsname = device_data["dnsname"]
            )
            devices_dict[device.uid] = device

        for iface_data in data.get("ifaces", []):
            iface = Iface(
                uid = iface_data["uid"],
                type = iface_data["type"],
                speed = iface_data["speed"],
                priority = iface_data["priority"],
                name = iface_data["name"],
                name_u = iface_data["name_u"],
                ip = iface_data["ip"],
                mac = iface_data["mac"],
                ip_is_dynamic = iface_data["ip_is_dynamic"],
                mac_is_dynamic = iface_data["mac_is_dynamic"],
                icmp_timeout = iface_data["icmp_timeout"],
                icmp_interval = iface_data["icmp_interval"],
                links = [],
                opened_ports = list(iface_data.get("opened_ports", []))
            )
            ifaces_dict[iface.uid] = iface

        for link_data in data.get("links", []):
            link = Link(
                uid = link_data["uid"],
                ifaces = [],
                type = link_data["type"],
                speed = link_data["speed"],
                priority = link_data["priority"],
                name = link_data["name"]
            )
            links_dict[link.uid] = link

        # Creating "connection" between objects
        for device_data in data.get("devices", []):
            dev_obj = devices_dict[device_data["uid"]]
            for iface_id in device_data.get("ifaces", []):
                if iface_id in ifaces_dict:
                    dev_obj.ifaces.append(ifaces_dict[iface_id])

        for iface_data in data.get("ifaces", []):
            iface_obj = ifaces_dict[iface_data["uid"]]
            for link_id in iface_data.get("links", []):
                if link_id in links_dict:
                    iface_obj.links.append(links_dict[link_id])

        for link_data in data.get("links", []):
            link_obj = links_dict[link_data["uid"]]
            for iface_id in link_data.get("ifaces", []):
                if iface_id in ifaces_dict:
                    link_obj.ifaces.append(ifaces_dict[iface_id])

        return Network(
            uid = data.get("network_uid"),
            name = data.get("name"),
            name_u = data.get("name_u"),
            devices = list(devices_dict.values()),
            ifaces = list(ifaces_dict.values()),
            links = list(links_dict.values())
        )

    def network_to_dict(self, network: Network) -> dict:
        # Half filled network -> dict
        network_table = {
            "schema_version": "1.0",
            "uid": network.uid,
            "name": network.name,
            "name_u": network.name_u,
            "devices": [],
            "ifaces": [],
            "links": []
        }

        # Filling network -> dict fully
        for device in network.devices:
            device_data = {
                "uid": device.uid,
                "type": device.type,
                "priority": device.priority,
                "ifaces": [],
                "name": device.name,
                "name_u": device.name_u,
                "tags": device.tags,
                "os": device.os,
                "brand": device.brand,
                "dnsname": device.dnsname
            }
            for iface in device.ifaces:
                device_data["ifaces"].append(iface.uid)

            network_table["devices"].append(device_data)

        for iface in network.ifaces:
            iface_data = {
                "uid": iface.uid,
                "type": iface.type,
                "device": iface.device.uid,
                "speed": iface.speed,
                "priority": iface.priority,
                "name": iface.name,
                "name_u": iface.name_u,
                "ip": iface.ip,
                "mac": iface.mac,
                "ip_is_dynamic": iface.ip_is_dynamic,
                "mac_is_dynamic": iface.mac_is_dynamic,
                "icmp_timeout": iface.icmp_timeout,
                "icmp_interval": iface.icmp_interval,
                "links": [],
                "opened_ports": []
            }

            for link in iface.links:
                iface_data["links"].append(link.uid)

            for port in iface.opened_ports:
                iface_data["opened_ports"].append(port)

            network_table["ifaces"].append(iface_data)

        for link in network.links:
            link_data = {
                "uid": link.uid,
                "ifaces": [],
                "type": link.type,
                "speed": link.speed,
                "priority": link.priority,
                "name": link.name
            }

            for iface in link.ifaces:
                link_data["ifaces"].append(iface.uid)

            network_table["links"].append(link_data)

        return network_table