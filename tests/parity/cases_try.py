# 'netplan try' rollback, backend failures and critical interfaces, for
# the parity runner (parity.py).
#
# The try cases start from generated backend files of an earlier
# configuration in /run, apply a different candidate YAML and then reject
# it (timeout, or SIGINT as sent by netplan-dbus Cancel) or accept it
# (SIGUSR1, netplan-dbus Apply). A correct rollback restores the earlier
# backend files without regenerating them from the still-present candidate.
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

STAMP = '/run/netplan/netplan-try.ready'

CANDIDATE_NETWORKD = '''network:
  version: 2
  ethernets:
    eth0:
      addresses: [10.0.0.2/24]
'''

CANDIDATE_NM = '''network:
  version: 2
  renderer: NetworkManager
  ethernets:
    eth0:
      addresses: [10.0.0.2/24]
'''

OLD_NETWORKD = {
    '/run/systemd/network/10-netplan-eth0.network': {
        'content': '[Match]\nName=eth0\n\n[Network]\nDHCP=ipv4\n', 'mode': 0o644},
}

OLD_NM = {
    '/run/NetworkManager/system-connections/netplan-eth0.nmconnection': {
        'content': '[connection]\nid=netplan-eth0\ntype=ethernet\ninterface-name=eth0\n\n[ipv4]\nmethod=auto\n'},
}

SYSFS_ETH0 = {
    '/sys/class/net/eth0/address': {'content': '00:11:22:33:44:55\n', 'mode': 0o644},
    '/sys/class/net/eth0/ifindex': {'content': '2\n', 'mode': 0o644},
}


def case(id, argv, **kw):
    return dict(id=id, argv=argv, **kw)


def try_cases():
    out = []
    for backend, candidate, old in (('networkd', CANDIDATE_NETWORKD, OLD_NETWORKD),
                                    ('nm', CANDIDATE_NM, OLD_NM)):
        files = dict(old, **{'/etc/netplan/a.yaml': candidate}, **SYSFS_ETH0)
        out += [
            case('try/%s/timeout' % backend, ['try', '--timeout', '1'], files=files, timeout=60),
            case('try/%s/cancel-sigint' % backend, ['try', '--timeout', '30'], files=files, timeout=60,
                 signal={'when_exists': STAMP, 'signal': 'SIGINT'}),
            case('try/%s/accept-sigusr1' % backend, ['try', '--timeout', '30'], files=files, timeout=60,
                 signal={'when_exists': STAMP, 'signal': 'SIGUSR1'}),
            case('try/%s/config-file-cancel' % backend,
                 ['try', '--timeout', '30', '--config-file', '/etc/network/extra.yaml'],
                 files=dict(files, **{'/etc/network/extra.yaml': candidate.replace('10.0.0.2', '10.0.0.3')}),
                 timeout=60, signal={'when_exists': STAMP, 'signal': 'SIGINT'}),
        ]
    files = dict(OLD_NETWORKD, **{'/etc/netplan/a.yaml': CANDIDATE_NETWORKD}, **SYSFS_ETH0)
    # backend operations failing while applying, and again while rolling back
    for name, mocks in (
        ('systemctl-stop-fails', {'systemctl': [{'prefix': ['stop'], 'exit': 1}]}),
        ('systemctl-start-fails', {'systemctl': [{'prefix': ['start'], 'exit': 1}]}),
        ('daemon-reload-fails', {'systemctl': [{'prefix': ['daemon-reload'], 'exit': 1}]}),
        ('networkctl-and-restart-fail', {'networkctl': [{'exit': 1}],
                                         'systemctl': [{'prefix': ['restart'], 'exit': 1}]}),
        ('udevadm-reload-fails', {'udevadm': [{'prefix': ['control'], 'exit': 1}]}),
    ):
        out.append(case('try/fail/%s' % name, ['try', '--timeout', '1'], files=files, mocks=mocks, timeout=60))
        out.append(case('apply/fail/%s' % name, ['apply'], files=files, mocks=mocks))
    return out


def critical_cases():
    out = []
    for critical in (True, False):
        yaml = '''network:
  version: 2
  ethernets:
    nic:
      match:
        macaddress: "00:11:22:33:44:55"
      set-name: lan0
      critical: %s
      dhcp4: true
''' % ('true' if critical else 'false')
        files = dict(SYSFS_ETH0, **{'/etc/netplan/a.yaml': yaml})
        mocks = {'ethtool': [{'prefix': ['-P'], 'stdout': 'Permanent address: 00:11:22:33:44:55\n'}]}
        name = 'critical' if critical else 'not-critical'
        out.append(case('apply/rename/%s' % name, ['apply'], files=files, mocks=mocks))
        out.append(case('try/rename/%s' % name, ['try', '--timeout', '30'], files=files, mocks=mocks,
                        timeout=60, signal={'when_exists': STAMP, 'signal': 'SIGUSR1'}))
    return out


def all_cases():
    return try_cases() + critical_cases()
