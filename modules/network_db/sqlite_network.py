# modules/network_db/sqlite_network.py
import json
import sqlite3 as sql
from modules.network.network import Network
from modules.network_db.support_thing import Support
from sanapo.logger import Logger


class NetworkSQlite:

    def open_db(self, filepath: str) -> sql.Connection:
        sql.register_adapter(dict, json.dumps)
        sql.register_adapter(list, json.dumps)
        connection = sql.connect(filepath)
        cursor = sql.Cursor(connection)
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Networks (
                schema_version TEXT,
                uid INTEGER,
                name TEXT,
                name_u TEXT)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Devices (
                uid INTEGER,
                type TEXT,
                priority TEXT,
                ifaces dict,
                name TEXT,
                name_u TEXT,
                tags TEXT,
                os TEXT,
                brand TEXT,
                dnsname TEXT)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Ifaces (
                uid INTEGER,
                type TEXT,
                device INTEGER,
                speed INTEGER,
                priority TEXT,
                name TEXT,
                name_u TEXT,
                ip TEXT,
                mac TEXT,
                ip_is_dynamic BOOL,
                mac_is_dynamic BOOL,
                icmp_timeout FLOAT,
                icmp_interval BOOL,
                links dict,
                opened_ports dict)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Links (
                uid INTEGER,
                ifaces dict,
                type TEXT,
                speed INTEGER,
                priority TEXT,
                name TEXT)
            """)

            return connection
        except Exception as e:
            Logger.err("Failed to create or open database: {e}", e=e)

    def close_db(self, conn: sql.Connection):
        try:
            conn.commit()
            conn.close()
        except Exception as e:
            Logger.err("Can't close db connection correctly: {e}", e=e)

    def backup_db(self, source_path: str, backup_path: str):
        source_connection = sql.connect(source_path)
        backup_connection = sql.connect(backup_path)

        try:
            with backup_connection:
                source_connection.backup(backup_connection)
        finally:
            backup_connection.close()
            source_connection.close()

    def vacuum_db(self, conn):
        cursor = sql.Cursor(conn)
        try:
            cursor.execute("VACUUM")
            conn.close()
        except Exception as e:
            Logger.err("Can't vacuum file: {e}", e=e)

    def import_from_sqlite(self, db_path: str) -> Network:
        conn = self.open_db(db_path)
        conn.row_factory = sql.Row
        cursor = sql.Cursor(conn)

        try:
            cursor.execute("SELECT * FROM Networks LIMIT 1")
            net_row = cursor.fetchone()
            if not net_row:
                self.close_db(conn)
                return None

            cursor.execute("SELECT * FROM Devices")
            devices_rows = cursor.fetchall()

            cursor.execute("SELECT * FROM Ifaces")
            ifaces_rows = cursor.fetchall()

            cursor.execute("SELECT * FROM Links")
            links_rows = cursor.fetchall()

            data = {
                "schema_version": net_row["schema_version"],
                "network_uid": net_row["uid"],
                "name": net_row["name"],
                "name_u": net_row["name_u"],
                "devices": [],
                "ifaces": [],
                "links": [],
            }

            for row in devices_rows:
                dev = dict(row)
                dev["ifaces"] = (
                    json.loads(dev["ifaces"]) if dev["ifaces"] else []
                )
                data["devices"].append(dev)

            for row in ifaces_rows:
                iface = dict(row)
                iface["links"] = (
                    json.loads(iface["links"]) if iface["links"] else []
                )
                iface["opened_ports"] = (
                    json.loads(iface["opened_ports"])
                    if iface["opened_ports"]
                    else {}
                )
                data["ifaces"].append(iface)

            for row in links_rows:
                lnk = dict(row)
                lnk["ifaces"] = (
                    json.loads(lnk["ifaces"]) if lnk["ifaces"] else []
                )
                data["links"].append(lnk)

            self.close_db(conn)

            support = Support()
            return support.create_network(data)

        except Exception as e:
            Logger.err("Import from sqlite failed: {e}", e=e)
            self.close_db(conn)
            return None

    def export_to_sqlite(self, network: Network, db_path: str) -> bool:
        support = Support()
        dicted_network = support.network_to_dict(network)
        dicted_devices = dicted_network.get("devices", [])
        dicted_ifaces = dicted_network.get("ifaces", [])
        dicted_links = dicted_network.get("links", [])

        try:
            conn = self.open_db(db_path)
            cursor = sql.Cursor(conn)

            with conn:
                cursor.execute(
                    "INSERT INTO Networks "
                    "(schema_version, uid, name, name_u) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        dicted_network.get("schema_version"),
                        dicted_network.get("uid"),
                        dicted_network.get("name"),
                        dicted_network.get("name_u"),
                    ),
                )

                if dicted_devices:
                    cursor.executemany(
                        "INSERT INTO Devices (uid, type, priority, "
                        "ifaces, name, name_u, tags, os, brand, dnsname) "
                        "VALUES (:uid, :type, :priority, :ifaces, :name, "
                        ":name_u, :tags, :os, :brand, :dnsname)",
                        dicted_devices,
                    )

                if dicted_ifaces:
                    cursor.executemany(
                        "INSERT INTO Ifaces (uid, type, device, speed, "
                        "priority, name, name_u, ip, mac, ip_is_dynamic, "
                        "mac_is_dynamic, icmp_timeout, icmp_interval, "
                        "links, opened_ports) VALUES (:uid, :type, :device, "
                        ":speed, :priority, :name, :name_u, :ip, :mac, "
                        ":ip_is_dynamic, :mac_is_dynamic, :icmp_timeout, "
                        ":icmp_interval, :links, :opened_ports)",
                        dicted_ifaces,
                    )

                if dicted_links:
                    cursor.executemany(
                        "INSERT INTO Links (uid, ifaces, type, speed, "
                        "priority, name) VALUES (:uid, :ifaces, :type, "
                        ":speed, :priority, :name)",
                        dicted_links,
                    )

            self.close_db(conn)
            return True

        except Exception as e:
            Logger.err("Export to sqlite failed: {e}", e=e)
            return False
