#
# Copyright (C) 2019-2020 Canonical, Ltd.
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
import shutil
import subprocess
import tempfile
import unittest
import time

from tests.test_utils import MockCmd

rootdir = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
exe_cli = [os.path.join(rootdir, 'src', 'netplan.script')]
if shutil.which('python3-coverage'):
    exe_cli = ['python3-coverage', 'run', '--append', '--'] + exe_cli

# Make sure we can import our development netplan.
os.environ.update({'PYTHONPATH': '.'})
NETPLAN_DBUS_CMD = os.path.join(os.path.dirname(__file__), "..", "..", "netplan-dbus")


class TestNetplanDBus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "etc", "netplan"), 0o700)
        os.makedirs(os.path.join(self.tmp, "lib", "netplan"), 0o700)
        os.makedirs(os.path.join(self.tmp, "run", "netplan"), 0o700)
        # Create main test YAML in /etc/netplan/
        test_file = os.path.join(self.tmp, 'etc', 'netplan', 'main_test.yaml')
        with open(test_file, 'w') as f:
            f.write("""network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true""")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.mock_netplan_cmd = MockCmd("netplan")
        self._create_mock_system_bus()
        self._run_netplan_dbus_on_mock_bus()
        self._mock_snap_env()
        self.mock_busctl_cmd = MockCmd("busctl")

    def _mock_snap_env(self):
        os.environ["SNAP"] = "test-netplan-apply-snapd"

    def _create_mock_system_bus(self):
        env = {}
        output = subprocess.check_output(["dbus-launch"], env={})
        for s in output.decode("utf-8").split("\n"):
            if s == "":
                continue
            k, v = s.split("=", 1)
            env[k] = v
        # override system bus with the fake one
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = env["DBUS_SESSION_BUS_ADDRESS"]
        self.addCleanup(os.kill, int(env["DBUS_SESSION_BUS_PID"]), 15)

    def _run_netplan_dbus_on_mock_bus(self):
        # run netplan-dbus in a fake system bus
        os.environ["DBUS_TEST_NETPLAN_CMD"] = self.mock_netplan_cmd.path
        os.environ["DBUS_TEST_NETPLAN_ROOT"] = self.tmp
        p = subprocess.Popen(NETPLAN_DBUS_CMD,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(1)  # Give some time for our dbus daemon to be ready
        self.addCleanup(self._cleanup_netplan_dbus, p)

    def _cleanup_netplan_dbus(self, p):
        p.terminate()
        p.wait()
        # netplan-dbus does not produce output
        self.assertEqual(p.stdout.read(), b"")
        self.assertEqual(p.stderr.read(), b"")

    def _check_dbus_error(self, cmd, returncode=1):
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p.wait()
        self.assertEqual(p.returncode, returncode)
        self.assertEqual(p.stdout.read().decode("utf-8"), "")
        return p.stderr.read().decode("utf-8")

    def _new_config_object(self):
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Config",
        ]
        # Create new config object / config state
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertIn(b'o "/io/netplan/Netplan/config/', out)
        cid = out.decode('utf-8').split('/')[-1].replace('"\n', '')
        # Verify that the state folders were created in /tmp
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        self.assertTrue(os.path.isdir(tmpdir))
        self.assertTrue(os.path.isdir(os.path.join(tmpdir, 'etc', 'netplan')))
        self.assertTrue(os.path.isdir(os.path.join(tmpdir, 'run', 'netplan')))
        self.assertTrue(os.path.isdir(os.path.join(tmpdir, 'lib', 'netplan')))
        # Return random config ID
        return cid

    def test_netplan_apply_in_snap_uses_dbus(self):
        p = subprocess.Popen(
            exe_cli + ["apply"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(p.stdout.read(), b"")
        self.assertEqual(p.stderr.read(), b"")
        self.assertEquals(self.mock_netplan_cmd.calls(), [
            ["netplan", "apply"],
        ])

    def test_netplan_apply_in_snap_calls_busctl(self):
        newenv = os.environ.copy()
        busctlDir = os.path.dirname(self.mock_busctl_cmd.path)
        newenv["PATH"] = busctlDir+":"+os.environ["PATH"]
        p = subprocess.Popen(
            exe_cli + ["apply"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=newenv)
        self.assertEqual(p.stdout.read(), b"")
        self.assertEqual(p.stderr.read(), b"")
        self.assertEquals(self.mock_busctl_cmd.calls(), [
            ["busctl", "call", "--quiet", "--system",
             "io.netplan.Netplan",  # the service
             "/io/netplan/Netplan",  # the object
             "io.netplan.Netplan",  # the interface
             "Apply",  # the method
             ],
        ])

    def test_netplan_generate_in_snap_calls_busctl(self):
        newenv = os.environ.copy()
        busctlDir = os.path.dirname(self.mock_busctl_cmd.path)
        newenv["PATH"] = busctlDir+":"+os.environ["PATH"]
        p = subprocess.Popen(
            exe_cli + ["generate"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=newenv)
        self.assertEqual(p.stdout.read(), b"")
        self.assertEqual(p.stderr.read(), b"")
        self.assertEquals(self.mock_busctl_cmd.calls(), [
            ["busctl", "call", "--quiet", "--system",
             "io.netplan.Netplan",  # the service
             "/io/netplan/Netplan",  # the object
             "io.netplan.Netplan",  # the interface
             "Generate",  # the method
             ],
        ])

    def test_netplan_generate_in_snap_calls_busctl_ret130(self):
        newenv = os.environ.copy()
        busctlDir = os.path.dirname(self.mock_busctl_cmd.path)
        newenv["PATH"] = busctlDir+":"+os.environ["PATH"]
        self.mock_busctl_cmd.set_returncode(130)
        p = subprocess.Popen(
            exe_cli + ["generate"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=newenv)
        self.assertIn(b"PermissionError: failed to communicate with dbus service", p.stderr.read())

    def test_netplan_generate_in_snap_calls_busctl_ret1(self):
        newenv = os.environ.copy()
        busctlDir = os.path.dirname(self.mock_busctl_cmd.path)
        newenv["PATH"] = busctlDir+":"+os.environ["PATH"]
        self.mock_busctl_cmd.set_returncode(1)
        p = subprocess.Popen(
            exe_cli + ["generate"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=newenv)
        self.assertIn(b"RuntimeError: failed to communicate with dbus service", p.stderr.read())

    def test_netplan_dbus_noroot(self):
        # Process should fail instantly, if not: kill it after 5 sec
        r = subprocess.run(NETPLAN_DBUS_CMD, timeout=5, capture_output=True)
        self.assertEquals(r.returncode, 1)
        self.assertIn(b'Failed to acquire service name', r.stderr)

    def test_netplan_dbus_happy(self):
        BUSCTL_NETPLAN_APPLY = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Apply",
        ]
        output = subprocess.check_output(BUSCTL_NETPLAN_APPLY)
        self.assertEqual(output.decode("utf-8"), "b true\n")
        # one call to netplan apply in total
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "apply"],
        ])

        # and again!
        output = subprocess.check_output(BUSCTL_NETPLAN_APPLY)
        self.assertEqual(output.decode("utf-8"), "b true\n")
        # and another call to netplan apply
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "apply"],
                ["netplan", "apply"],
        ])

    def test_netplan_dbus_generate(self):
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Generate",
        ]
        output = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(output.decode("utf-8"), "b true\n")
        # one call to netplan apply in total
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "generate"],
        ])

    def test_netplan_dbus_info(self):
        BUSCTL_NETPLAN_INFO = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Info",
        ]
        output = subprocess.check_output(BUSCTL_NETPLAN_INFO)
        self.assertIn("Features", output.decode("utf-8"))

    def test_netplan_dbus_config(self):
        # Create test YAML
        test_file_lib = os.path.join(self.tmp, 'lib', 'netplan', 'lib_test.yaml')
        with open(test_file_lib, 'w') as f:
            f.write('TESTING-lib')
        test_file_run = os.path.join(self.tmp, 'run', 'netplan', 'run_test.yaml')
        with open(test_file_run, 'w') as f:
            f.write('TESTING-run')
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'etc', 'netplan', 'main_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'lib', 'netplan', 'lib_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'run', 'netplan', 'run_test.yaml')))

        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        self.addClassCleanup(shutil.rmtree, tmpdir)

        # Verify the object path has been created, by calling .Config.Get() on that object
        # it would throw an error if it does not exist
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Get",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD, universal_newlines=True)
        self.assertIn(r's ""', out)  # No output as 'netplan get' is actually mocked
        self.assertEquals(self.mock_netplan_cmd.calls(), [[
            "netplan", "get", "all", "--root-dir={}".format(tmpdir)
        ]])

        # Verify all *.yaml files have been copied
        self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'etc', 'netplan', 'main_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'lib', 'netplan', 'lib_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'run', 'netplan', 'run_test.yaml')))

    def test_netplan_dbus_no_such_command(self):
        err = self._check_dbus_error([
            "busctl", "call",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "NoSuchCommand"
        ])
        self.assertIn("Unknown method", err)

    def test_netplan_dbus_config_set(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        self.addCleanup(shutil.rmtree, tmpdir)

        # Verify .Config.Set() on the config object
        # No actual YAML file will be created, as the netplan command is mocked
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth42.dhcp6=true", "",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)
        print(self.mock_netplan_cmd.calls(), flush=True)
        self.assertEquals(self.mock_netplan_cmd.calls(), [[
            "netplan", "set", "ethernets.eth42.dhcp6=true",
            "--root-dir={}".format(tmpdir)
        ]])

    def test_netplan_dbus_config_set_multi_line(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        self.addCleanup(shutil.rmtree, tmpdir)
        self.mock_netplan_cmd.expect_stdin()

        # Verify .Config.Set() on the config object
        # No actual YAML file will be created, as the netplan command is mocked
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets:\n eth42:\n  dhcp6: true", "",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)
        self.assertEquals(self.mock_netplan_cmd.calls(), [[
            "netplan", "set", "-",
            "--root-dir={}".format(tmpdir)
        ]])
        self.assertEquals(self.mock_netplan_cmd.stdin(), """ethernets:
 eth42:
  dhcp6: true""")

    def test_netplan_dbus_config_set_multi_line_error(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        self.addCleanup(shutil.rmtree, tmpdir)
        self.mock_netplan_cmd.add_snippet("echo stdout; >&2 echo stderr; exit 1")
        self.mock_netplan_cmd.expect_stdin()
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets:\n eth42:\n  dhcp6: true", "",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD)
        self.assertIn("netplan set failed: Child process exited with code 1", err)
        self.assertIn("stdout: 'stdout", err)
        self.assertIn("stderr: 'stderr", err)

    def test_netplan_dbus_config_set_multi_line_no_stdin_error(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        self.addCleanup(shutil.rmtree, tmpdir)
        self.mock_netplan_cmd.add_snippet("exec 0<&-")
        self.mock_netplan_cmd.expect_stdin()

        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets:\n eth42:\n  dhcp6: true", "",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD)
        self.assertIn("netplan set failed: Child process exited with code 1", err)
        # XXX: not quite the failure we except
        self.assertIn("stderr: 'cat: -: Bad file descriptor", err)

    def test_netplan_dbus_config_get(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        self.addCleanup(shutil.rmtree, tmpdir)

        # Verify .Config.Get() on the config object
        self.mock_netplan_cmd.set_output("network:\n  eth42:\n    dhcp6: true")
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Get",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD, universal_newlines=True)
        self.assertIn(r's "network:\n  eth42:\n    dhcp6: true\n"', out)
        self.assertEquals(self.mock_netplan_cmd.calls(), [[
            "netplan", "get", "all", "--root-dir={}".format(tmpdir)
        ]])

    def test_netplan_dbus_config_cancel(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)

        # Verify .Config.Cancel() teardown of the config object and state dirs
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Cancel",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)

        time.sleep(1)  # Give some time for 'Cancel' to clean up
        self.assertFalse(os.path.isdir(tmpdir))

        # Verify the object is gone from the bus
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD)
        self.assertIn('Unknown object \'/io/netplan/Netplan/config/{}\''.format(cid), err)

    def test_netplan_dbus_config_apply(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        with open(os.path.join(tmpdir, 'etc', 'netplan', 'apply_test.yaml'), 'w') as f:
            f.write('TESTING-apply')
        with open(os.path.join(tmpdir, 'lib', 'netplan', 'apply_test.yaml'), 'w') as f:
            f.write('TESTING-apply')
        with open(os.path.join(tmpdir, 'run', 'netplan', 'apply_test.yaml'), 'w') as f:
            f.write('TESTING-apply')

        # Verify .Config.Apply() teardown of the config object and state dirs
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Apply",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)
        self.assertEquals(self.mock_netplan_cmd.calls(), [["netplan", "apply"]])
        time.sleep(1)  # Give some time for 'Apply' to clean up
        self.assertFalse(os.path.isdir(tmpdir))

        # Verify the new YAML files were copied over
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'etc', 'netplan', 'apply_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'run', 'netplan', 'apply_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'lib', 'netplan', 'apply_test.yaml')))

        # Verify the object is gone from the bus
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD)
        self.assertIn('Unknown object \'/io/netplan/Netplan/config/{}\''.format(cid), err)

    def test_netplan_dbus_config_try_cancel(self):
        # self-terminate after 30 dsec = 3 sec, if not cancelled before
        self.mock_netplan_cmd.set_timeout(30)
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        backup = '/tmp/netplan-config-BACKUP'
        with open(os.path.join(tmpdir, 'etc', 'netplan', 'try_test.yaml'), 'w') as f:
            f.write('TESTING-try')
        with open(os.path.join(tmpdir, 'lib', 'netplan', 'try_test.yaml'), 'w') as f:
            f.write('TESTING-try')
        with open(os.path.join(tmpdir, 'run', 'netplan', 'try_test.yaml'), 'w') as f:
            f.write('TESTING-try')

        # Verify .Config.Try() setup of the config object and state dirs
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Try", "u", "3",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)

        # Verify the temp state still exists
        self.assertTrue(os.path.isdir(tmpdir))
        self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'etc', 'netplan', 'try_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'run', 'netplan', 'try_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(tmpdir, 'lib', 'netplan', 'try_test.yaml')))

        # Verify the backup has been created
        self.assertTrue(os.path.isdir(backup))
        self.assertTrue(os.path.isfile(os.path.join(backup, 'etc', 'netplan', 'main_test.yaml')))

        # Verify the new YAML files were copied over
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'etc', 'netplan', 'try_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'run', 'netplan', 'try_test.yaml')))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'lib', 'netplan', 'try_test.yaml')))

        BUSCTL_NETPLAN_CMD2 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Cancel",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD2)
        self.assertEqual(b'b true\n', out)
        time.sleep(1)  # Give some time for 'Cancel' to clean up

        # Verify the backup andconfig state dir are gone
        self.assertFalse(os.path.isdir(backup))
        self.assertFalse(os.path.isdir(tmpdir))

        # Verify the backup has been restored
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'etc', 'netplan', 'main_test.yaml')))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, 'etc', 'netplan', 'try_test.yaml')))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, 'run', 'netplan', 'try_test.yaml')))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, 'lib', 'netplan', 'try_test.yaml')))

        # Verify the config object is gone from the bus
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD2)
        self.assertIn('Unknown object \'/io/netplan/Netplan/config/{}\''.format(cid), err)

        # Verify 'netplan try' has been called
        self.assertEquals(self.mock_netplan_cmd.calls(), [["netplan", "try", "--timeout=3"]])

    def test_netplan_dbus_config_try_cb(self):
        self.mock_netplan_cmd.set_timeout(1)  # actually self-terminate after 0.1 sec
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)
        backup = '/tmp/netplan-config-BACKUP'
        with open(os.path.join(tmpdir, 'etc', 'netplan', 'try_test.yaml'), 'w') as f:
            f.write('TESTING-try')
        with open(os.path.join(tmpdir, 'lib', 'netplan', 'try_test.yaml'), 'w') as f:
            f.write('TESTING-try')
        with open(os.path.join(tmpdir, 'run', 'netplan', 'try_test.yaml'), 'w') as f:
            f.write('TESTING-try')

        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Try", "u", "1",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)
        time.sleep(1.5)  # Give some time for the timeout to happen

        # Verify the backup andconfig state dir are gone
        self.assertFalse(os.path.isdir(backup))
        self.assertFalse(os.path.isdir(tmpdir))

        # Verify the backup has been restored
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, 'etc', 'netplan', 'main_test.yaml')))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, 'etc', 'netplan', 'try_test.yaml')))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, 'run', 'netplan', 'try_test.yaml')))
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, 'lib', 'netplan', 'try_test.yaml')))

        # Verify the config object is gone from the bus
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD)
        self.assertIn('Unknown object \'/io/netplan/Netplan/config/{}\''.format(cid), err)

        # Verify 'netplan try' has been called
        self.assertEquals(self.mock_netplan_cmd.calls(), [["netplan", "try", "--timeout=1"]])

    def test_netplan_dbus_config_try_apply(self):
        self.mock_netplan_cmd.set_timeout(30)  # 30 dsec = 3 sec
        cid = self._new_config_object()
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Try", "u", "3",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)

        BUSCTL_NETPLAN_CMD2 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Apply",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD2)
        self.assertIn('Another \'netplan try\' process is already running', err)

    def test_netplan_dbus_config_try_config_try(self):
        self.mock_netplan_cmd.set_timeout(50)  # 50 dsec = 5 sec
        cid = self._new_config_object()
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Try", "u", "3",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)

        cid2 = self._new_config_object()
        BUSCTL_NETPLAN_CMD2 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid2),
            "io.netplan.Netplan.Config",
            "Try", "u", "5",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD2)
        self.assertIn('Another Try() is currently in progress: PID ', err)

    def test_netplan_dbus_config_set_invalidate(self):
        self.mock_netplan_cmd.set_timeout(30)  # 30 dsec = 3 sec
        cid = self._new_config_object()
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=true", "70-snapd",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)
        # Calling Set() on the same config object still works
        BUSCTL_NETPLAN_CMD1 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=yes", "70-snapd",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD1)
        self.assertEqual(b'b true\n', out)

        cid2 = self._new_config_object()
        # Calling Set() on another config object fails
        BUSCTL_NETPLAN_CMD2 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid2),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=false", "70-snapd",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD2)
        self.assertIn('This config was invalidated by another config object', err)
        # Calling Try() on another config object fails
        BUSCTL_NETPLAN_CMD3 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid2),
            "io.netplan.Netplan.Config",
            "Try", "u", "3",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD3)
        self.assertIn('This config was invalidated by another config object', err)
        # Calling Apply() on another config object fails
        BUSCTL_NETPLAN_CMD4 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid2),
            "io.netplan.Netplan.Config",
            "Apply",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD4)
        self.assertIn('This config was invalidated by another config object', err)

        # Calling Apply() on the same config object still works
        BUSCTL_NETPLAN_CMD5 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Apply",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD5)
        self.assertEqual(b'b true\n', out)

        # Verify that Set()/Apply() was only called by one config object
        self.assertEquals(self.mock_netplan_cmd.calls(), [
            ["netplan", "set", "ethernets.eth0.dhcp4=true", "--origin-hint=70-snapd",
             "--root-dir=/tmp/netplan-config-{}".format(cid)],
            ["netplan", "set", "ethernets.eth0.dhcp4=yes", "--origin-hint=70-snapd",
             "--root-dir=/tmp/netplan-config-{}".format(cid)],
            ["netplan", "apply"]
        ])

        # Now it works again
        cid3 = self._new_config_object()
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid3),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=false", "70-snapd",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid3),
            "io.netplan.Netplan.Config",
            "Apply",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)

    def test_netplan_dbus_config_set_uninvalidate(self):
        self.mock_netplan_cmd.set_timeout(2)
        cid = self._new_config_object()
        cid2 = self._new_config_object()
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=true", "70-snapd",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)

        # Calling Set() on another config object fails
        BUSCTL_NETPLAN_CMD2 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid2),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=false", "70-snapd",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD2)
        self.assertIn('This config was invalidated by another config object', err)

        # Calling Cancel() clears the dirty state
        BUSCTL_NETPLAN_CMD3 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Cancel",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD3)
        self.assertEqual(b'b true\n', out)

        # Calling Set() on the other config object works now
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD2)
        self.assertEqual(b'b true\n', out)

        # Verify the call stack
        self.assertEquals(self.mock_netplan_cmd.calls(), [
            ["netplan", "set", "ethernets.eth0.dhcp4=true", "--origin-hint=70-snapd",
             "--root-dir=/tmp/netplan-config-{}".format(cid)],
            ["netplan", "set", "ethernets.eth0.dhcp4=false", "--origin-hint=70-snapd",
             "--root-dir=/tmp/netplan-config-{}".format(cid2)]
        ])

    def test_netplan_dbus_config_set_uninvalidate_timeout(self):
        self.mock_netplan_cmd.set_timeout(1)  # actually self-terminate process after 0.1 sec
        cid = self._new_config_object()
        cid2 = self._new_config_object()
        BUSCTL_NETPLAN_CMD = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=true", "70-snapd",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)

        BUSCTL_NETPLAN_CMD1 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid),
            "io.netplan.Netplan.Config",
            "Try", "u", "1",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD1)
        self.assertEqual(b'b true\n', out)

        # Calling Set() on another config object fails
        BUSCTL_NETPLAN_CMD2 = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan/config/{}".format(cid2),
            "io.netplan.Netplan.Config",
            "Set", "ss", "ethernets.eth0.dhcp4=false", "70-snapd",
        ]
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD2)
        self.assertIn('This config was invalidated by another config object', err)

        time.sleep(1.5)  # Wait for the child process to self-terminate

        # Calling Set() on the other config object works now
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD2)
        self.assertEqual(b'b true\n', out)

        # Verify the call stack
        self.assertEquals(self.mock_netplan_cmd.calls(), [
            ["netplan", "set", "ethernets.eth0.dhcp4=true", "--origin-hint=70-snapd",
             "--root-dir=/tmp/netplan-config-{}".format(cid)],
            ["netplan", "try", "--timeout=1"],
            ["netplan", "set", "ethernets.eth0.dhcp4=false", "--origin-hint=70-snapd",
             "--root-dir=/tmp/netplan-config-{}".format(cid2)]
        ])
