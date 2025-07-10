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
import subprocess

from .base import TestBase, exe_configure, exe_generate, OVS_CLEANUP


class TestConfigArgs(TestBase):
    '''Config file argument handling'''

    def test_invalid_args(self):
        # Systemd generator stage
        generator = os.path.join(self.workdir.name, 'usr', 'local_test', 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)
        try:
            subprocess.check_output([generator, '--root-dir', self.workdir.name,
                                     self.generator_dir, self.generator_early_dir, self.generator_late_dir,
                                     '--invalid-arg'],
                                    stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.assertIn('failed to parse options: Unknown option --invalid-arg', e.output)
            self.assertEqual(e.returncode, 1)

        # Netplan configure stage
        try:
            subprocess.check_output([exe_configure, '--root-dir', self.workdir.name, '--invalid-arg'],
                                    stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            self.assertIn('failed to parse options: Unknown option --invalid-arg', e.output)
            self.assertEqual(e.returncode, 1)

    def test_no_files(self):
        # Systemd generator stage
        generator = os.path.join(self.workdir.name, 'usr', 'local_test', 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)
        try:
            subprocess.check_output([generator, '--root-dir', self.workdir.name,
                                     self.generator_dir, self.generator_early_dir, self.generator_late_dir],
                                    stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:  # pragma: nocover (debug output)
            self.fail(f"systemd generator failed: {e.output.strip()}")

        # Netplan configure stage
        subprocess.check_call([exe_configure, '--root-dir', self.workdir.name])
        # nothing is generated in /run besides the netplan-ovs-cleanup.service.
        # We only have the sd-generator in usr/lib/systemd/system-generators
        # (or rather usr/local_test/)
        self.assertEqual(os.listdir(self.workdir.name), ['usr', 'run'])
        self.assert_networkd(None)
        self.assert_networkd_udev(None)
        self.assert_nm(None)
        self.assert_nm_udev(None)
        self.assert_ovs({'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})

    def test_no_configs(self):
        self.generate('network:\n  version: 2')
        # should not write any files
        self.assertEqual(set(os.listdir(self.workdir.name)) - {'usr'}, {'etc', 'run'})
        self.assert_networkd(None)
        self.assert_networkd_udev(None)
        self.assert_nm(None)
        self.assert_nm_udev(None)
        self.assert_ovs({'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})
        # should not touch -wait-online
        service_dir = os.path.join(self.workdir.name, 'run', 'systemd', 'system')
        override = os.path.join(service_dir, 'systemd-networkd-wait-online.service.d', '10-netplan.conf')
        self.assertFalse(os.path.isfile(override))

    def test_empty_config(self):
        self.generate('')
        # should not write any files
        self.assertEqual(set(os.listdir(self.workdir.name)) - {'usr'}, {'etc', 'run'})
        self.assert_networkd(None)
        self.assert_networkd_udev(None)
        self.assert_nm(None)
        self.assert_nm_udev(None)
        self.assert_ovs({'cleanup.service': OVS_CLEANUP % {'iface': 'cleanup'}})

    def test_generate_fails_during_try(self):
        os.makedirs(self.rundir, mode=0o700, exist_ok=True)
        open(os.path.join(self.rundir, "netplan-try.ready"), "w").close()

        self.generate('network:\n  version: 2', expect_fail=True)

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
        # There is one systemd service unit 'netplan-ovs-cleanup.service' in /run,
        # which will always be created
        self.assertEqual(set(os.listdir(self.workdir.name)) - {'usr'}, {'config', 'etc', 'run'})
        self.assert_networkd(None)
        self.assert_networkd_udev(None)
        self.assert_nm(None)
        self.assert_nm_udev(None)

    def test_file_args_notfound(self):
        err = self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''', expect_fail=True, extra_args=['/non/existing/config'])
        self.assertEqual(err, 'Cannot stat /non/existing/config: No such file or directory\n')
        # No backend configuration was generated
        self.assert_networkd(None)
        self.assert_networkd_udev(None)
        self.assert_nm(None)
        self.assert_nm_udev(None)

    def test_help(self):
        conf = os.path.join(self.workdir.name, 'etc', 'netplan', 'a.yaml')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true''')
        os.chmod(conf, mode=0o600)

        p = subprocess.Popen([exe_generate, '--root-dir', self.workdir.name, '--help'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
        (out, err) = p.communicate()
        self.assertEqual(err, '')
        self.assertEqual(p.returncode, 0)
        self.assertIn('Usage:', out)
        self.assertEqual(set(os.listdir(self.workdir.name)) - {'usr'}, {'etc'})

    def test_unknown_cli_args(self):
        p = subprocess.Popen([exe_generate, '--foo'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True)
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
        # can be /proc/foor/run/systemd/{network,system}
        self.assertIn('cannot create directory /proc/foo/run/systemd/', err)

    def test_systemd_generator(self):
        conf = os.path.join(self.confdir, 'a.yaml')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as f:
            f.write('''network:
  version: 2
  ethernets:
    eth99:
      dhcp4: true
    eth98:
      dhcp4: true
      optional: true
    lo:
      addresses: ["127.0.0.1/8", "::1/128"]
  vlans:
    eth99.42:  # link-local is ignored for bridge-members
      link: eth99
      id: 42
      link-local: [ipv4, ipv6]
    eth99.43: # no link-local, but routable IP
      link: eth99
      id: 43
      link-local: []
      addresses: [10.0.0.2/24]
    eth99.44: # link-loal, but no routable IP
      link: eth99
      id: 44
      link-local: [ipv6]
    eth99.45: # ignore-carrier & no link-local, but routable IP
      link: eth99
      id: 45
      link-local: []
      ignore-carrier: true
      addresses: [10.0.0.3/24]
    eth99.46: # routable, but optional. So no wait-online log message about this bond member
      link: eth99
      id: 46
      dhcp4: true
      optional: true
  bonds:
    bond0:
      dhcp4: true
      interfaces: [eth99.42, eth99.43, eth99.46]''')
        os.chmod(conf, mode=0o600)

        generator = os.path.join(self.workdir.name, 'usr', 'local_test', 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        local_env = os.environ.copy()
        local_env['G_MESSAGES_DEBUG'] = 'all'
        out = ''
        try:
            out = subprocess.check_output([generator, '--root-dir', self.workdir.name,
                                           self.generator_dir, self.generator_early_dir, self.generator_late_dir],
                                          stderr=subprocess.STDOUT, text=True, env=local_env)
        except subprocess.CalledProcessError as e:  # pragma: nocover (debug output)
            self.fail(f"systemd generator failed: {e.output.strip()}")
        self.assert_networkd(None)  # we're only executing the sd-generator here, not the ./configure stage

        # check log message about bonds wait-online
        self.assertIn('Not all bond members need to be connected for bond0 to be ready.', out)
        self.assertIn('Consider marking eth99.42 as "optional: true", to avoid blocking systemd-networkd-wait-online.', out)
        self.assertNotIn('making eth99.43 as "optional: true"', out)  # routable
        self.assertNotIn('making eth99.46 as "optional: true"', out)  # optional

        # should auto-enable networkd and -wait-online
        self.assertTrue(os.path.islink(os.path.join(
            self.generator_dir, 'multi-user.target.wants', 'systemd-networkd.service')))
        self.assertTrue(os.path.islink(os.path.join(
            self.generator_dir, 'network-online.target.wants', 'systemd-networkd-wait-online.service')))
        override = os.path.join(self.generator_late_dir, 'systemd-networkd-wait-online.service.d', '10-netplan.conf')
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            # eth99 does not exist on the system, so will not be listed
            self.assertEqual(f.read(), '''[Unit]
ConditionPathIsSymbolicLink=/run/systemd/generator/network-online.target.wants/systemd-networkd-wait-online.service
After=systemd-resolved.service

[Service]
ExecStart=
ExecStart=/lib/systemd/systemd-networkd-wait-online -i eth99.43:carrier -i lo:carrier \
-i eth99.42:carrier -i eth99.44:degraded -i bond0:degraded
ExecStart=/lib/systemd/systemd-networkd-wait-online --any --dns -o routable -i eth99.43 -i eth99.45 -i bond0\n''')

        # should be a no-op the second time while the stamp exists
        out = subprocess.check_output([generator, '--root-dir', self.workdir.name,
                                       self.generator_dir, self.generator_early_dir, self.generator_late_dir],
                                      stderr=subprocess.STDOUT, text=True)
        self.assertFalse(os.path.exists(n))
        self.assertIn('netplan generate already ran', out)

        # after removing the stamp it generates again, and not trip over the
        # existing enablement symlink
        os.unlink(os.path.join(outdir, 'netplan.stamp'))
        subprocess.check_output([generator, '--root-dir', self.workdir.name,
                                 self.generator_dir, self.generator_early_dir, self.generator_late_dir])
        self.assertTrue(os.path.exists(n))

    def test_systemd_generator_all_optional(self):
        self.generate('''network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      optional: true''')
        n = os.path.join(self.workdir.name, 'run', 'systemd', 'network', '10-netplan-eth0.network')
        self.assertTrue(os.path.exists(n))
        os.unlink(n)

        # should auto-enable networkd but not -wait-online
        self.assertTrue(os.path.islink(os.path.join(
            self.generator_dir, 'multi-user.target.wants', 'systemd-networkd.service')))
        self.assertFalse(os.path.islink(os.path.join(
            self.generator_dir, 'network-online.target.wants', 'systemd-networkd-wait-online.service')))
        override = os.path.join(self.generator_late_dir, 'systemd-networkd-wait-online.service.d', '10-netplan.conf')
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            self.assertEqual(f.read(), '''[Unit]
ConditionPathIsSymbolicLink=/run/systemd/generator/network-online.target.wants/systemd-networkd-wait-online.service
''')

    def test_systemd_wait_online_only_non_routable(self):
        self.generate('''network:
  version: 2
  ethernets:
    nomatchfound: # non-optional, but cannot be matched to a physical interface on the test runner
      dhcp4: true
  vlans:
    eth99.44:
      link: nomatchfound
      id: 44
      link-local: [ipv6]''')
        override = os.path.join(self.generator_late_dir, 'systemd-networkd-wait-online.service.d', '10-netplan.conf')
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            self.assertEqual(f.read(), '''[Unit]
ConditionPathIsSymbolicLink=/run/systemd/generator/network-online.target.wants/systemd-networkd-wait-online.service

[Service]
ExecStart=
ExecStart=/lib/systemd/systemd-networkd-wait-online -i eth99.44:degraded
''')

    def test_systemd_wait_online_only_routable(self):
        self.generate('''network:
  version: 2
  bridges:
    br0:
      dhcp4: true''')
        n = os.path.join(self.workdir.name, 'run', 'systemd', 'network', '10-netplan-br0.network')
        self.assertTrue(os.path.exists(n))
        os.unlink(n)

        override = os.path.join(self.generator_late_dir, 'systemd-networkd-wait-online.service.d', '10-netplan.conf')
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            self.assertEqual(f.read(), '''[Unit]
ConditionPathIsSymbolicLink=/run/systemd/generator/network-online.target.wants/systemd-networkd-wait-online.service
After=systemd-resolved.service

[Service]
ExecStart=
ExecStart=/lib/systemd/systemd-networkd-wait-online -i br0:degraded
ExecStart=/lib/systemd/systemd-networkd-wait-online --any --dns -o routable -i br0
''')

    def test_systemd_generator_noconf(self):
        self.generate('')
        # no enablement symlink here (in multi-user.target.wants)
        self.assertFalse(os.path.exists(os.path.join(
            self.generator_late_dir, 'multi-user.target.wants', 'systemd-networkd.service')))

    def test_systemd_generator_badcall(self):
        outdir = os.path.join(self.workdir.name, 'out')
        os.mkdir(outdir)

        generator = os.path.join(self.workdir.name, 'systemd', 'system-generators', 'netplan')
        os.makedirs(os.path.dirname(generator))
        os.symlink(exe_generate, generator)

        try:
            subprocess.check_output([generator, '--root-dir', self.workdir.name],
                                    stderr=subprocess.STDOUT, text=True)
            self.fail("direct systemd generator call is expected to fail, but succeeded.")  # pragma: nocover
        except subprocess.CalledProcessError as e:
            self.assertEqual(e.returncode, 1)
            self.assertIn('can not be called directly', e.output)

    def test_systemd_generator_escaping(self):
        conf = '''network:
  version: 2
  ethernets:
    lo:
      match:
        name: lo
      set-name: "a ; b\\t; c\\t; d \\n 123 ; echo "
      addresses: ["127.0.0.1/8", "::1/128"]'''
        self.generate(conf)

        n = os.path.join(self.workdir.name, 'run', 'systemd', 'network', '10-netplan-lo.network')
        self.assertTrue(os.path.exists(n))
        os.unlink(n)

        # should auto-enable networkd and -wait-online
        self.assertTrue(os.path.islink(os.path.join(
            self.generator_dir, 'multi-user.target.wants', 'systemd-networkd.service')))
        self.assertTrue(os.path.islink(os.path.join(
            self.generator_dir, 'network-online.target.wants', 'systemd-networkd-wait-online.service')))
        override = os.path.join(self.generator_late_dir, 'systemd-networkd-wait-online.service.d', '10-netplan.conf')
        self.assertTrue(os.path.isfile(override))
        with open(override, 'r') as f:
            # eth99 does not exist on the system, so will not be listed
            self.assertEqual(f.read(), '''[Unit]
ConditionPathIsSymbolicLink=/run/systemd/generator/network-online.target.wants/systemd-networkd-wait-online.service
After=systemd-resolved.service

[Service]
ExecStart=
ExecStart=/lib/systemd/systemd-networkd-wait-online -i a \\; b\\t; c\\t; d \\n 123 \\; echo :degraded
ExecStart=/lib/systemd/systemd-networkd-wait-online --any --dns -o routable -i a \\; b\\t; c\\t; d \\n 123 \\; echo \n''')

        # should be a no-op the second time while the stamp exists
        out = subprocess.check_output([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir],
                                      stderr=subprocess.STDOUT, text=True)
        self.assertFalse(os.path.exists(n))
        self.assertIn('netplan generate already ran', out)

        # after removing the stamp it generates again, and not trip over the
        # existing enablement symlink
        os.unlink(os.path.join(outdir, 'netplan.stamp'))
        subprocess.check_output([generator, '--root-dir', self.workdir.name, outdir, outdir, outdir])
        self.assertTrue(os.path.exists(n))
