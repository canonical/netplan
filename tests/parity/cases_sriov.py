# SR-IOV parity cases: "netplan apply" (SR-IOV part, netplan_cli/cli/sriov.py)
# and "netplan rebind", with sysfs fixtures for PFs and VFs under
# /sys/class/net and /sys/bus/pci (and the mlx5 debugfs under
# /sys/kernel/debug). /sbin/devlink is mocked.
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

import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PF_PCI = '0000:03:00.0'
PF2_PCI = '0000:04:00.0'


def example(name):
    with open(os.path.join(REPO, 'examples', name)) as f:
        return f.read()


def case(id, argv, **kw):
    return dict(id=id, argv=argv, **kw)


def ro(content):
    return {'content': content, 'mode': 0o644}


def pci_dev(pci, driver=None, extra=None):
    '''A PCI device under /sys/bus/pci/devices, optionally bound to a driver.'''
    base = '/sys/bus/pci/devices/' + pci
    files = {base + '/uevent': ro('DRIVER=%s\nPCI_CLASS=20000\nPCI_SLOT_NAME=%s\n' % (driver or '', pci))}
    if driver:
        files[base + '/driver'] = {'symlink': '../../drivers/' + driver}
        files['/sys/bus/pci/drivers/%s/bind' % driver] = ''
        files['/sys/bus/pci/drivers/%s/unbind' % driver] = ''
    files.update(extra or {})
    return files


def netdev(name, pci):
    return {'/sys/class/net/%s/device' % name: {'symlink': '../../../bus/pci/devices/' + pci},
            '/sys/class/net/%s/ifindex' % name: ro('2\n')}


def pf(name, pci=PF_PCI, vfs=(), driver='mlx5_core', totalvfs='8\n', numvfs='0\n', autoprobe=None,
       vf_driver=None, vendor='0x15b3\n', device='0x1017\n'):
    '''A PF network device with VFs [(netdev name or None, pci address)].'''
    base = '/sys/bus/pci/devices/' + pci
    extra = {}
    if numvfs is not None:
        extra[base + '/sriov_numvfs'] = numvfs if isinstance(numvfs, dict) else ro(numvfs)
    if totalvfs is not None:
        extra[base + '/sriov_totalvfs'] = ro(totalvfs)
    if autoprobe is not None:
        extra[base + '/sriov_drivers_autoprobe'] = ro(autoprobe)
    if vendor is not None:
        extra[base + '/vendor'] = ro(vendor)
    if device is not None:
        extra[base + '/device'] = ro(device)
    files = pci_dev(pci, driver, extra)
    files.update(netdev(name, pci))
    for i, (vf_name, vf_pci) in enumerate(vfs):
        files[base + '/virtfn%d' % i] = {'symlink': '../' + vf_pci}
        files.update(pci_dev(vf_pci, vf_driver, {
            '/sys/bus/pci/devices/%s/physfn' % vf_pci: {'symlink': '../' + pci}}))
        if vf_name:
            files.update(netdev(vf_name, vf_pci))
    return files


def vfs_for(prefix, pci_prefix, names):
    return [(name, '%s.%d' % (pci_prefix, i + 2)) for i, name in enumerate(names)]


EXAMPLE_VFS = vfs_for('enp1s16f', '0000:03:00', ['enp1s16f1', 'enp1s16f2'])


def devlink(mode=None, exit=0, stdout=None, set_exit=0, pci=PF_PCI):
    if stdout is None:
        dev = {'pci/' + pci: {'mode': mode}} if mode else {}
        stdout = json.dumps({'dev': dev}) + '\n'
    return [{'prefix': ['-j', 'dev', 'eswitch', 'show'], 'stdout': stdout, 'exit': exit},
            {'prefix': ['dev', 'eswitch', 'set'], 'exit': set_exit}]


def netplan_yaml(body):
    return 'network:\n  version: 2\n  renderer: networkd\n' + body


