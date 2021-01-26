#!/usr/bin/python3
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

from netplan.cli.commands.apply import NetplanApply
from netplan.cli.commands.generate import NetplanGenerate
from netplan.cli.commands.ip import NetplanIp
from netplan.cli.commands.migrate import NetplanMigrate
from netplan.cli.commands.try_command import NetplanTry
from netplan.cli.commands.info import NetplanInfo
from netplan.cli.commands.set import NetplanSet
from netplan.cli.commands.get import NetplanGet

__all__ = [
    'NetplanApply',
    'NetplanGenerate',
    'NetplanIp',
    'NetplanMigrate',
    'NetplanTry',
    'NetplanInfo',
    'NetplanSet',
    'NetplanGet',
]
