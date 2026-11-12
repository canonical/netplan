# Case definitions for the parity runner (parity.py).
#
# A case is a dict:
#   id     unique name
#   argv   CLI arguments; "{ROOT}" is replaced by the sandbox root directory
#   files  {path: content | {"content", "mode"} | {"symlink"} | {"dir": True}}
#          where path is "{ROOT}/..." or under one of the sandboxed system
#          directories (/etc/netplan, /etc/network, /run, /sys/class/net,
#          /usr/lib/netplan); files default to mode 0600
#   mocks  {command: [rule, ...]}, see mock_cmd.py
#   env    extra environment variables
#   abs_mocks  absolute paths at which to also place mocks (logged and
#          replayed like the $PATH mock of the same basename), for commands
#          run by full path, e.g. ["/usr/bin/ovs-vsctl"]
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

import glob
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COMMANDS = ['apply', 'generate', 'get', 'info', 'ip', 'migrate', 'rebind', 'set', 'status', 'try']

SIMPLE = '''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
'''

TWO_FILES = {
    '{ROOT}/etc/netplan/10-base.yaml': '''network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true
      nameservers:
        addresses: [8.8.8.8]
    eth1:
      addresses: [10.0.0.2/24]
''',
    '{ROOT}/etc/netplan/90-override.yaml': '''network:
  ethernets:
    eth0:
      dhcp4: false
      dhcp6: true
''',
}


def case(id, argv, **kw):
    return dict(id=id, argv=argv, **kw)


def args_cases():
    root = {'files': {'{ROOT}/etc/netplan/a.yaml': SIMPLE}}
    out = [
        case('args/none', []),
        case('args/unknown-global-option', ['--bogus']),
        case('args/debug-only', ['--debug']),
        case('args/help-command', ['help']),
        case('args/-h', ['-h']),
        case('args/--help', ['--help']),
        case('args/unknown-command', ['nonexistent']),
        case('args/abbrev-global-option', ['--deb', 'info']),
        case('args/abbrev-option', ['info', '--js']),
        case('args/info-json-and-yaml', ['info', '--json', '--yaml']),
        case('args/get-abbrev-root-dir', ['get', '--root', '{ROOT}'], **root),
        case('args/get-unknown-option', ['get', '--bogus', '--root-dir', '{ROOT}'], **root),
        case('args/get-help-word', ['get', 'help']),
        case('args/get-two-keys', ['get', '--root-dir', '{ROOT}', 'network', 'ethernets'], **root),
        case('args/get-root-dir-missing-value', ['get', '--root-dir']),
        case('args/get-root-dir-equals', ['get', '--root-dir={ROOT}'], **root),
        case('args/set-no-key', ['set', '--root-dir', '{ROOT}'], **root),
        case('args/set-two-keys', ['set', '--root-dir', '{ROOT}', 'ethernets.eth0.dhcp6=true',
                                   'ethernets.eth0.dhcp4=false'], **root),
        case('args/debug-after-command', ['get', '--debug', '--root-dir', '{ROOT}'], **root),
        case('args/migrate-without-test-commands', ['migrate', '--dry-run']),
        case('args/migrate-with-test-commands', ['migrate', '--dry-run'], env={'ENABLE_TEST_COMMANDS': '1'}),
        case('args/double-dash', ['--', 'info']),
    ]
    for cmd in COMMANDS:
        out.append(case('args/cmd/%s-unknown-option' % cmd, [cmd, '--bogus-option'], **root))
        out.append(case('args/cmd/%s--h' % cmd, [cmd, '-h']))
    return out