def apply_cases():
    sriov = example('sriov.yaml')
    sriov_vlan = example('sriov_vlan.yaml')
    sysfs = pf('eno1', vfs=EXAMPLE_VFS)

    def f(conf, *extra, **kw):
        files = {'/etc/netplan/a.yaml': conf}
        for e in extra:
            files.update(e)
        return dict(files=files, **kw)

    pf_only = netplan_yaml('  ethernets:\n    eno1:\n      virtual-function-count: 2\n')
    eswitch_only = netplan_yaml('  ethernets:\n    eno1:\n      embedded-switch-mode: legacy\n')
    vf_conf = netplan_yaml('''  ethernets:
    eno1: {}
    enp1s16f1:
      link: eno1
''')
    two_vlans = netplan_yaml('''  ethernets:
    eno1: {}
    enp1s16f1:
      link: eno1
  vlans:
    vlan1:
      id: 10
      link: enp1s16f1
      renderer: sriov
    vlan2:
      id: 11
      link: enp1s16f1
      renderer: sriov
''')
    vlan_no_vf = netplan_yaml('''  ethernets:
    eno1: {}
    enp1s16f1:
      link: eno1
    eth9: {}
  vlans:
    vlan1:
      id: 10
      link: eth9
      renderer: sriov
''')
    pf_match = netplan_yaml('''  ethernets:
    pf:
      match:
        name: "en*"
      set-name: %s
      virtual-function-count: 1
''')
    pf_match_driver = netplan_yaml('''  ethernets:
    pf:
      match:
        driver: ixgbe
      virtual-function-count: 1
''')
    vf_match_two = netplan_yaml('''  ethernets:
    eno1: {}
    vf1:
      match:
        name: "enp1s16f*"
      link: eno1
''')
    switchdev_delay = netplan_yaml('''  ethernets:
    eno1:
      embedded-switch-mode: switchdev
      delay-virtual-functions-rebind: true
    enp1s16f1:
      link: eno1
''')
    explicit = netplan_yaml('''  ethernets:
    eno1:
      virtual-function-count: %d
    enp1s16f1:
      link: eno1
    enp1s16f2:
      link: eno1
''')
    two_pfs = netplan_yaml('''  ethernets:
    eno1:
      virtual-function-count: 1
    eno2:
      embedded-switch-mode: switchdev
      virtual-function-count: 2
''')
    sw = devlink('switchdev')
    leg = devlink('legacy')
    full_dev = '/sys/bus/pci/devices/%s/sriov_numvfs' % PF_PCI

    out = [
        # examples/sriov.yaml: eswitch change (legacy -> switchdev), with and without autoprobe
        case('sriov/apply/example', ['apply', '--sriov-only'], **f(sriov, sysfs, mocks={'devlink': leg})),
        case('sriov/apply/example-autoprobe', ['apply', '--sriov-only'],
             **f(sriov, pf('eno1', vfs=EXAMPLE_VFS, autoprobe='1\n'), mocks={'devlink': leg})),
        case('sriov/apply/example-autoprobe-off', ['apply', '--sriov-only'],
             **f(sriov, pf('eno1', vfs=EXAMPLE_VFS, autoprobe='0\n'), mocks={'devlink': leg})),
        case('sriov/apply/example-vfs-bound', ['apply', '--sriov-only'],
             **f(sriov, pf('eno1', vfs=EXAMPLE_VFS, vf_driver='mlx5_core'), mocks={'devlink': leg})),
        case('sriov/apply/example-unbind-fails', ['apply', '--sriov-only'],
             **f(sriov, pf('eno1', vfs=EXAMPLE_VFS, vf_driver='mlx5_core'),
                 {'/sys/bus/pci/drivers/mlx5_core/unbind': {'dir': True}}, mocks={'devlink': leg})),
        case('sriov/apply/example-already-switchdev', ['apply', '--sriov-only'],
             **f(sriov, sysfs, mocks={'devlink': sw})),
        case('sriov/apply/example-devlink-fails', ['apply', '--sriov-only'],
             **f(sriov, sysfs, mocks={'devlink': devlink(exit=1)})),
        case('sriov/apply/example-devlink-no-mode', ['apply', '--sriov-only'],
             **f(sriov, sysfs, mocks={'devlink': devlink()})),
        case('sriov/apply/example-devlink-bad-json', ['apply', '--sriov-only'],
             **f(sriov, sysfs, mocks={'devlink': devlink(stdout='not json')})),
        case('sriov/apply/example-devlink-json-list', ['apply', '--sriov-only'],
             **f(sriov, sysfs, mocks={'devlink': devlink(stdout='[]')})),
        case('sriov/apply/example-devlink-set-fails', ['apply', '--sriov-only'],
             **f(sriov, sysfs, mocks={'devlink': devlink('legacy', set_exit=1)})),
        case('sriov/apply/example-bind-fails', ['apply', '--sriov-only'],
             **f(sriov, sysfs, {'/sys/bus/pci/drivers/mlx5_core/bind': {'dir': True}}, mocks={'devlink': sw})),
        case('sriov/apply/example-no-sysfs', ['apply', '--sriov-only'], **f(sriov, mocks={'devlink': leg})),
        case('sriov/apply/example-full-apply', ['apply'], **f(sriov, sysfs, mocks={'devlink': leg})),
        case('sriov/apply/example-vlan', ['apply', '--sriov-only'], **f(sriov_vlan, sysfs)),
        case('sriov/apply/example-vlan-ip-fails', ['apply', '--sriov-only'],
             **f(sriov_vlan, sysfs, mocks={'ip': [{'prefix': ['link', 'set'], 'exit': 2}]})),
        case('sriov/apply/example-vlan-no-vf-index', ['apply', '--sriov-only'],
             **f(sriov_vlan, sysfs, {'/sys/class/net/enp1s16f1/device': {
                 'symlink': '../../../bus/pci/devices/0000:03:00.7'}})),
        case('sriov/apply/example-vlan-vf-no-device', ['apply', '--sriov-only'],
             **f(sriov_vlan, pf('eno1', vfs=[(None, '0000:03:00.2')]),
                 {'/sys/class/net/enp1s16f1/ifindex': ro('3\n')})),
        case('sriov/apply/two-sriov-vlans', ['apply', '--sriov-only'], **f(two_vlans, sysfs)),
        case('sriov/apply/vlan-link-not-vf', ['apply', '--sriov-only'], **f(vlan_no_vf, sysfs)),
        case('sriov/apply/vf-only', ['apply', '--sriov-only'], **f(vf_conf, sysfs)),
        case('sriov/apply/pf-only-count', ['apply', '--sriov-only'], **f(pf_only, sysfs)),
        case('sriov/apply/eswitch-only', ['apply', '--sriov-only'], **f(eswitch_only, sysfs, mocks={'devlink': sw})),
        case('sriov/apply/eswitch-only-no-vfs', ['apply', '--sriov-only'],
             **f(eswitch_only, pf('eno1'), mocks={'devlink': sw})),
        case('sriov/apply/delay-rebind', ['apply', '--sriov-only'],
             **f(switchdev_delay, sysfs, mocks={'devlink': leg})),
        case('sriov/apply/explicit-count', ['apply', '--sriov-only'], **f(explicit % 4, sysfs)),
        case('sriov/apply/explicit-count-too-small', ['apply', '--sriov-only'], **f(explicit % 1, sysfs)),
        case('sriov/apply/count-over-256', ['apply', '--sriov-only'], **f(explicit % 300, sysfs)),
        case('sriov/apply/count-over-totalvfs', ['apply', '--sriov-only'],
             **f(explicit % 4, pf('eno1', vfs=EXAMPLE_VFS, totalvfs='3\n'))),
        case('sriov/apply/totalvfs-missing', ['apply', '--sriov-only'],
             **f(explicit % 4, pf('eno1', vfs=EXAMPLE_VFS, totalvfs=None))),
        case('sriov/apply/totalvfs-invalid', ['apply', '--sriov-only'],
             **f(explicit % 4, pf('eno1', vfs=EXAMPLE_VFS, totalvfs='lots\n'))),
        case('sriov/apply/totalvfs-underscore', ['apply', '--sriov-only'],
             **f(explicit % 4, pf('eno1', vfs=EXAMPLE_VFS, totalvfs=' 1_6 \n'))),
        case('sriov/apply/numvfs-is-dir', ['apply', '--sriov-only'],
             **f(pf_only, pf('eno1', vfs=EXAMPLE_VFS, numvfs={'dir': True}))),
        case('sriov/apply/numvfs-write-error', ['apply', '--sriov-only'],
             **f(pf_only, pf('eno1', vfs=EXAMPLE_VFS), {full_dev: {'symlink': '/dev/full'}})),
        case('sriov/apply/numvfs-write-error-autoprobe', ['apply', '--sriov-only'],
             **f(sriov, pf('eno1', vfs=EXAMPLE_VFS, autoprobe='1\n'), {full_dev: {'symlink': '/dev/full'}},
                 mocks={'devlink': leg})),
        case('sriov/apply/vendor-missing', ['apply', '--sriov-only'],
             **f(pf_only, pf('eno1', vfs=EXAMPLE_VFS, vendor=None))),
        case('sriov/apply/device-missing', ['apply', '--sriov-only'],
             **f(pf_only, pf('eno1', vfs=EXAMPLE_VFS, device=None))),
        case('sriov/apply/uevent-missing', ['apply', '--sriov-only'],
             **f(eswitch_only, netdev('eno1', PF_PCI), mocks={'devlink': sw})),
        case('sriov/apply/uevent-no-slot', ['apply', '--sriov-only'],
             **f(eswitch_only, pf('eno1'), {'/sys/bus/pci/devices/%s/uevent' % PF_PCI: ro('DRIVER=x\n')},
                 mocks={'devlink': sw})),
        case('sriov/apply/autoprobe-uevent-missing', ['apply', '--sriov-only'],
             **f(sriov, netdev('eno1', PF_PCI),
                 {'/sys/class/net/eno1/device': {'dir': True},
                  '/sys/class/net/eno1/device/sriov_totalvfs': ro('8\n')}, mocks={'devlink': leg})),
        case('sriov/apply/pf-match-set-name', ['apply', '--sriov-only'], **f(pf_match % 'eno1', sysfs)),
        case('sriov/apply/pf-match-three', ['apply', '--sriov-only'],
             **f(pf_match % 'pf0', pf('eno1', vfs=[]), pf('eno2', PF2_PCI), netdev('eno3', '0000:05:00.0'))),
        case('sriov/apply/pf-match-driver', ['apply', '--sriov-only'],
             **f(pf_match_driver, pf('eno1', vfs=EXAMPLE_VFS, driver='ixgbe'))),
        case('sriov/apply/vf-match-two', ['apply', '--sriov-only'], **f(vf_match_two, sysfs)),
        case('sriov/apply/two-pfs', ['apply', '--sriov-only'],
             **f(two_pfs, pf('eno1', vfs=[('enp1s16f1', '0000:03:00.2')]),
                 pf('eno2', PF2_PCI, vfs=vfs_for('x', '0000:04:00', ['enp2s16f1', 'enp2s16f2'])),
                 mocks={'devlink': devlink('legacy', pci=PF2_PCI)})),
    ]
    return out


