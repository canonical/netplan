# Parity cases for `netplan status` (tabular/JSON/YAML output, --diff and
# --diff-only, NetworkManager/networkd managed interfaces, failing tools).
#
# The system data is modelled on the fixtures of tests/cli/test_status.py,
# tests/cli/test_state.py and tests/cli/test_state_diff.py.
#
# Copyright (C) 2026 Canonical, Ltd.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 3.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import copy
import json

NM_UUID = 'b6b7a21d-186e-45e1-b3a6-636da1735563'
NM_UUID2 = '1a1fc964-78df-4a93-8ed3-1416f02c5cdf'
NM_SSID2 = 'áéíóúççção€€€'
NM_SSID2_ESCAPED = '%3B'.join(str(b) for b in NM_SSID2.encode()) + '%3B'


def addr(family, local, prefixlen, **kw):
    a = {'family': family, 'local': local, 'prefixlen': prefixlen, 'scope': 'global'}
    a.update(kw)
    return a


IPROUTE2 = [
    {'ifindex': 1, 'ifname': 'lo', 'flags': ['LOOPBACK', 'UP', 'LOWER_UP'], 'mtu': 65536,
     'operstate': 'UNKNOWN', 'link_type': 'loopback', 'address': '00:00:00:00:00:00',
     'addr_info': [addr('inet', '127.0.0.1', 8, scope='host', label='lo'),
                   addr('inet6', '::1', 128, scope='host')]},
    {'ifindex': 2, 'ifname': 'enp0s31f6', 'flags': ['BROADCAST', 'MULTICAST', 'UP', 'LOWER_UP'], 'mtu': 1500,
     'operstate': 'UP', 'link_type': 'ether', 'address': '54:e1:ad:5f:24:b4',
     'addr_info': [addr('inet', '192.168.178.62', 24, metric=100, dynamic=True, label='enp0s31f6'),
                   addr('inet6', '2001:9e8:a19f:1c00:56e1:adff:fe5f:24b4', 64, dynamic=True, mngtmpaddr=True),
                   addr('inet6', 'fe80::56e1:adff:fe5f:24b4', 64, scope='link')]},
    {'ifindex': 5, 'ifname': 'wlan0', 'flags': ['BROADCAST', 'MULTICAST', 'UP', 'LOWER_UP'], 'mtu': 1500,
     'operstate': 'UP', 'link_type': 'ether', 'address': '1c:4d:70:e4:e4:0e',
     'addr_info': [addr('inet', '192.168.178.142', 24, dynamic=True, noprefixroute=True, label='wlan0'),
                   addr('inet6', '2001:9e8:a19f:1c00:7011:2d1:951:ad03', 64, temporary=True, dynamic=True),
                   addr('inet6', '2001:9e8:a19f:1c00:f24f:f724:5dd1:d0ad', 64, dynamic=True, mngtmpaddr=True),
                   addr('inet6', 'fe80::fec1:6ced:5268:b46c', 64, scope='link', noprefixroute=True)]},
    {'ifindex': 41, 'ifname': 'wg0', 'flags': ['POINTOPOINT', 'NOARP', 'UP', 'LOWER_UP'], 'mtu': 1420,
     'operstate': 'UNKNOWN', 'link_type': 'none', 'linkinfo': {'info_kind': 'wireguard'},
     'addr_info': [addr('inet', '10.10.0.2', 24, label='wg0')]},
    {'ifindex': 46, 'ifname': 'wwan0', 'flags': ['BROADCAST', 'MULTICAST', 'NOARP'], 'mtu': 1500,
     'operstate': 'DOWN', 'link_type': 'ether', 'address': 'a2:23:44:c4:4e:f8', 'addr_info': []},
    {'ifindex': 48, 'link': None, 'ifname': 'tun0', 'flags': ['POINTOPOINT', 'NOARP', 'UP', 'LOWER_UP'],
     'mtu': 1480, 'operstate': 'UNKNOWN', 'link_type': 'sit', 'address': '1.1.1.1',
     'linkinfo': {'info_kind': 'sit', 'info_data': {'proto': 'ip6ip', 'remote': '2.2.2.2', 'local': '1.1.1.1'}},
     'addr_info': [addr('inet6', '2001:dead:beef::2', 64)]},
    {'ifindex': 49, 'ifname': 'tun1', 'flags': ['POINTOPOINT', 'MULTICAST', 'NOARP', 'UP', 'LOWER_UP'],
     'mtu': 1500, 'operstate': 'UNKNOWN', 'link_type': 'none',
     'linkinfo': {'info_kind': 'tun', 'info_data': {'type': 'tun'}}},
    {'ifindex': 42, 'ifname': 'fakedev0', 'flags': [], 'operstate': 'DOWN'},
]


