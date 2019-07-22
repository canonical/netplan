#
# Copyright (C) 2019 Canonical, Ltd.
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


class TestNetplanDBus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.mock_netplan_cmd = MockCmd("netplan")
        self._create_mock_system_bus()
        self._run_netplan_dbus_on_mock_bus()

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

    def test_netplan_dbus_happy(self):
        BUSCTL_NETPLAN_APPLY = [
            "busctl", "call",
            "io.netplan.Netplan",
            "/io/netplan/Netplan",
            "io.netplan.Netplan",
            "Apply",
        ]
        output = subprocess.check_output(
            BUSCTL_NETPLAN_APPLY, encoding="utf-8")
        self.assertEqual(output, "b true\n")
        # one call to netplan apply in total
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "apply"],
            ])

        # and again!
        output = subprocess.check_output(
            BUSCTL_NETPLAN_APPLY, encoding="utf-8")
        # and another call to netplan apply
        self.assertEquals(self.mock_netplan_cmd.calls(), [
                ["netplan", "apply"],
                ["netplan", "apply"],
            ])

    def test_netplan_dbus_no_such_command(self):
        cp = subprocess.run(
            ["busctl", "call",
             "io.netplan.Netplan",
             "/io/netplan/Netplan",
             "io.netplan.Netplan",
             "NoSuchCommand"],
            capture_output=True, encoding="utf-8")
        self.assertEqual(cp.returncode, 1)
        self.assertEqual(cp.stdout, "")
        self.assertEqual(cp.stderr, "Unknown method 'NoSuchCommand' or interface 'io.netplan.Netplan'.\n")