def rebind_cases():
    bond_conf = '''network:
  version: 2
  ethernets:
    eno1: {}
    eno2: {}
  bonds:
    bond0:
      interfaces: [eno1, eno2]
%s'''
    ab = bond_conf % '      parameters:\n        mode: active-backup\n'
    rr = bond_conf % '      parameters:\n        mode: balance-rr\n'
    nomode = bond_conf % ''
    matched = '''network:
  version: 2
  ethernets:
    pf:
      match:
        name: "en*"
      set-name: eno1
  bonds:
    bond0:
      interfaces: [pf]
      parameters:
        mode: 802.3ad
'''
    lag = '/sys/kernel/debug/mlx5/%s/lag/state' % PF_PCI
    mlx = pf('eno1', vfs=EXAMPLE_VFS)
    ixgbe = pf('eno1', vfs=EXAMPLE_VFS, driver='ixgbe')
    cfg = {'/etc/netplan/a.yaml': ab}

    def f(*parts):
        files = {}
        for p in parts:
            files.update(p)
        return files

    out = []
    for dbg in ([], ['--debug']):
        d = '-debug' if dbg else ''
        out += [
            case('sriov/rebind/no-args' + d, ['rebind'] + dbg, files=f(cfg, mlx)),
            case('sriov/rebind/not-pf' + d, ['rebind'] + dbg + ['eno1'],
                 files=f(pci_dev(PF_PCI, 'ixgbe'), netdev('eno1', PF_PCI))),
            case('sriov/rebind/ixgbe' + d, ['rebind'] + dbg + ['eno1'], files=ixgbe),
            case('sriov/rebind/ixgbe-bound' + d, ['rebind'] + dbg + ['eno1'],
                 files=pf('eno1', vfs=EXAMPLE_VFS, driver='ixgbe', vf_driver='ixgbevf')),
            case('sriov/rebind/two-pfs' + d, ['rebind'] + dbg + ['eno1', 'eno2'],
                 files=f(ixgbe, pf('eno2', PF2_PCI, driver='ixgbe', vfs=[(None, '0000:04:00.2')]))),
            case('sriov/rebind/unknown-netdev' + d, ['rebind'] + dbg + ['nope0'], files=ixgbe),
            case('sriov/rebind/no-pci-slot' + d, ['rebind'] + dbg + ['eno1'],
                 files=f(ixgbe, {'/sys/bus/pci/devices/%s/uevent' % PF_PCI: ro('DRIVER=ixgbe\n')})),
            case('sriov/rebind/mlx5-no-config' + d, ['rebind'] + dbg + ['eno1'], files=mlx),
            case('sriov/rebind/mlx5-no-bond' + d, ['rebind'] + dbg + ['eno1'],
                 files=f(mlx, {'/etc/netplan/a.yaml': example('sriov.yaml')})),
            case('sriov/rebind/mlx5-lag-active' + d, ['rebind'] + dbg + ['eno1'],
                 files=f(cfg, mlx, {lag: ro('active\n')})),
            case('sriov/rebind/mlx5-lag-unreadable' + d, ['rebind'] + dbg + ['eno1'],
                 files=f(cfg, mlx, {lag: {'dir': True}})),
            case('sriov/rebind/mlx5-unsupported-mode' + d, ['rebind'] + dbg + ['eno1'],
                 files=f({'/etc/netplan/a.yaml': rr}, mlx)),
            case('sriov/rebind/mlx5-no-mode' + d, ['rebind'] + dbg + ['eno1'],
                 files=f({'/etc/netplan/a.yaml': nomode}, mlx)),
            case('sriov/rebind/mlx5-match-set-name' + d, ['rebind'] + dbg + ['eno1'],
                 files=f({'/etc/netplan/a.yaml': matched}, mlx, {lag: ro('active\n')})),
            case('sriov/rebind/mlx5-invalid-config' + d, ['rebind'] + dbg + ['eno1'],
                 files=f({'/etc/netplan/a.yaml': 'network:\n  ethernets: [\n'}, mlx)),
            case('sriov/rebind/root-dir' + d, ['rebind'] + dbg + ['--root-dir', '{ROOT}', 'eno1'],
                 files=f({'{ROOT}/etc/netplan/a.yaml': ab}, mlx, {lag: ro('active\n')})),
            case('sriov/rebind/root-dir-empty' + d, ['rebind'] + dbg + ['--root-dir', '{ROOT}', 'eno1'],
                 files=f(cfg, mlx, {lag: ro('active\n')})),
        ]
    # slow ones (they sleep for 3 and 5 seconds), only with --debug
    out += [
        case('sriov/rebind/mlx5-lag-missing-debug', ['rebind', '--debug', 'eno1'], files=f(cfg, mlx)),
        case('sriov/rebind/mlx5-lag-disabled-debug', ['rebind', '--debug', 'eno1'],
             files=f(cfg, mlx, {lag: ro('disabled\n')})),
    ]
    return out


def all_cases():
    return apply_cases() + rebind_cases()
