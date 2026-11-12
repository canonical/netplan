# Parity cases for the Open vSwitch cleanup (netplan_cli/cli/ovs.py), run by
# 'netplan apply' and 'netplan apply --only-ovs-cleanup'.
#
# ovs.py runs ovs-vsctl by absolute path (/usr/bin/ovs-vsctl, or
# /snap/bin/ovs-vsctl if only that exists), so these cases place mocks there
# via "abs_mocks" (see parity.py).
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
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

USR = '/usr/bin/ovs-vsctl'
SNAP = '/snap/bin/ovs-vsctl'
# libnetplan refuses OVS configs unless ovs-vsctl exists at its compiled-in
# PREFIX/BINDIR path (/usr/local/bin with meson's default prefix); the CLI
# itself never looks there.
LIBNETPLAN = '/usr/local/bin/ovs-vsctl'
CLEANUP = ['apply', '--only-ovs-cleanup']
LIST = ['-f', 'csv', '-d', 'bare', '--no-headings', 'list']

SIMPLE = '''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
'''

with open(os.path.join(REPO, 'examples', 'openvswitch.yaml')) as f:
    OVS_EXAMPLE = f.read()

# A previous run left OVS systemd units behind, so a full 'apply' runs the
# cleanup (old_files_ovs).
OLD_OVS_UNIT = {'/run/systemd/generator.late/netplan-ovs-ovs9.service': '[Unit]\n'}


def case(id, argv, **kw):
    return dict(id='ovs/' + id, argv=argv, **kw)


def lst(table, cols='name,external-ids'):
    return ['--columns=%s' % cols] + LIST + [table]


def vsctl(port='', bridge='', iface='', ovs='', controller='', show_exit=0, rules=()):
    '''ovs-vsctl mock rules: canned 'list' output per table, plus extra rules
    (which take precedence).'''
    return {'ovs-vsctl': list(rules) + [
        {'argv': ['show'], 'exit': show_exit},
        {'argv': lst('Port'), 'stdout': port},
        {'argv': lst('Bridge'), 'stdout': bridge},
        {'argv': lst('Interface'), 'stdout': iface},
        {'argv': lst('Open_vSwitch', 'external-ids'), 'stdout': ovs},
        {'argv': lst('Controller', '_uuid,external-ids'), 'stdout': controller},
    ]}


def ovs_case(id, argv=CLEANUP, config=SIMPLE, abs_mocks=(USR,), files=None, **kw):
    fs = {'/etc/netplan/a.yaml': config} if config is not None else {}
    fs.update(files or {})
    return case(id, argv, files=fs, abs_mocks=[LIBNETPLAN] + list(abs_mocks), mocks=vsctl(**kw))


def install_cases():
    return [
        # no ovs-vsctl at all: debug message only
        case('not-installed', CLEANUP, files={'/etc/netplan/a.yaml': SIMPLE}),
        case('not-installed-debug', ['--debug'] + CLEANUP, files={'/etc/netplan/a.yaml': SIMPLE}),
        case('not-installed-ovs-config', CLEANUP, abs_mocks=[LIBNETPLAN],
             files={'/etc/netplan/a.yaml': OVS_EXAMPLE}),
        # installed but the database is not running: warning
        ovs_case('inactive', show_exit=1),
        ovs_case('inactive-debug', ['--debug'] + CLEANUP, show_exit=1),
        ovs_case('snap-inactive', abs_mocks=[SNAP], show_exit=1),
        ovs_case('snap-active', abs_mocks=[SNAP]),
        ovs_case('usr-and-snap', abs_mocks=[USR, SNAP], port='old0,"netplan=true"\n'),
        # running, nothing tagged
        ovs_case('active-empty'),
        ovs_case('active-untagged', port='p0,""\np1,"foo=bar"\n', bridge='br0,""\n'),
        ovs_case('active-no-config', config=None, port='old0,"netplan=true"\n'),
    ]


