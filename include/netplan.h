/*
 * Copyright (C) 2021 Canonical, Ltd.
 * Author: Lukas Märdian <slyon@ubuntu.com>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; version 3.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#pragma once
#define NETPLAN_PUBLIC __attribute__ ((visibility("default")))
#define NETPLAN_INTERNAL __attribute__ ((visibility("default")))

/**
 * Represent a configuration stanza
 */
typedef struct net_definition NetplanNetDefinition;

NETPLAN_PUBLIC void
write_netplan_conf(const NetplanNetDefinition* def, const char* rootdir);
