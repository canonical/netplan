/*
 * Copyright (C) 2016 Canonical, Ltd.
 * Author: Martin Pitt <martin.pitt@ubuntu.com>
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

#include <glob.h>
#pragma once

extern GHashTable* wifi_frequency_24;
extern GHashTable* wifi_frequency_5;

void safe_mkdir_p_dir(const char* file_path);
void g_string_free_to_file(GString* s, const char* rootdir, const char* path, const char* suffix);
void unlink_glob(const char* rootdir, const char* _glob);
int find_yaml_glob(const char* rootdir, glob_t* out_glob);

int wifi_get_freq24(int channel);
int wifi_get_freq5(int channel);

gchar* systemd_escape(char* string);

#define OPENVSWITCH_OVS_VSCTL "/usr/bin/ovs-vsctl"
