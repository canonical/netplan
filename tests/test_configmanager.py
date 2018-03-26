#!/usr/bin/python3
# Validate ConfigManager methods
#
# Copyright (C) 2018 Canonical, Ltd.
# Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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
import tempfile
import unittest

from netplan.configmanager import ConfigManager


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.configmanager = ConfigManager(prefix=self.workdir.name)
        os.makedirs(os.path.join(self.workdir.name, "etc/netplan"))
        os.makedirs(os.path.join(self.workdir.name, "run/systemd/network"))
        os.makedirs(os.path.join(self.workdir.name, "run/NetworkManager/system-connections"))
        with open(os.path.join(self.workdir.name, "newfile.yaml"), 'w') as fd:
            print("new yaml", file=fd)
        with open(os.path.join(self.workdir.name, "etc/netplan/test.yaml"), 'w') as fd:
            print("pretend yaml", file=fd)
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'w') as fd:
            print("pretend .network", file=fd)
        with open(os.path.join(self.workdir.name, "run/NetworkManager/system-connections/pretend"), 'w') as fd:
            print("pretend NM config", file=fd)

    def test_add(self):
        self.configmanager.add({os.path.join(self.workdir.name, "newfile.yaml"):
                                os.path.join(self.workdir.name, "etc/netplan/newfile.yaml")})
        self.assertIn(os.path.join(self.workdir.name, "newfile.yaml"),
                      self.configmanager.extra_files)
        self.assertTrue(os.path.exists(os.path.join(self.workdir.name, "etc/netplan/newfile.yaml")))

    def test_backup_without_config_file(self):
        backup_dir = self.configmanager.tempdir
        self.configmanager.backup(with_config_file=False)
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/NetworkManager/system-connections/pretend")))
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/systemd/network/01-pretend.network")))
        self.assertFalse(os.path.exists(os.path.join(backup_dir, "etc/netplan/test.yaml")))

    def test_backup_with_config_file(self):
        backup_dir = self.configmanager.tempdir
        self.configmanager.backup(with_config_file=True)
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/NetworkManager/system-connections/pretend")))
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "run/systemd/network/01-pretend.network")))
        self.assertTrue(os.path.exists(os.path.join(backup_dir, "etc/netplan/test.yaml")))

    def test_revert(self):
        self.configmanager.backup(with_config_file=False)
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'a+') as fd:
            print("CHANGED", file=fd)
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'r') as fd:
            lines = fd.readlines()
            self.assertIn("CHANGED\n", lines)
        self.configmanager.revert()
        with open(os.path.join(self.workdir.name, "run/systemd/network/01-pretend.network"), 'r') as fd:
            lines = fd.readlines()
            self.assertNotIn("CHANGED\n", lines)

    def test_cleanup(self):
        backup_dir = self.configmanager.tempdir
        self.assertTrue(os.path.exists(backup_dir))
        self.configmanager.cleanup()
        self.assertFalse(os.path.exists(backup_dir))