def nd(index, name, type, setup='configured', network_file=None, **kw):
    d = {'Index': index, 'Name': name, 'AlternativeNames': [], 'Type': type, 'Driver': None,
         'SetupState': setup, 'OperationalState': 'routable', 'CarrierState': 'carrier',
         'OnlineState': 'online', 'LinkFile': '/usr/lib/systemd/network/99-default.link',
         'Vendor': None, 'Model': None}
    if network_file:
        d['NetworkFile'] = network_file
    d.update(kw)
    return d


def nd_file(netdef):
    return '/run/systemd/network/10-netplan-%s.network' % netdef


NETWORKD = {'Interfaces': [
    nd(1, 'lo', 'loopback', setup='unmanaged'),
    nd(2, 'enp0s31f6', 'ether', network_file=nd_file('enp0s31f6'), Driver='e1000e',
       Vendor='Intel Corporation', Model='Ethernet Connection I219-LM',
       DNS=[{'Family': 2, 'Address': [192, 168, 178, 1], 'ConfigSource': 'DHCPv4',
             'ConfigProvider': [192, 168, 178, 1]},
            {'Family': 10, 'Address': [0xfd, 0, 0, 0, 0, 0, 0, 0, 0xce, 0xce, 0x1e, 0xff, 0xfe, 0x3d, 0xc7, 0x37],
             'ConfigSource': 'DHCPv6'}],
       SearchDomains=[{'Domain': 'search.domain', 'ConfigSource': 'DHCPv4'}],
       Addresses=[{'Family': 2, 'Address': [192, 168, 178, 62], 'PrefixLength': 24, 'ConfigSource': 'DHCPv4'},
                  {'Family': 10, 'Address': [0xfe, 0x80, 0, 0, 0, 0, 0, 0, 0x56, 0xe1, 0xad, 0xff, 0xfe, 0x5f,
                                             0x24, 0xb4], 'PrefixLength': 64, 'ConfigSource': 'foreign'}]),
    nd(5, 'wlan0', 'wlan', setup='unmanaged', network_file=nd_file('wlan0'), Driver='iwlwifi',
       Vendor='Intel Corporation  '),
    nd(41, 'wg0', 'wireguard', network_file=nd_file('wg0')),
    nd(46, 'wwan0', 'wwan', setup='unmanaged', Vendor='Sierra Wireless, Inc.', Model='EM7455'),
    nd(48, 'tun0', 'sit', network_file=nd_file('tun0')),
    nd(49, 'tun1', 'none', Kind='tun', Driver='tun', setup='unmanaged'),
]}

NMCLI = '\n'.join([
    'wlan0:MYCON:%s:/run/NetworkManager/system-connections/netplan-NM-%s-MYCON.nmconnection:802-11-wireless:yes'
    % (NM_UUID, NM_UUID),
    'wlan1:%s:%s:/run/NetworkManager/system-connections/netplan-NM-%s-%s.nmconnection:802-11-wireless:no'
    % (NM_SSID2, NM_UUID2, NM_UUID2, NM_SSID2_ESCAPED),
    ':inactive:1234:/etc/NetworkManager/system-connections/foo.nmconnection:802-3-ethernet:yes',
]) + '\n'


def route(family, dst, dev, table='main', protocol='kernel', scope='global', type='unicast', **kw):
    r = {'family': family, 'type': type, 'dst': dst, 'dev': dev, 'table': table,
         'protocol': protocol, 'scope': scope, 'flags': []}
    r.update(kw)
    return r