def teardown_cases():
    port = 'patch0-1,"netplan=true"\nbond0,"netplan=true"\nold0,"netplan=true"\nforeign0,"x=y"\n'
    bridge = 'ovs0,"netplan=true"\noldbr0,"netplan=true"\n'
    iface = ('patch1-0,"netplan=true"\noldpatch0,"netplan=true"\nvlan-fake0,"netplan=true"\n'
             'eth0,"netplan=true"\n')
    br_exists = [{'argv': ['br-exists', 'oldpatch0'], 'exit': 2},
                 {'argv': ['br-exists', 'vlan-fake0'], 'exit': 0},
                 {'argv': ['br-exists', 'eth0'], 'exit': 1}]
    return [
        ovs_case('teardown-simple-config', port=port, bridge=bridge, iface=iface, rules=br_exists),
        ovs_case('teardown-ovs-config', config=OVS_EXAMPLE, port=port, bridge=bridge, iface=iface,
                 rules=br_exists),
        ovs_case('teardown-debug', ['--debug'] + CLEANUP, config=OVS_EXAMPLE, port=port, bridge=bridge,
                 iface=iface, rules=br_exists),
        ovs_case('teardown-crlf', port='old0,"netplan=true"\r\nold1,"netplan=true"\r\n'),
        ovs_case('teardown-no-comma', port='old0 netplan=true\n'),
        ovs_case('teardown-del-port-fails', port='old0,"netplan=true"\nold1,"netplan=true"\n',
                 rules=[{'prefix': ['--if-exists', 'del-port', 'old0'], 'exit': 1}]),
        ovs_case('teardown-del-bond-iface-fails', iface='old0,"netplan=true"\n',
                 rules=[{'prefix': ['br-exists'], 'exit': 2},
                        {'prefix': ['--if-exists', 'del-bond-iface'], 'exit': 4, 'stderr': 'boom\n'}]),
        ovs_case('teardown-br-exists-output', iface='old0,"netplan=true"\n',
                 rules=[{'prefix': ['br-exists'], 'exit': 0, 'stdout': 'out\n', 'stderr': 'err\n'}]),
        ovs_case('list-port-fails', rules=[{'argv': lst('Port'), 'exit': 1, 'stderr': 'database error\n'}]),
        ovs_case('list-controller-fails', port='old0,"netplan=true"\n',
                 rules=[{'argv': lst('Controller', '_uuid,external-ids'), 'exit': 3}]),
    ]


def settings_cases():
    bridge = ('ovs0,"netplan=true netplan/global/set-fail-mode=secure netplan/mcast_snooping_enable=true '
              'netplan/rstp_enable=false netplan/external-ids/iface-id=myhostname '
              'netplan/other-config/disable-in-band=true netplan/protocols=OpenFlow10,OpenFlow11 '
              'netplan/global/set-controller=unix:/var/run/openvswitch/ovs0.mgmt,tcp:1.2.3.4:5"\n')
    port = 'bond0,"netplan=true netplan/lacp=passive netplan/other-config/lacp-time=fast"\n'
    iface = 'eth0,"netplan/external-ids/iface-id=mylocaliface netplan/other-config/disable-in-band=false"\n'
    ovs = ('"netplan/global/set-ssl=/private/key.pem,/another/cert.pem,/some/ca-cert.pem '
           'netplan/external-ids/somekey=somevalue netplan/other-config/key=value '
           'netplan/protocols=OpenFlow13"\n')
    controller = '6c2c4b0e-0000-4000-8000-000000000001,"netplan/connection_mode=out-of-band"\n'
    getters = [
        {'argv': ['get-fail-mode', 'ovs0'], 'stdout': 'secure\n'},
        {'argv': ['get-controller', 'ovs0'], 'stdout': 'unix:/var/run/openvswitch/ovs0.mgmt\ntcp:1.2.3.4:5\n'},
        {'argv': ['get-ssl'], 'stdout': 'Private key: /private/key.pem\nCertificate: /another/cert.pem\n'
                                        'CA Certificate: /some/ca-cert.pem\nBootstrap: false\n'},
    ]
    other = [
        {'argv': ['get-fail-mode', 'ovs0'], 'stdout': 'standalone\n'},
        {'argv': ['get-controller', 'ovs0'], 'stdout': 'unix:/var/run/openvswitch/ovs0.mgmt\n'},
        {'argv': ['get-ssl'], 'stdout': 'Private key: /other/key.pem\n'},
    ]
    all_tables = dict(port=port, bridge=bridge, iface=iface, ovs=ovs, controller=controller)
    return [
        ovs_case('settings-all', config=OVS_EXAMPLE, rules=getters, **all_tables),
        ovs_case('settings-all-debug', ['--debug'] + CLEANUP, config=OVS_EXAMPLE, rules=getters, **all_tables),
        ovs_case('settings-not-ours', config=OVS_EXAMPLE, rules=other, **all_tables),
        ovs_case('settings-simple-config', rules=getters, **all_tables),
        ovs_case('settings-ssl', ovs='"netplan/global/set-ssl=/k.pem,/c.pem,/ca.pem"\n',
                 rules=[{'argv': ['get-ssl'], 'stdout': '/k.pem /c.pem /ca.pem\n'}]),
        ovs_case('settings-fail-mode', bridge='br0,"netplan/global/set-fail-mode=standalone"\n',
                 rules=[{'argv': ['get-fail-mode', 'br0'], 'stdout': 'standalone\n'}]),
        ovs_case('settings-controller-row', controller='abc,"netplan/target=tcp:1.2.3.4 netplan/x/y=z"\n'),
        ovs_case('settings-mandatory-defaults',
                 bridge='br0,"netplan/mcast_snooping_enable=false netplan/rstp_enable=true"\n'),
        ovs_case('settings-weird-entries',
                 bridge='br0,"netplan/ netplan/noval netplan/=x netplan/a/b/c=d=e foo/netplan/x=1 netplan/global=g"\n'),
        ovs_case('settings-ovs-row-with-comma', ovs='"netplan/external-ids/a=b,c netplan/global/set-ssl=x"\n',
                 rules=[{'argv': ['get-ssl'], 'stdout': ''}]),
        ovs_case('settings-empty-iface', bridge=',"netplan/global/set-fail-mode=secure"\n',
                 rules=[{'argv': ['get-fail-mode'], 'stdout': 'secure\n'}]),
        ovs_case('settings-no-comma', bridge='br0 netplan/foo=bar\n'),
        ovs_case('settings-unknown-global', bridge='br0,"netplan/global/set-foo=bar"\n'),
        ovs_case('settings-unknown-global-quote', bridge='br0,"netplan/global/it\'s=bar"\n'),
        ovs_case('settings-get-fails', bridge='br0,"netplan/global/set-fail-mode=secure"\n',
                 rules=[{'argv': ['get-fail-mode', 'br0'], 'exit': 1, 'stderr': 'no bridge\n'}]),
        ovs_case('settings-del-fails', bridge='br0,"netplan/global/set-fail-mode=secure"\n',
                 rules=[{'argv': ['get-fail-mode', 'br0'], 'stdout': 'secure\n'},
                        {'argv': ['del-fail-mode', 'br0'], 'exit': 2}]),
        ovs_case('settings-remove-fails', port='p0,"netplan/lacp=active netplan/x=y"\n',
                 rules=[{'prefix': ['remove', 'Port', 'p0', 'lacp'], 'exit': 1}]),
        ovs_case('settings-remove-tag-fails', port='p0,"netplan/lacp=active"\n',
                 rules=[{'prefix': ['remove', 'Port', 'p0', 'external-ids'], 'exit': 1}]),
        ovs_case('settings-set-default-fails', bridge='br0,"netplan/rstp_enable=true"\n',
                 rules=[{'prefix': ['set'], 'exit': 5}]),
    ]


