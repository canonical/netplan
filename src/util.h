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

#pragma once

GHashTable* wifi_frequency_24;
GHashTable* wifi_frequency_5;

void safe_mkdir_p_dir(const char* file_path);
void g_string_free_to_file(GString* s, const char* rootdir, const char* path, const char* suffix);
void unlink_glob(const char* rootdir, const char* _glob);

int wifi_get_freq24(int channel);
int wifi_get_freq5(int channel);