ROUTE4 = [
    route(2, 'default', 'enp0s31f6', protocol='dhcp', gateway='192.168.178.1', prefsrc='192.168.178.62', metric=100),
    route(2, 'default', 'wlan0', protocol='dhcp', gateway='192.168.178.1', metric=600),
    route(2, '10.10.0.0/24', 'wg0', scope='link', prefsrc='10.10.0.2'),
    route(2, '192.168.178.0/24', 'enp0s31f6', scope='link', prefsrc='192.168.178.62', metric=100),
    route(2, '192.168.178.0/24', 'wlan0', scope='link', prefsrc='192.168.178.142', metric=600),
    route(2, '192.168.178.1', 'enp0s31f6', table='1234', protocol='dhcp', scope='link',
          prefsrc='192.168.178.62', metric=100),
    route(2, '192.168.178.255', 'enp0s31f6', table='local', scope='link', type='broadcast',
          prefsrc='192.168.178.62'),
    route(2, '127.0.0.0/8', 'lo', table='local', scope='host', type='local', prefsrc='127.0.0.1'),
    route(2, '10.0.0.0/16', 'fakedev0', gateway='10.0.0.1', type='local', protocol='static'),
]
ROUTE6 = [
    route(10, '::1', 'lo', metric=256, pref='medium'),
    route(10, '2001:9e8:a19f:1c00::/64', 'enp0s31f6', protocol='ra', metric=100, expires=7199),
    route(10, '2001:9e8:a19f:1c00::/64', 'wlan0', protocol='ra', metric=600),
    route(10, '2001:9e8:a19f:1c00::/56', 'enp0s31f6', protocol='ra', gateway='fe80::cece:1eff:fe3d:c737',
          metric=100),
    route(10, '2001:9e8:a19f:1c00::/56', 'wlan0', protocol='ra', gateway='fe80::cece:1eff:fe3d:c737', metric=600),
    route(10, '2001:dead:beef::/64', 'tun0', metric=256),
    route(10, 'fe80::/64', 'enp0s31f6', metric=256),
    route(10, 'fe80::/64', 'wlan0', metric=1024),
    route(10, 'default', 'enp0s31f6', table='1234', protocol='ra', gateway='fe80::cece:1eff:fe3d:c737', metric=100),
    route(10, 'default', 'wlan0', protocol='ra', gateway='fe80::cece:1eff:fe3d:c737', metric=20600),
    route(10, 'ff00::/8', 'enp0s31f6', table='local', type='multicast', metric=256),
]

DNS_IP4 = [192, 168, 178, 1]
DNS_IP6 = [0xfd, 0, 0, 0, 0, 0, 0, 0, 0xce, 0xce, 0x1e, 0xff, 0xfe, 0x3d, 0xc7, 0x37]
RESOLVED = {'type': 'a{sv}', 'data': [{
    'DNS': {'type': 'a(iiay)', 'data': [[5, 2, DNS_IP4], [5, 10, DNS_IP6], [2, 2, DNS_IP4], [2, 10, DNS_IP6]]},
    'Domains': {'type': 'a(isb)', 'data': [[5, 'search.domain', False], [2, 'search.domain', False]]},
}]}

BUSCTL_ARGV = ['--json=short', 'call', '--system', 'org.freedesktop.resolve1', '/org/freedesktop/resolve1',
               'org.freedesktop.DBus.Properties', 'GetAll', 's', 'org.freedesktop.resolve1.Manager']

RESOLV_STUB = '''# This is /run/systemd/resolve/stub-resolv.conf managed by man:systemd-resolved(8).
# Do not edit.
nameserver 127.0.0.53
options edns0 trust-ad
search search.domain
'''

NETWORKCTL_STATUS = {
    'enp0s31f6': '''● 2: enp0s31f6
                     Link File: /usr/lib/systemd/network/99-default.link
                  Network File: /run/systemd/network/10-netplan-enp0s31f6.network
                         State: routable (configured)
             Activation Policy: manual
''',
    'wg0': '             Activation Policy: up\n',
    'tun0': '             Activation Policy: always-down\n',
    'wlan0': '      Wi-Fi access point: MYCON (aa:bb:cc:dd:ee:ff)\n',
}


