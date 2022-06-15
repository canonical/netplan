/*
 * Copyright (C) 2021 Canonical, Ltd.
 * Author: Simon Chopin <simon.chopin@canonical.com>
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

#include "netplan.h"
#include "types.h"

NETPLAN_INTERNAL const char*
netplan_backend_name(NetplanBackend val);

const char*
netplan_def_type_name(NetplanDefType val);

const char*
netplan_auth_key_management_type_name(NetplanAuthKeyManagementType val);

const char*
netplan_auth_eap_method_name(NetplanAuthEAPMethod val);

const char*
netplan_tunnel_mode_name(NetplanTunnelMode val);

const char*
netplan_addr_gen_mode_name(NetplanAddrGenMode val);

const char*
netplan_wifi_mode_name(NetplanWifiMode val);

const char*
netplan_infiniband_mode_name(NetplanInfinibandMode val);

NetplanDefType
netplan_def_type_from_name(const char* val);
