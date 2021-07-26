/*
 * Copyright (C) 2019 Canonical, Ltd.
 * Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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

#include "parse.h"
#include <glib.h>


gboolean is_ip4_address(const char* address);
gboolean is_ip6_address(const char* address);
gboolean is_hostname(const char* hostname);
gboolean is_wireguard_key(const char* hostname);
gboolean validate_ovs_target(gboolean host_first, gchar* s);

gboolean
validate_netdef_grammar(NetplanNetDefinition* nd, yaml_node_t* node, GError** error);

gboolean
validate_backend_rules(NetplanNetDefinition* nd, GError** error);

gboolean
validate_default_route_consistency(GHashTable* netdefs, GError** error);