def example_cases():
    out = []
    exdir = os.path.join(REPO, 'examples')
    for name in sorted(os.listdir(exdir)):
        if not name.endswith('.yaml'):
            continue
        with open(os.path.join(exdir, name)) as f:
            content = f.read()
        stem = name[:-len('.yaml')]
        rooted = {'files': {'{ROOT}/etc/netplan/' + name: content}}
        system = {'files': {'/etc/netplan/' + name: content}}
        out += [
            case('example/%s/get' % stem, ['get', '--root-dir', '{ROOT}'], **rooted),
            case('example/%s/get-ethernets' % stem, ['get', '--root-dir', '{ROOT}', 'ethernets'], **rooted),
            case('example/%s/set' % stem, ['set', '--root-dir', '{ROOT}', 'ethernets.parity0.dhcp4=true'], **rooted),
            case('example/%s/generate' % stem, ['generate', '--root-dir', '{ROOT}'], **rooted),
            case('example/%s/apply' % stem, ['apply'], **system),
        ]
    return out


def get_set_cases():
    base = {'files': dict(TWO_FILES)}
    out = []
    for key in ['', 'all', 'network', 'ethernets', 'ethernets.eth0', 'network.ethernets.eth0.dhcp4',
                'ethernets.eth0.nameservers.addresses', 'renderer', 'version', 'ethernets.nope',
                'bad..key', '.', 'ethernets.eth0.dhcp4.too.deep', 'ETHERNETS']:
        argv = ['get', '--root-dir', '{ROOT}'] + ([key] if key else [])
        out.append(case('get/key=%s' % (key or '<none>'), argv, **base))
    for i, expr in enumerate([
        'ethernets.eth0.dhcp4=true',
        'network.ethernets.eth2.addresses=[10.1.1.1/24, "10.2.2.2/24"]',
        'ethernets.eth0=null',
        'ethernets.eth1.addresses=null',
        'ethernets=null',
        'ethernets.eth0.mtu=1500',
        'ethernets.eth0.mtu="1500"',
        'ethernets.eth0.dhcp4=yes',
        'ethernets.eth0.dhcp4=maybe',
        'ethernets.eth0={dhcp4: true, dhcp6: false}',
        'ethernets.eth0=[',
        'ethernets.eth0.dhcp4',
        'ethernets.eth0.dhcp4=',
        'renderer=NetworkManager',
        'version=3',
        'bridges.br0.interfaces=[eth1]',
        'ethernets.eth0.nameservers.addresses=[1.1.1.1]',
        'ethernets.eth0.unknown-key=1',
        'ethernets.eth 0.dhcp4=true',
        'a=b=c',
    ]):
        out.append(case('set/%02d %s' % (i, expr), ['set', '--root-dir', '{ROOT}', expr], **base))
    out += [
        case('set/origin-hint', ['set', '--root-dir', '{ROOT}', '--origin-hint', 'parity',
                                 'ethernets.eth0.dhcp4=true'], **base),
        case('set/origin-hint-null', ['set', '--root-dir', '{ROOT}', '--origin-hint', '90-override',
                                      'ethernets.eth0=null'], **base),
        case('set/origin-hint-empty', ['set', '--root-dir', '{ROOT}', '--origin-hint', '',
                                       'ethernets.eth0.dhcp4=true'], **base),
        case('set/empty-root', ['set', '--root-dir', '{ROOT}', 'ethernets.eth0.dhcp4=true']),
        case('set/system-etc-netplan', ['set', 'ethernets.eth0.dhcp4=true'],
             files={'/etc/netplan/a.yaml': SIMPLE}),
    ]
    return out


