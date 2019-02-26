#
# Command-line arguments handling tests for generator
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel.lapierre@canonical.com>
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

import os
import sys
import subprocess

from .base import TestBase, exe_generate


class TestConfigArgs(TestBase):
    '''Config file argument handling'''

    def test_no_files(self):
        subprocess.check_call([exe_generate, '--root-dir', self.workdir.name])
        self.assertEqual(os.listdir(self.workdir.name), [])
        self.assert_nm_udev(None)

    def test_no_configs(self):
        self.generate('network:\n  version: 2')
        # should not write any files
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])
        self.assert_nm_udev(None)

    def test_empty_config(self):
        self.generate('')
        # should not write any files
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])
        self.assert_nm_udev(None)

    def test_file_args(self):
        conf = os.path.join(self.workdir.name, 'config')
        with open(conf, 'w') as f:
            f.write('network: {}')
        # when specifying custom files, it should ignore the global config
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', extra_args=[conf])
        self.assertEqual(set(os.listdir(self.workdir.name)), {'config', 'etc'})

    def test_file_args_notfound(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', expect_fail=True, extra_args=['/non/existing/config'])
        self.assertEqual(err, 'Cannot open /non/existing/config: No such file or directory\n')
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])

    def test_help(self):
        conf = os.path.join(self.workdir.name, 'etc', 'netplan', 'a.yaml')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''')

        p = subprocess.Popen([exe_generate, '--root-dir', self.workdir.name, '--help'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        (out, err) = p.communicate()
        self.assertEqual(err, '')
        self.assertEqual(p.returncode, 0)
        self.assertIn('Usage:', out)
        self.assertEqual(os.listdir(self.workdir.name), ['etc'])

    def test_unknown_cli_args(self):
        p = subprocess.Popen([exe_generate, '--foo'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        (out, err) = p.communicate()
        self.assertIn('nknown option --foo', err)
        self.assertNotEqual(p.returncode, 0)

    def test_output_mkdir_error(self):
        conf = os.path.join(self.workdir.name, 'config')
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''')
        err = self.generate('', extra_args=['--root-dir', '/proc/foo', conf], expect_fail=True)
        self.assertIn('cannot create directory /proc/foo/run/systemd/network', err)

    def test_systemd_generator(self):
        conf = os.path.join(self.confdir, 'a.yaml')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''')
        outdir = os.path.join(self.workdir.name, 'out')
        os.mkdir(outdir)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        subprocess.check_call([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir])
        n = os.path.join(self.workdir.name, 'run', 'systemd', 'network', '10-netplan-eth0.network')
        self.assertTrue(os.path.exists(n))
        os.unlink(n)

        # should auto-enable networkd and -wait-online
        self.assertTrue(os.path.islink(os.path.join(
            outdir, 'network-online.target.wants', 'systemd-networkd.service')))
        self.assertTrue(os.path.islink(os.path.join(
            outdir, 'network-online.target.wants', 'systemd-networkd-wait-online.service')))

        # should be a no-op the second time while the stamp exists
        out = subprocess.check_output([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir],
                                      stderr=subprocess.STDOUT)
        self.assertFalse(os.path.exists(n))
        self.assertIn(b'netplan generate already ran', out)

        # after removing the stamp it generates again, and not trip over the
        # existing enablement symlink
        os.unlink(os.path.join(outdir, 'netplan.stamp'))
        subprocess.check_output([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir])
        self.assertTrue(os.path.exists(n))

    def test_systemd_generator_noconf(self):
        outdir = os.path.join(self.workdir.name, 'out')
        os.mkdir(outdir)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        subprocess.check_call([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir])
        # no enablement symlink here
        self.assertEqual(os.listdir(outdir), ['netplan.stamp'])

    def test_systemd_generator_badcall(self):
        outdir = os.path.join(self.workdir.name, 'out')
        os.mkdir(outdir)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        try:
            subprocess.check_output([generator, '--root-dir', self.workdir.name],
                                    stderr=subprocess.STDOUT)
            self.fail("direct systemd generator call is expected to fail, but succeeded.")  # pragma: nocover
        except subprocess.CalledProcessError as e:
            self.assertEqual(e.returncode, 1)
            self.assertIn(b'can not be called directly', e.output)