def mocks(iproute2=None, networkd=None, nmcli=NMCLI, route4=None, route6=None, resolved=None, members=None,
          networkctl_status=None, ssids=None, systemctl=None, extra=None):
    '''Mock rules for one system. Pass a dict {"exit": .., "stdout": ..} to make a query fail.'''
    def out(v):
        if isinstance(v, dict) and ('exit' in v or 'stdout' in v):
            return v
        return {'stdout': v if isinstance(v, str) else json.dumps(v) + '\n'}

    ip = [dict(argv=['-d', '-j', 'addr'], **out(IPROUTE2 if iproute2 is None else iproute2)),
          dict(argv=['-d', '-j', '-4', 'route', 'show', 'table', 'all'], **out(ROUTE4 if route4 is None else route4)),
          dict(argv=['-d', '-j', '-6', 'route', 'show', 'table', 'all'], **out(ROUTE6 if route6 is None else route6))]
    for master, m in (members or {}).items():
        ip.append(dict(argv=['-d', '-j', 'link', 'show', 'master', master], **out(m)))
    status = dict(NETWORKCTL_STATUS)
    status.update(networkctl_status or {})
    networkctl = [dict(argv=['--json=short'], **out(NETWORKD if networkd is None else networkd))]
    for name, text in status.items():
        networkctl.append(dict(argv=['status', '--', name], **out(text)))
    nm = []
    for con, ssid in (ssids if ssids is not None else {'MYCON': 'MYCON\n', NM_SSID2: NM_SSID2 + '\n'}).items():
        nm.append(dict(argv=['--get-values', '802-11-wireless.ssid', 'con', 'show', 'id', con], **out(ssid)))
    nm.append(dict(argv=['-t', '-f', 'DEVICE,NAME,UUID,FILENAME,TYPE,AUTOCONNECT', 'con', 'show'], **out(nmcli)))
    m = {
        'systemctl': systemctl or [{'argv': ['--quiet', 'is-active', 'systemd-networkd.service'], 'exit': 0}],
        'ip': ip,
        'networkctl': networkctl,
        'nmcli': nm,
        'busctl': [dict(argv=BUSCTL_ARGV, **out(RESOLVED if resolved is None else resolved))],
    }
    for k, v in (extra or {}).items():
        m[k] = v + m.get(k, [])
    return m


RESOLV_FILE = '/run/systemd/resolve/stub-resolv.conf'


def case(id, argv, files=None, resolv=RESOLV_STUB, env=None, **kw):
    f = dict(files or {})
    if resolv is not None:
        f[RESOLV_FILE] = resolv
    c = {'id': 'status/' + id, 'argv': ['status'] + argv, 'files': f, 'mocks': mocks(**kw)}
    if env:
        c['env'] = env
    return c


# A subset of the interfaces above, for the diff cases.
def only(*names):
    return [copy.deepcopy(i) for i in IPROUTE2 if i['ifname'] in names]


DIFF_MISMATCH = '''network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s31f6:
      dhcp4: true
      addresses: [10.0.0.5/24]
      macaddress: "AA:bb:cc:dd:ee:ff"
      nameservers:
        addresses: [1.1.1.1]
        search: [example.com]
      routes:
        - to: 172.16.0.0/16
          via: 192.168.178.254
        - to: 10.9.9.9/32
          via: 192.168.178.254
          metric: 50
    eth9:
      dhcp4: true
  bridges:
    br9:
      dhcp6: true
  wifis:
    wl9:
      access-points:
        "nothere": {}
'''

DIFF_MATCH = '''network:
  version: 2
  ethernets:
    enp0s31f6:
      dhcp4: true
      dhcp6: true
'''

NM_WIFI = '''network:
  version: 2
  wifis:
    NM-%s:
      renderer: NetworkManager
      match:
        name: wlan0
      dhcp4: true
      nameservers:
        addresses: [192.168.178.1, "fd00::cece:1eff:fe3d:c737"]
        search: [search.domain]
      access-points:
        "MYCON":
          auth:
            key-management: none
      networkmanager:
        uuid: %s
        name: MYCON
''' % (NM_UUID, NM_UUID)

