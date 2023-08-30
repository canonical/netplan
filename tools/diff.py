import argparse
import json
from itertools import zip_longest

from rich.console import Console
from rich.table import Table

from netplan_cli.cli.state import SystemConfigState, NetplanConfigState
from netplan_cli.cli.state_diff import DiffJSONEncoder, NetplanDiffState

parser = argparse.ArgumentParser(
    prog='Diff',
    description='Demo tool for netplan diff')
parser.add_argument('-r', '--root-dir', default='/')
parser.add_argument('-t', '--table', action='store_true')
parser.add_argument('-j', '--json', action='store_true')


def print_table(diff: dict, **style: dict):
    main_table = Table.grid()

    if interfaces := diff.get('interfaces'):
        for iface, data in interfaces.items():
            name = data.get('name')
            id = data.get('id')

            missing_dhcp = data.get('missing_dhcp4_address', False)
            missing_dhcp = missing_dhcp or data.get('missing_dhcp6_address', False)
            # Skip interfaces without diff
            if not data.get('system_state') and not data.get('netplan_state') and not missing_dhcp:
                continue

            table = Table(expand=True, title=f'Interface: {name}\nNetplan ID: {id}', **style)
            table.add_column('Missing resources in Netplan\'s State', justify="center", ratio=2)
            table.add_column('Missing resources in System\'s State', justify="center", ratio=2)

            system_macaddress = data.get('system_state', {}).get('missing_macaddress')
            netplan_macaddress = data.get('netplan_state', {}).get('missing_macaddress')
            if system_macaddress or netplan_macaddress:
                table.add_section()
                table.add_row('MAC Address', 'MAC Address', style='magenta')
                table.add_row(netplan_macaddress, system_macaddress)

            system_addresses = data.get('system_state', {}).get('missing_addresses', [])
            netplan_addresses = data.get('netplan_state', {}).get('missing_addresses', [])
            missing_dhcp4 = data.get('system_state', {}).get('missing_dhcp4_address', False)
            missing_dhcp6 = data.get('system_state', {}).get('missing_dhcp6_address', False)

            if system_addresses or netplan_addresses or missing_dhcp4 or missing_dhcp6:
                table.add_section()
                table.add_row('Addresses', 'Addresses', style='magenta')

                if missing_dhcp4:
                    system_addresses.append('DHCPv4: missing IP')
                if missing_dhcp6:
                    system_addresses.append('DHCPv6: missing IP')

                for (ip1, ip2) in zip_longest(netplan_addresses, system_addresses):
                    table.add_row(ip1, ip2)

            system_nameservers = data.get('system_state', {}).get('missing_nameservers_addresses', [])
            netplan_nameservers = data.get('netplan_state', {}).get('missing_nameservers_addresses', [])

            if system_nameservers or netplan_nameservers:
                table.add_section()
                table.add_row('Nameservers', 'Nameservers', style='magenta')
                for (ns1, ns2) in zip_longest(netplan_nameservers, system_nameservers):
                    table.add_row(ns1, ns2)

            system_search = data.get('system_state', {}).get('missing_nameservers_search', [])
            netplan_search = data.get('netplan_state', {}).get('missing_nameservers_search', [])

            if system_search or netplan_search:
                table.add_section()
                table.add_row('Search domains', 'Search domains', style='magenta')
                for (search1, search2) in zip_longest(netplan_search, system_search):
                    table.add_row(search1, search2)

            system_routes = data.get('system_state', {}).get('missing_routes', [])
            netplan_routes = data.get('netplan_state', {}).get('missing_routes', [])

            if system_routes or netplan_routes:
                table.add_section()
                table.add_row('Routes', 'Routes', style='magenta', end_section=True)
                for (route1, route2) in zip_longest(netplan_routes, system_routes):
                    table.add_row(str(route1) if route1 else None, str(route2) if route2 else None)

            if data.get('netplan_state') or data.get('system_state'):
                main_table.add_section()
                main_table.add_row(table, end_section=True)

    # Add missing interfaces to the grid
    missing_interfaces_system = diff.get('missing_interfaces_system', {})
    missing_interfaces_netplan = diff.get('missing_interfaces_netplan', {})
    if missing_interfaces_system or missing_interfaces_netplan:
        table = Table(expand=True, title='Missing Interfaces', **style)
        table.add_column('Missing interfaces in Netplan\'s State', justify="center", ratio=2)
        table.add_column('Missing interfaces in System\'s State', justify="center", ratio=2)
        for (iface1, iface2) in zip_longest(missing_interfaces_netplan.items(), missing_interfaces_system.items()):
            iface1_name = iface1[0] if iface1 else None
            iface2_name = iface2[0] if iface2 else None
            table.add_row(iface1_name, iface2_name)

        main_table.add_section()
        main_table.add_row(table, end_section=True)

    # Draw the grid
    if main_table.columns:
        console = Console()
        console.print(main_table)


if __name__ == '__main__':
    args = parser.parse_args()

    system_state = SystemConfigState(all=True)
    netplan_state = NetplanConfigState(rootdir=args.root_dir)

    diff_state = NetplanDiffState(system_state, netplan_state)
    diff = diff_state.get_diff()

    if args.table:
        style = {
            'title_style': 'bold magenta',
        }
        print_table(diff, **style)
    elif args.json:
        print(json.dumps(diff, indent=2, cls=DiffJSONEncoder))
    else:
        print('Use either -t or -j (or both)')
