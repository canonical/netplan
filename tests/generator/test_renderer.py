# SPDX-License-Identifier: GPL-3.0-only
# Regression tests for per-type renderer selection.
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

import itertools
import tempfile

import yaml

import netplan
from tests.test_utils import call_cli
from .base import TestBase


class TestTypeRenderer(TestBase):
    def check_backends(self, expected):
        parser = netplan.Parser()
        parser.load_yaml_hierarchy(self.workdir.name)
        state = netplan.State()
        state.import_parser_results(parser)
        with tempfile.TemporaryFile(mode='w+') as output:
            state._dump_yaml(output)
            output.seek(0)
            parser = netplan.Parser()
            parser.load_yaml(output)
            roundtrip = netplan.State()
            roundtrip.import_parser_results(parser)
        for name, backend in expected.items():
            self.assertEqual(state[name].backend, backend)
            self.assertEqual(roundtrip[name].backend, backend)
            self.assertEqual(self.file_exists('10-netplan-' + name + '.network'), backend == 'networkd')
            self.assertEqual(self.file_exists('netplan-' + name + '.nmconnection', 'nm'), backend == 'NetworkManager')

    def test_device_override(self):
        self.generate('''network:
  renderer: networkd
  ethernets:
    dev0: {renderer: networkd}
    dev1: {}
    renderer: NetworkManager
  bridges:
    br0: {}
''')
        self.check_backends({'dev0': 'networkd', 'dev1': 'NetworkManager', 'br0': 'networkd'})

    def test_existing_definition_renderer_is_preserved(self):
        self.generate(None, confs={
            'a': '''network:
  ethernets:
    dev0: {renderer: networkd}
''',
            'b': '''network:
  renderer: networkd
  ethernets:
    dev0: {dhcp4: true}
    dev1: {}
    renderer: NetworkManager
'''})
        self.check_backends({'dev0': 'networkd', 'dev1': 'NetworkManager'})

    def test_later_device_override(self):
        self.generate(None, confs={
            'a': '''network:
  ethernets:
    dev0: {}
    renderer: NetworkManager
''',
            'b': '''network:
  ethernets:
    dev0: {renderer: networkd}
'''})
        self.check_backends({'dev0': 'networkd'})

    def test_cli_get_type_renderer(self):
        self.generate('''network:
  renderer: networkd
  ethernets:
    dev0: {}
    renderer: NetworkManager
''')
        output = call_cli(['get', '--root-dir', self.workdir.name])
        config = yaml.safe_load(output)
        self.assertEqual(config['network']['ethernets']['dev0']['renderer'], 'NetworkManager')
        self.check_backends({'dev0': 'NetworkManager'})

    def test_cli_remove_type_renderer(self):
        self.generate('''network:
  renderer: networkd
  ethernets:
    dev0: {}
    renderer: NetworkManager
''')
        call_cli(['set', 'ethernets.renderer=null', '--root-dir', self.workdir.name])
        self.generate(None)
        self.check_backends({'dev0': 'networkd'})

    def test_cli_origin_hint_with_type_renderer(self):
        self.generate('''network:
  renderer: networkd
  ethernets:
    dev0: {}
    renderer: NetworkManager
''')
        call_cli(['set', 'ethernets.dev1={}', '--origin-hint=b', '--root-dir', self.workdir.name])
        self.generate(None)
        self.check_backends({'dev0': 'NetworkManager', 'dev1': 'networkd'})


def renderer_order_case(device_type, backend, order):
    def test(self):
        other = 'networkd' if backend == 'NetworkManager' else 'NetworkManager'
        definitions = {
            'renderer': backend,
            'dev0': {'dhcp4': True},
            'dev1': {'dhcp4': True},
        }
        config = {'network': {'version': 2, 'renderer': other,
                              device_type: {key: definitions[key] for key in order}}}
        self.generate(yaml.safe_dump(config, sort_keys=False))
        self.check_backends({'dev0': backend, 'dev1': backend})
    return test


for device_type, backend, order in itertools.product(
        ('ethernets', 'bridges'), ('networkd', 'NetworkManager'),
        itertools.permutations(('renderer', 'dev0', 'dev1'))):
    name = 'test_{}_{}_{}'.format(device_type, backend, '_'.join(order))
    setattr(TestTypeRenderer, name, renderer_order_case(device_type, backend, order))
