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

rootdir = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
exe_cli = [os.path.join(rootdir, 'src', 'netplan.script')]
if shutil.which('python3-coverage'):
    exe_cli = ['python3-coverage', 'run', '--append', '--'] + exe_cli

# Make sure we can import our development netplan.
os.environ.update({'PYTHONPATH': '.'})


class MockCmd:
    """MockCmd will mock a given command name and capture all calls to it"""

    def __init__(self, name):
        self._tmp = tempfile.TemporaryDirectory()
        self.name = name
        self.path = os.path.join(self._tmp.name, name)
        self.call_log = os.path.join(self._tmp.name, "call.log")
        with open(self.path, "w") as fp:
            fp.write("""#!/bin/bash
printf "%%s" "$(basename "$0")" >> %(log)s
printf '\\0' >> %(log)s

for arg in "$@"; do
     printf "%%s" "$arg" >> %(log)s
     printf '\\0'  >> %(log)s
done

printf '\\0' >> %(log)s
""" % {'log': self.call_log})
        os.chmod(self.path, 0o755)

    def calls(self):
        """
        calls() returns the calls to the given mock command in the form of
        [ ["cmd", "call1-arg1"], ["cmd", "call2-arg1"], ... ]
        """
        with open(self.call_log) as fp:
            b = fp.read()
        calls = []
        for raw_call in b.rstrip("\0\0").split("\0\0"):
            call = raw_call.rstrip("\0")
            calls.append(call.split("\0"))
        return calls

    def set_output(self, output):
        with open(self.path, "a") as fp:
            fp.write("cat << EOF\n%s\nEOF" % output)


class TestNetplanDBus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
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
        p = subprocess.Popen(
            os.path.join(os.path.dirname(__file__), "..", "..", "netplan-dbus"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
        self.assertTrue(os.path.isdir(tmpdir + '/etc/netplan'))
        self.assertTrue(os.path.isdir(tmpdir + '/run/netplan'))
        self.assertTrue(os.path.isdir(tmpdir + '/lib/netplan'))
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

    def test_netplan_dbus_get(self):
        self.mock_netplan_cmd.set_output("""network:
  ens3:
    addresses:
    - 1.2.3.4/24
    - 5.6.7.8/24
    dhcp4: true""")
        BUSCTL_NETPLAN_GET = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Get"
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_GET, universal_newlines=True)
        self.assertIn(r's "network:\n  ens3:\n    addresses:\n    - 1.2.3.4/24\n    - 5.6.7.8/24\n    dhcp4: true\n"', out)
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "get", "all"],
        ])

    def test_netplan_dbus_set(self):
        BUSCTL_NETPLAN_SET = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Set", "ss",
            "ethernets.eth0={addresses: [5.6.7.8/24], dhcp4: false}",
            ""
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_SET, universal_newlines=True)
        self.assertEqual(out, "b true\n")
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "set", "ethernets.eth0={addresses: [5.6.7.8/24], dhcp4: false}"],
        ])

    def test_netplan_dbus_set_origin(self):
        BUSCTL_NETPLAN_SET = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Set", "ss",
            "ethernets.eth0={addresses: [5.6.7.8/24], dhcp4: false}",
            "99_snapd"
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_SET, universal_newlines=True)
        self.assertEqual(out, "b true\n")
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "set", "ethernets.eth0={addresses: [5.6.7.8/24], dhcp4: false}",
                 "--origin-hint=99_snapd"],
        ])

    def test_netplan_dbus_try(self):
        BUSCTL_NETPLAN_TRY = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Try", "u", "5",
        ]
        BUSCTL_NETPLAN_CANCEL = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Cancel",
        ]
        BUSCTL_NETPLAN_APPLY = [
            "busctl", "call", "--system",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Apply",
        ]

        output = subprocess.check_output(BUSCTL_NETPLAN_CANCEL)
        self.assertEqual("b false\n", output.decode("utf-8"))

        output = subprocess.check_output(BUSCTL_NETPLAN_TRY)
        self.assertEqual("b true\n", output.decode("utf-8"))

        output = subprocess.check_output(BUSCTL_NETPLAN_APPLY)
        self.assertEqual("b true\n", output.decode("utf-8"))

        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "try", "--timeout=5"],
                ["netplan", "apply"],
        ])

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
            "Set", "ss", "ethernets.eth42.dhcp6=true", "testfile",
        ]
        out = subprocess.check_output(BUSCTL_NETPLAN_CMD)
        self.assertEqual(b'b true\n', out)
        self.assertEquals(self.mock_netplan_cmd.calls(), [[
            "netplan", "set", "ethernets.eth42.dhcp6=true",
            "--origin-hint=testfile", "--root-dir={}".format(tmpdir)
        ]])

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
        self.assertFalse(os.path.isdir(tmpdir))

        # Verify the object is gone from the bus
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD)
        self.assertIn('Unknown object \'/io/netplan/Netplan/config/{}\''.format(cid), err)

    def test_netplan_dbus_config_apply(self):
        cid = self._new_config_object()
        tmpdir = '/tmp/netplan-config-{}'.format(cid)

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
        self.assertFalse(os.path.isdir(tmpdir))

        # Verify the object is gone from the bus
        err = self._check_dbus_error(BUSCTL_NETPLAN_CMD)
        self.assertIn('Unknown object \'/io/netplan/Netplan/config/{}\''.format(cid), err)

    # TODO: test_netplan_dbus_config_try + extra cases where files are moved around the config/GLOBAL states