def config_error_cases():
    def files(content, mode=0o600, name='a.yaml'):
        return {'{ROOT}/etc/netplan/' + name: {'content': content, 'mode': mode}}
    # Not covered: a directory named *.yaml makes libnetplan report a random
    # error message (uninitialised memory in the C parser), in both CLIs.
    variants = {
        'world-readable': files(SIMPLE, 0o644),
        'group-readable': files(SIMPLE, 0o640),
        'unreadable': files(SIMPLE, 0o000),
        'invalid-yaml': files('network:\n  ethernets:\n    eth0: [\n'),
        'tab-indent': files('network:\n\tversion: 2\n'),
        'unknown-key': files('network:\n  version: 2\n  ethernets:\n    eth0:\n      bogus: 1\n'),
        'bad-bool': files('network:\n  version: 2\n  ethernets:\n    eth0:\n      dhcp4: maybe\n'),
        'bad-version': files('network:\n  version: 1\n'),
        'empty-file': files(''),
        'not-network': files('foo: bar\n'),
        'validation': files('network:\n  version: 2\n  bridges:\n    br0:\n      interfaces: [missing0]\n'),
        'non-yaml-ext': files(SIMPLE, name='a.yml'),
        'symlink-dangling': {'{ROOT}/etc/netplan/a.yaml': {'symlink': '/nonexistent'}},
    }
    out = []
    for name, f in sorted(variants.items()):
        out.append(case('config/%s/get' % name, ['get', '--root-dir', '{ROOT}'], files=f))
        out.append(case('config/%s/generate' % name, ['generate', '--root-dir', '{ROOT}'], files=f))
        out.append(case('config/%s/set' % name, ['set', '--root-dir', '{ROOT}', 'ethernets.eth9.dhcp4=true'], files=f))
    out.append(case('config/missing-root-dir', ['get', '--root-dir', '/nonexistent/root']))
    return out


def info_cases():
    return [case('info/' + ' '.join(a or ['<none>']), ['info'] + a)
            for a in ([], ['--json'], ['--yaml'], ['--debug'])]


def generate_cases():
    f = {'/etc/netplan/a.yaml': SIMPLE}
    return [
        case('generate/system', ['generate'], files=f),
        case('generate/mapping', ['generate', '--mapping', 'eth0'], files=f),
        case('generate/mapping-missing', ['generate', '--mapping', 'nope0'], files=f),
        case('generate/try-stamp', ['generate'], files=dict(f, **{'/run/netplan/netplan-try.ready': ''})),
        case('generate/daemon-reload-fails', ['generate'], files=f,
             mocks={'systemctl': [{'prefix': ['daemon-reload'], 'exit': 3}]}),
        case('generate/no-config', ['generate']),
        case('generate/snap-busctl', ['generate'], files=f, env={'SNAP': '/snap/netplan/1'}),
    ]


def apply_cases():
    f = {'/etc/netplan/a.yaml': SIMPLE}
    nm = {'/etc/netplan/a.yaml': SIMPLE.replace('version: 2', 'version: 2\n  renderer: NetworkManager')}
    sysnet = {'/sys/class/net/eth0/address': {'content': '00:11:22:33:44:55\n', 'mode': 0o644},
              '/sys/class/net/eth0/ifindex': {'content': '2\n', 'mode': 0o644}}
    return [
        case('apply/simple', ['apply'], files=f),
        case('apply/nm', ['apply'], files=nm),
        case('apply/no-config', ['apply']),
        case('apply/with-sysfs', ['apply'], files=dict(f, **sysnet)),
        case('apply/previous-run-state', ['apply'], files=dict(f, **{
            '/run/systemd/network/10-netplan-eth9.network': '[Match]\nName=eth9\n'})),
        case('apply/sriov-only', ['apply', '--sriov-only'], files=f),
        case('apply/only-ovs-cleanup', ['apply', '--only-ovs-cleanup'], files=f),
        case('apply/daemon-reload-fails', ['apply'], files=f,
             mocks={'systemctl': [{'prefix': ['daemon-reload'], 'exit': 1}]}),
        case('apply/udevadm-fails', ['apply'], files=f, mocks={'udevadm': [{'exit': 1}]}),
        case('apply/invalid-config', ['apply'], files={'/etc/netplan/a.yaml': 'network:\n  ethernets: [\n'}),
    ]


def ip_cases():
    lease = '# This is private data. Do not parse.\nADDRESS=192.168.1.10\nNETMASK=255.255.255.0\n'
    sysnet = {'/sys/class/net/eth0/ifindex': {'content': '2\n', 'mode': 0o644}}
    f = {'{ROOT}/etc/netplan/a.yaml': SIMPLE}
    return [
        case('ip/leases-no-iface', ['ip', 'leases', '--root-dir', '{ROOT}'], files=f),
        case('ip/leases-unknown-iface', ['ip', 'leases', '--root-dir', '{ROOT}', 'nope0'], files=f),
        case('ip/leases-no-lease', ['ip', 'leases', '--root-dir', '{ROOT}', 'eth0'], files=dict(f, **sysnet)),
        case('ip/leases-networkd', ['ip', 'leases', '--root-dir', '{ROOT}', 'eth0'],
             files=dict(f, **sysnet, **{'{ROOT}/run/systemd/netif/leases/2': lease})),
        case('ip/no-subcommand', ['ip']),
    ]