# bond/bridge/vrf members on the system vs. in Netplan
LINKS_IP = [
    {'ifindex': 10, 'ifname': 'eth1', 'flags': ['UP'], 'operstate': 'UP', 'address': '52:54:00:00:00:01'},
    {'ifindex': 11, 'ifname': 'eth2', 'flags': ['UP'], 'operstate': 'UP', 'address': '52:54:00:00:00:02'},
    {'ifindex': 12, 'ifname': 'br0', 'flags': ['UP'], 'operstate': 'UP', 'address': '52:54:00:00:00:03',
     'addr_info': [addr('inet', '10.1.1.1', 24)]},
    {'ifindex': 13, 'ifname': 'bond0', 'flags': ['UP'], 'operstate': 'UP'},
    {'ifindex': 14, 'ifname': 'vrf0', 'flags': ['UP'], 'operstate': 'UP'},
    {'ifindex': 15, 'ifname': 'eth3', 'flags': ['UP'], 'operstate': 'UP'},
    {'ifindex': 16, 'ifname': 'veth0', 'flags': ['UP'], 'operstate': 'UP'},
]
LINKS_ND = {'Interfaces': [
    nd(10, 'eth1', 'ether', network_file=nd_file('eth1')),
    nd(11, 'eth2', 'ether', network_file=nd_file('eth2')),
    nd(12, 'br0', 'bridge', network_file=nd_file('br0')),
    nd(13, 'bond0', 'bond', network_file=nd_file('bond0')),
    nd(14, 'vrf0', 'ether', Kind='vrf', network_file=nd_file('vrf0')),
    nd(15, 'eth3', 'ether', network_file=nd_file('eth3')),
    nd(16, 'veth0', 'ether', Kind='veth', network_file=nd_file('veth0')),
]}
LINKS_MEMBERS = {
    'br0': [{'ifindex': 10, 'ifname': 'eth1'}],
    'bond0': [{'ifindex': 15, 'ifname': 'eth3'}],
    'vrf0': [],
}
LINKS_ROUTES4 = [
    route(2, '10.1.1.0/24', 'br0', scope='link', prefsrc='10.1.1.1'),
    route(2, '10.1.1.1', 'br0', table='local', scope='host', type='local', prefsrc='10.1.1.1'),
    route(2, 'default', 'br0', protocol='static', gateway='10.1.1.254', metric=42, table='200'),
    route(2, '10.50.0.0/16', 'br0', protocol='static', gateway='10.1.1.253'),
]
LINKS_NETPLAN = '''network:
  version: 2
  renderer: networkd
  ethernets:
    eth1: {}
    eth2: {}
    eth3: {}
  bridges:
    br0:
      interfaces: [eth2]
      addresses: [10.1.1.1/24]
      routes:
        - to: default
          via: 10.1.1.254
          table: 200
          metric: 42
  bonds:
    bond0:
      interfaces: [eth3]
  vrfs:
    vrf0:
      table: 1000
      interfaces: [eth1]
'''
LINKS_NETPLAN_GW = '''network:
  version: 2
  renderer: networkd
  bridges:
    br0:
      addresses: [10.1.1.1/24]
      gateway4: 10.1.1.254
      gateway6: "2001:db8:0:0::1"
'''


def links(id, argv, netplan=LINKS_NETPLAN, **kw):
    return case(id, argv, files={'/etc/netplan/50-links.yaml': netplan}, iproute2=LINKS_IP, networkd=LINKS_ND,
                route4=kw.pop('route4', LINKS_ROUTES4), route6=[], resolved={'data': [{}]}, nmcli='',
                members=LINKS_MEMBERS, **kw)


def rt_tables(content):
    return {'/usr/share/iproute2/rt_tables': content}


