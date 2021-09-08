#
# Blackbox tests of netplan's keyfile parser that verify that the generated
# YAML files look as expected. These are run during "make check" and
# don't touch the system configuration at all.
#
# Copyright (C) 2021 Canonical, Ltd.
# Author: Lukas Märdian <slyon@ubuntu.com>
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

from configparser import ConfigParser
import os
import sys
import shutil
import tempfile
import unittest
import ctypes
import ctypes.util
import contextlib
import subprocess

exe_generate = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), 'generate')

# make sure we point to libnetplan properly.
os.environ.update({'LD_LIBRARY_PATH': '.:{}'.format(os.environ.get('LD_LIBRARY_PATH'))})

# make sure we fail on criticals
os.environ['G_DEBUG'] = 'fatal-criticals'

lib = ctypes.CDLL(ctypes.util.find_library('netplan'))


# A contextmanager to catch the output on a low level so that it catches output
# from a subprocess or C library call, in addition to normal python output
@contextlib.contextmanager
def capture_stderr():
    stderr_fd = 2  # 2 = stderr
    with tempfile.NamedTemporaryFile(mode='w+b') as tmp:
        stderr_copy = os.dup(stderr_fd)
        try:
            sys.stderr.flush()
            os.dup2(tmp.fileno(), stderr_fd)
            yield tmp
        finally:
            sys.stderr.flush()
            os.dup2(stderr_copy, stderr_fd)
            os.close(stderr_copy)


class TestKeyfileBase(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.confdir = os.path.join(self.workdir.name, 'etc', 'netplan')
        self.maxDiff = None
        os.makedirs(self.confdir)

    def tearDown(self):
        shutil.rmtree(self.workdir.name)
        super().tearDown()

    def generate_from_keyfile(self, keyfile, netdef_id=None, expect_fail=False, filename=None):
        '''Call libnetplan with given keyfile string as configuration'''
        # Autodetect default 'NM-<UUID>' netdef-id
        ssid = ''
        if not netdef_id:
            found_values = 0
            uuid = 'UNKNOWN_UUID'
            for line in keyfile.splitlines():
                if line.startswith('uuid='):
                    uuid = line.split('=')[1]
                    found_values += 1
                elif line.startswith('ssid='):
                    ssid += '-' + line.split('=')[1]
                    found_values += 1
                if found_values >= 2:
                    break
            netdef_id = 'NM-' + uuid
        if not filename:
            filename = 'netplan-{}{}.nmconnection'.format(netdef_id, ssid)
        f = os.path.join(self.workdir.name, 'run/NetworkManager/system-connections/{}'.format(filename))
        os.makedirs(os.path.dirname(f))
        with open(f, 'w') as file:
            file.write(keyfile)

        with capture_stderr() as outf:
            if expect_fail:
                self.assertFalse(lib.netplan_parse_keyfile(f.encode(), None))
            else:
                self.assertTrue(lib.netplan_parse_keyfile(f.encode(), None))
                lib._write_netplan_conf(netdef_id.encode(), self.workdir.name.encode())
                lib.netplan_clear_netdefs()
                self.assert_nm_regenerate({filename: keyfile})  # check re-generated keyfile
            with open(outf.name, 'r') as f:
                output = f.read().strip()  # output from stderr (fd=2) on C/library level
                return output

    def assert_netplan(self, file_contents_map):
        for uuid in file_contents_map.keys():
            self.assertTrue(os.path.isfile(os.path.join(self.confdir, '90-NM-{}.yaml'.format(uuid))))
            with open(os.path.join(self.confdir, '90-NM-{}.yaml'.format(uuid)), 'r') as f:
                self.assertEqual(f.read(), file_contents_map[uuid])

    def normalize_keyfile(self, file_contents):
        parser = ConfigParser()
        parser.read_string(file_contents)
        sections = parser.sections()
        res = []
        # Sort sections and keys
        sections.sort()
        for s in sections:
            items = parser.items(s)
            if s == 'ipv6' and len(items) == 1 and items[0] == ('method', 'ignore'):
                continue

            line = '\n[' + s + ']'
            res.append(line)
            items.sort(key=lambda tup: tup[0])
            for k, v in items:
                # Normalize lines
                if k == 'addr-gen-mode':
                    v = v.replace('1', 'stable-privacy').replace('0', 'eui64')
                elif k == 'dns-search' and v != '':
                    # XXX: netplan is loosing information here about which search domain
                    #      belongs to the [ipv4] or [ipv6] sections
                    v = '*** REDACTED (in base.py) ***'
                # handle NM defaults
                elif k == 'dns-search' and v == '':
                    continue
                elif k == 'wake-on-lan' and v == '1':
                    continue
                elif k == 'stp' and v == 'true':
                    continue

                line = (k + '=' + v).strip(';')
                res.append(line)
        return '\n'.join(res).strip()+'\n'

    def assert_nm_regenerate(self, file_contents_map):
        argv = [exe_generate, '--root-dir', self.workdir.name]
        p = subprocess.Popen(argv, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
        (out, err) = p.communicate()
        self.assertEqual(out, '')
        con_dir = os.path.join(self.workdir.name, 'run', 'NetworkManager', 'system-connections')
        if file_contents_map:
            self.assertEqual(set(os.listdir(con_dir)),
                             set([n for n in file_contents_map]))
            for fname, contents in file_contents_map.items():
                with open(os.path.join(con_dir, fname)) as f:
                    generated_keyfile = self.normalize_keyfile(f.read())
                    normalized_contents = self.normalize_keyfile(contents)
                    self.assertEqual(generated_keyfile, normalized_contents,
                                     'Re-generated keyfile does not match')
        else:  # pragma: nocover (only needed for test debugging)
            if os.path.exists(con_dir):
                self.assertEqual(os.listdir(con_dir), [])
        return err