def migrate_cases():
    env = {'ENABLE_TEST_COMMANDS': '1'}
    ifaces = {
        'empty': '',
        'loopback-only': 'auto lo\niface lo inet loopback\n',
        'static': 'auto eth1\niface eth1 inet static\n  address 10.0.0.2/24\n  gateway 10.0.0.1\n',
        'static-netmask': 'auto eth1\niface eth1 inet static\n  address 10.0.0.2\n  netmask 255.255.255.0\n',
        'dhcp': 'auto eth0\niface eth0 inet dhcp\n',
        'dhcp6': 'auto eth0\niface eth0 inet6 dhcp\n',
        'dns': 'auto eth0\niface eth0 inet dhcp\n  dns-nameservers 1.1.1.1 8.8.8.8\n  dns-search example.com\n',
        'non-auto': 'iface eth0 inet dhcp\n',
        'allow-hotplug': 'allow-hotplug eth0\niface eth0 inet dhcp\n',
        'mapping': 'mapping eth0\n  script /bin/true\n',
        'source': 'source /etc/network/interfaces.d/*\nauto eth0\niface eth0 inet dhcp\n',
        'hwaddress': 'auto eth0\niface eth0 inet dhcp\n  hwaddress ether 00:11:22:33:44:55\n',
        'mtu': 'auto eth0\niface eth0 inet static\n  address 10.0.0.2/24\n  mtu 9000\n',
        'unsupported-option': 'auto eth0\niface eth0 inet dhcp\n  hostname foo\n',
        'manual': 'auto eth0\niface eth0 inet manual\n',
        'garbage': 'this is not interfaces syntax\n',
        'continuation': 'auto eth0\niface eth0 inet static \\\n  address 10.0.0.2/24\n',
    }
    out = []
    for name, content in sorted(ifaces.items()):
        f = {'{ROOT}/etc/network/interfaces': content}
        out.append(case('migrate/%s/dry-run' % name, ['migrate', '--root-dir', '{ROOT}', '--dry-run'], files=f, env=env))
        out.append(case('migrate/%s/write' % name, ['migrate', '--root-dir', '{ROOT}'], files=f, env=env))
    out.append(case('migrate/no-interfaces-file', ['migrate', '--root-dir', '{ROOT}', '--dry-run'], env=env))
    out.append(case('migrate/existing-netplan', ['migrate', '--root-dir', '{ROOT}'], env=env, files={
        '{ROOT}/etc/network/interfaces': ifaces['dhcp'], '{ROOT}/etc/netplan/a.yaml': SIMPLE}))
    return out


def misc_cases():
    f = {'/etc/netplan/a.yaml': SIMPLE}
    return [
        case('status/no-mocks', ['status'], files=f),
        case('status/json-no-mocks', ['status', '--format', 'json'], files=f),
        case('status/bad-format', ['status', '--format', 'xml'], files=f),
        case('try/non-interactive', ['try', '--timeout', '1'], files=f, timeout=20),
        case('rebind/no-args', ['rebind'], files=f),
        case('rebind/iface', ['rebind', 'eth0'], files=f),
    ]


def extra_cases():
    '''Cases from tests/parity/cases_*.py, each defining all_cases().'''
    out = []
    for path in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cases_*.py'))):
        spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out += module.all_cases()
    return out


def all_cases():
    return (args_cases() + example_cases() + get_set_cases() + config_error_cases() + info_cases() +
            generate_cases() + apply_cases() + ip_cases() + migrate_cases() + misc_cases() + extra_cases())
