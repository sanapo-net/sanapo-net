# tests/sanapo/main.py
import time
import argparse
from tests.sanapo.infra import TestLedger, setup_config
from tests.sanapo.local_tests import (
    test_start_stop_system,
    test_send_local_evt,
    test_send_local_cmd,
    test_kernel_create_methods,
    test_thread_types,
    test_tier_creating,
    test_random_create,
    test_def_thread_tier_for_unit,
    test_boot_master_tier_retry,
    test_boot_master_global_restart,
    test_boot_master_skip_dead_tier,
    test_boot_master_shutdown_stuck,
    test_watchdog_module_reborn,
    test_watchdog_unit_reborn,
    test_watchdog_thread_reborn,
    test_secretary_report_transaction,
    test_secretary_execution_speed,
    test_secretary_invalid_addressing,
    test_secretary_advanced_callbacks,
)
from tests.sanapo.network_tests import (
    test_network_handshake_integrity,
    test_network_auto_discovery,
    test_network_command_exchange,
    test_network_service_discovery,
)

def run_test_node(node_name: str):
    setup_config(node_name)
    ledger = TestLedger(node_name)

    if node_name == "ALPHA":
        # Local tests
        #"""
        test_start_stop_system(ledger, node_name)
        test_send_local_evt(ledger, node_name)
        test_send_local_cmd(ledger, node_name)
        test_kernel_create_methods(ledger, node_name)
        test_thread_types(ledger, node_name)
        test_tier_creating(ledger, node_name)
        test_random_create(ledger, node_name, 1)
        test_def_thread_tier_for_unit(ledger, node_name)
        test_boot_master_tier_retry(ledger, node_name)
        test_boot_master_global_restart(ledger, node_name)
        test_boot_master_skip_dead_tier(ledger, node_name)
        test_boot_master_shutdown_stuck(ledger, node_name)
        test_watchdog_module_reborn(ledger, node_name)
        test_watchdog_unit_reborn(ledger, node_name)
        test_watchdog_thread_reborn(ledger, node_name)
        test_secretary_report_transaction(ledger, node_name)
        test_secretary_execution_speed(ledger, node_name)
        test_secretary_invalid_addressing(ledger, node_name)
        test_secretary_advanced_callbacks(ledger, node_name)
        #"""
        # Network tests (run both roles, but BETA must be started separately)
        nodes = ["ALPHA", "BETA"]
        test_network_handshake_integrity(ledger, node_name, nodes),
        test_network_auto_discovery(ledger, node_name, nodes)
        test_network_command_exchange(ledger, node_name, nodes)
        test_network_service_discovery(ledger, node_name, nodes)
        #"""
        ledger.print_results()
    else:   # BETA
        nodes = ["ALPHA", "BETA"]
        test_network_handshake_integrity(ledger, node_name, nodes),
        test_network_auto_discovery(ledger, node_name, nodes)
        test_network_command_exchange(ledger, node_name, nodes)
        test_network_service_discovery(ledger, node_name, nodes)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sanapo Discrete Fuzzing Suite")
    parser.add_argument("node", choices=["ALPHA", "BETA"], help="Node Name")
    args = parser.parse_args()
    run_test_node(args.node)