def apply_cases():
    out = []
    # The OVS examples, through a full 'apply' (with a previous OVS unit, so
    # the cleanup runs) and through '--only-ovs-cleanup'
    for path in sorted(glob.glob(os.path.join(REPO, 'examples', 'openvswitch*.yaml'))):
        stem = os.path.basename(path)[:-len('.yaml')]
        with open(path) as f:
            content = f.read()
        tagged = dict(port='old0,"netplan=true"\npatch0-1,"netplan=true netplan/lacp=off"\n',
                      bridge='ovs0,"netplan=true netplan/global/set-fail-mode=secure"\n',
                      rules=[{'argv': ['get-fail-mode', 'ovs0'], 'stdout': 'secure\n'}])
        out += [
            ovs_case('example/%s/only-cleanup' % stem, config=content, **tagged),
            ovs_case('example/%s/apply' % stem, ['apply'], config=content, **tagged),
            ovs_case('example/%s/apply-old-units' % stem, ['apply'], config=content, files=OLD_OVS_UNIT,
                     **tagged),
            ovs_case('example/%s/apply-inactive' % stem, ['apply'], config=content, files=OLD_OVS_UNIT,
                     show_exit=1),
            case('example/%s/apply-not-installed' % stem, ['apply'], abs_mocks=[LIBNETPLAN],
                 files=dict(OLD_OVS_UNIT, **{'/etc/netplan/a.yaml': content})),
            case('example/%s/apply-libnetplan-no-ovs' % stem, ['apply'],
                 files=dict(OLD_OVS_UNIT, **{'/etc/netplan/a.yaml': content})),
        ]
    out += [
        ovs_case('apply/old-units-simple', ['apply'], files=OLD_OVS_UNIT, port='old0,"netplan=true"\n'),
        ovs_case('apply/old-units-list-fails', ['apply'], files=OLD_OVS_UNIT,
                 rules=[{'argv': lst('Port'), 'exit': 1}]),
        ovs_case('apply/old-units-unknown-global', ['apply'], files=OLD_OVS_UNIT,
                 bridge='br0,"netplan/global/set-foo=bar"\n'),
        ovs_case('invalid-config', config='network:\n  ethernets: [\n'),
        ovs_case('invalid-config-inactive', config='network:\n  ethernets: [\n', show_exit=1),
    ]
    return out


def all_cases():
    return install_cases() + teardown_cases() + settings_cases() + apply_cases()