def all_cases():
    out = []
    # Plain system output
    for fmt in (None, 'json', 'yaml', 'JSON', 'tabular', 'other'):
        f = ['--format', fmt] if fmt else []
        name = fmt or 'tabular-default'
        out.append(case('sys/%s' % name, f))
        out.append(case('sys/%s-all' % name, f + ['-a']))
    out.append(case('sys/verbose-all', ['-a', '-v']))
    out.append(case('sys/verbose', ['--verbose']))
    out.append(case('sys/verbose-rt-tables', ['-av'], files=rt_tables('255\tlocal\n254\tmain\n1234 custom\n# x y\n')))
    out.append(case('sys/rt-tables-empty', ['-av'], files=rt_tables('')))
    out.append(case('sys/rt-tables-default', ['-av']))
    for ifname in ('enp0s31f6', 'wlan0', 'wwan0', 'fakedev0', 'lo', 'tun1', 'nonexistent0'):
        out.append(case('ifname/%s' % ifname, [ifname]))
        out.append(case('ifname/%s-json' % ifname, [ifname, '-f', 'json']))
    out.append(case('ifname/empty', ['']))
    out.append(case('ifname/yaml-verbose', ['enp0s31f6', '-v', '-f', 'yaml']))

    # Colours and terminal width
    out.append(case('color/force', ['-a'], env={'FORCE_COLOR': '1'}))
    out.append(case('color/force-empty', ['-av'], env={'FORCE_COLOR': '', 'TERM': 'xterm-256color'}))
    out.append(case('color/truecolor', ['-a'], env={'FORCE_COLOR': '1', 'COLORTERM': 'truecolor'}))
    out.append(case('color/dumb', ['-a'], env={'FORCE_COLOR': '1', 'TERM': 'dumb', 'COLUMNS': '30'}))
    out.append(case('color/no-color', ['-a'], env={'FORCE_COLOR': '1', 'NO_COLOR': '1'}))
    out.append(case('color/narrow', ['-a'], env={'COLUMNS': '30'}))
    out.append(case('color/narrow-lines', ['-a'], env={'COLUMNS': '25', 'LINES': '10', 'FORCE_COLOR': '1'}))
    out.append(case('color/very-narrow', ['-av'], env={'COLUMNS': '8'}))

    # networkd not running
    sc = 'systemd-networkd.service'
    inactive = {'argv': ['--quiet', 'is-active', sc], 'exit': 3}
    masked = {'argv': ['is-enabled', sc], 'exit': 1, 'stdout': 'masked\n'}
    disabled = {'argv': ['is-enabled', sc], 'exit': 1, 'stdout': 'disabled\n'}
    out.append(case('networkd/masked', [], systemctl=[inactive, masked]))
    out.append(case('networkd/not-installed', [], systemctl=[inactive, disabled, {'argv': ['status', sc], 'exit': 4}]))
    out.append(case('networkd/start', [], systemctl=[inactive, {'argv': ['status', sc], 'exit': 3}]))
    out.append(case('networkd/start-fails', [],
                    systemctl=[inactive, {'argv': ['start', sc], 'exit': 1, 'stderr': 'Failed to start\n'}]))

    # Required queries failing
    out.append(case('fail/ip-addr', [], iproute2={'exit': 1, 'stderr': 'ip: boom\n'}))
    out.append(case('fail/ip-addr-json', [], iproute2='[{"ifindex": 1,]\n'))
    out.append(case('fail/ip-addr-empty', [], iproute2=[]))
    out.append(case('fail/networkctl', [], networkd={'exit': 1}))
    out.append(case('fail/networkctl-json', [], networkd='{"Interfaces": [}'))
    out.append(case('fail/networkctl-no-interfaces-key', [], networkd={'Links': []}))
    out.append(case('fail/networkctl-list', [], networkd=[1, 2]))
    out.append(case('fail/networkctl-empty', [], networkd={'Interfaces': []}))
    out.append(case('fail/both', [], iproute2={'exit': 2}, networkd='garbage'))

    # Optional queries failing
    out.append(case('optional/nmcli-fails', ['-a'], nmcli={'exit': 8, 'stderr': 'Error: NetworkManager is not running.\n'}))
    out.append(case('optional/nmcli-short-line', ['-a'], nmcli='wlan0:MYCON:uuid\n'))
    out.append(case('optional/nm-ssid-fails', ['-a'], ssids={'MYCON': {'exit': 10}}))
    out.append(case('optional/route4-fails', ['-a'], route4={'exit': 1}))
    out.append(case('optional/route6-fails', ['-a'], route6={'exit': 1}))
    out.append(case('optional/route6-bad-json', ['-a', '-f', 'json'], route6='nope'))
    out.append(case('optional/routes-dict', ['-a'], route4={'a': 1}))
    out.append(case('optional/busctl-fails', ['-a'], resolved={'exit': 1}))
    out.append(case('optional/busctl-bad-type', ['-a', '-f', 'json'],
                    resolved={'data': [{'DNS': {'type': 'invalid', 'data': 'garbage'}}]}))
    out.append(case('optional/busctl-bad-domains', ['-a', '-f', 'json'],
                    resolved={'data': [{'DNS': RESOLVED['data'][0]['DNS'], 'Domains': {'type': 'x'}}]}))
    out.append(case('optional/networkctl-status-fails', ['-a'],
                    networkctl_status={'enp0s31f6': {'exit': 1, 'stderr': 'Interface not found\n'}}))
    out.append(case('optional/no-resolv-conf', ['-a'], resolv=None))
    out.append(case('optional/resolv-compat', ['-f', 'yaml'], resolv='''# This is /run/systemd/resolve/resolv.conf managed
nameserver 1.1.1.1
nameserver 8.8.8.8 9.9.9.9
nameservers 7.7.7.7
search a.example b.example
search c.example
''', ))
    out.append(case('optional/resolv-plain', [], resolv='nameserver 10.0.0.1\r\nsearch x.y\n'))
    out.append(case('optional/resolv-empty', [], resolv=''))

    # A networkd-managed wifi and assorted odd data
    wifi_nd = copy.deepcopy(NETWORKD)
    wifi_nd['Interfaces'][2]['SetupState'] = 'configured'
    out.append(case('wifi/networkd', ['wlan0'], networkd=wifi_nd, nmcli=''))
    out.append(case('wifi/networkd-escaped', ['wlan0', '-f', 'json'], networkd=wifi_nd, nmcli='', networkctl_status={
        'wlan0': 'WiFi access point: \\303\\241\\303\\251 x (y) (aa:bb)\n'}))
    out.append(case('wifi/networkd-no-ap', ['wlan0'], networkd=wifi_nd, nmcli='', networkctl_status={'wlan0': ''}))
    wlan1 = copy.deepcopy(IPROUTE2) + [{'ifindex': 7, 'ifname': 'wlan1', 'flags': ['UP'], 'operstate': 'UP'}]
    wlan1_nd = copy.deepcopy(NETWORKD)
    wlan1_nd['Interfaces'].append(nd(7, 'wlan1', 'wlan', setup='unmanaged'))
    out.append(case('wifi/nm-non-ascii-ssid', ['-f', 'json'], iproute2=wlan1, networkd=wlan1_nd))
    out.append(case('wifi/nm-non-ascii-ssid-tabular', [], iproute2=wlan1, networkd=wlan1_nd))
    weird = copy.deepcopy(IPROUTE2)
    weird[0]['ifname'] = 'lo[1]'
    weird[1]['addr_info'].append(addr('inet6', '::ffff:1.2.3.4', 128))
    weird[6]['flags'] = 'UP'
    out.append(case('odd/names', ['-a'], iproute2=weird))
    out.append(case('odd/names-color', ['-a'], iproute2=weird, env={'FORCE_COLOR': '1'}))
    markup = copy.deepcopy(IPROUTE2)
    markup[3]['ifname'] = 'wg[/x]'
    out.append(case('odd/markup-error', ['-a'], iproute2=markup))
    nd_null = copy.deepcopy(NETWORKD)
    nd_null['Interfaces'][3]['SetupState'] = None
    out.append(case('odd/setup-state-null', [], networkd=nd_null))
    nd_noidx = copy.deepcopy(NETWORKD)
    del nd_noidx['Interfaces'][0]['Index']
    out.append(case('odd/networkd-no-index', [], networkd=nd_noidx))
    long_vendor = copy.deepcopy(NETWORKD)
    long_vendor['Interfaces'][1]['Vendor'] = 'Intel Corporation ' * 6
    out.append(case('odd/long-vendor', ['enp0s31f6'], networkd=long_vendor))
    out.append(case('odd/long-vendor-yaml', ['enp0s31f6', '-f', 'yaml'], networkd=long_vendor))
    yaml_q = copy.deepcopy(IPROUTE2)
    yaml_q[1]['address'] = '52:54:00:12:34:56'
    yaml_q[3]['ifname'] = 'yes'
    yaml_q[5]['ifname'] = '2024-01-01'
    out.append(case('odd/yaml-quoting', ['-a', '-f', 'yaml'], iproute2=yaml_q))
    tabs = copy.deepcopy(NETWORKD)
    tabs['Interfaces'][1]['Vendor'] = 'Intel\tCorp\t\tx'
    out.append(case('odd/tab-vendor', ['enp0s31f6'], networkd=tabs))
    out.append(case('odd/tab-vendor-color', ['enp0s31f6'], networkd=tabs, env={'FORCE_COLOR': '1', 'COLUMNS': '30'}))
    out.append(case('odd/cjk-ssid', ['wlan0', '-v'], networkd=wifi_nd, nmcli='', env={'COLUMNS': '33'},
                    networkctl_status={'wlan0': 'WiFi access point: \\344\\275\\240\\345\\245\\275\\344\\275\\240\\345'
                                                '\\245\\275\\344\\275\\240\\345\\245\\275 "q" (aa)\n'}))
    nodst = copy.deepcopy(ROUTE4) + [{'family': 2, 'dev': 'enp0s31f6', 'table': 'main', 'type': 'blackhole',
                                      'metric': 0, 'gateway': '', 'scope': 'nowhere', 'protocol': 'boot'}]
    out.append(case('odd/route-no-dst', ['enp0s31f6', '-v'], route4=nodst))
    out.append(case('odd/route-no-dst-diff', ['--diff-only'], route4=nodst, files={'/etc/netplan/50-cfg.yaml': DIFF_MATCH}))
    online = copy.deepcopy(IPROUTE2)
    online[1]['addr_info'] = [a for a in online[1]['addr_info'] if a['family'] == 'inet6']
    out.append(case('odd/offline', [], iproute2=online, nmcli=''))

    # bond/bridge/vrf members
    members = {'mybr0': [{'ifname': 'fakedev0'}], 'mybond0': {'exit': 1}}
    br = copy.deepcopy(IPROUTE2) + [
        {'ifindex': 43, 'ifname': 'mybr0', 'flags': ['UP'], 'operstate': 'UP'},
        {'ifindex': 45, 'ifname': 'mybond0', 'flags': ['UP'], 'operstate': 'UP'}]
    br_nd = copy.deepcopy(NETWORKD)
    br_nd['Interfaces'] += [nd(43, 'mybr0', 'bridge'), nd(45, 'mybond0', 'bond')]
    out.append(case('members/basic', ['-a'], iproute2=br, networkd=br_nd, members=members))
    out.append(case('members/bad-json', ['-a'], iproute2=br, networkd=br_nd, members={'mybr0': 'nope'}))

    # --diff / --diff-only
    mism = {'/etc/netplan/50-cfg.yaml': DIFF_MISMATCH}
    match = {'/etc/netplan/50-cfg.yaml': DIFF_MATCH}
    nmwifi = {'/etc/netplan/90-NM-%s.yaml' % NM_UUID: NM_WIFI}
    for name, files, ip in (('mismatch', mism, None), ('match', match, only('lo', 'enp0s31f6')),
                            ('nm-wifi', nmwifi, None), ('none', {}, only('lo', 'enp0s31f6', 'wwan0'))):
        for flag in ('--diff', '--diff-only'):
            for fmt in ([], ['-f', 'json'], ['-f', 'yaml']):
                out.append(case('diff/%s%s%s' % (name, flag[6:] and '-only', fmt and '-' + fmt[1] or ''),
                                [flag] + fmt, files=files, iproute2=ip))
        out.append(case('diff/%s-ifname' % name, ['--diff', 'enp0s31f6'], files=files, iproute2=ip))
        out.append(case('diff/%s-verbose' % name, ['--diff-only', '-v'], files=files, iproute2=ip))
    out.append(case('diff/mismatch-missing-ifname', ['--diff', 'eth9'], files=mism))
    out.append(case('diff/mismatch-color', ['--diff'], files=mism, env={'FORCE_COLOR': '1'}))
    out.append(case('diff/mismatch-color-256', ['--diff', '-v'], files=mism,
                    env={'FORCE_COLOR': '1', 'TERM': 'xterm-256color', 'COLUMNS': '100'}))
    out.append(case('diff/mismatch-only-color', ['--diff-only'], files=mism, env={'FORCE_COLOR': '1', 'NO_COLOR': ''}))
    out.append(case('diff/root-dir', ['--diff', '--root-dir', '{ROOT}'],
                    files={'{ROOT}/etc/netplan/a.yaml': DIFF_MISMATCH}))
    out.append(case('diff/root-dir-empty', ['--diff-only', '--root-dir', ''], files=mism))
    out.append(case('diff/bad-yaml', ['--diff'], files={'/etc/netplan/a.yaml': 'network: [\n'}))
    out.append(case('diff/bad-config', ['--diff'], files={'/etc/netplan/a.yaml':
                                                          'network:\n  ethernets:\n    eth0:\n      dhcp4: maybe\n'}))
    out.append(links('links/diff', ['--diff']))
    out.append(links('links/diff-only-json', ['--diff-only', '-f', 'json']))
    out.append(links('links/diff-verbose', ['--diff', '-v']))
    out.append(links('links/diff-gateways', ['--diff-only'], netplan=LINKS_NETPLAN_GW))
    out.append(links('links/diff-gateways-json', ['--diff-only', '-f', 'json'], netplan=LINKS_NETPLAN_GW))
    out.append(links('links/plain', ['-a']))
    out.append(links('links/yaml', ['-f', 'yaml']))
    return out
