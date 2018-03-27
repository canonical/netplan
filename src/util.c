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

#include <stdlib.h>
#include <unistd.h>
#include <glob.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "util.h"

/**
 * Create the parent directories of given file path. Exit program on failure.
 */
void
safe_mkdir_p_dir(const char* file_path)
{
    g_autofree char* dir = g_path_get_dirname(file_path);

    if (g_mkdir_with_parents(dir, 0755) < 0) {
        g_fprintf(stderr, "ERROR: cannot create directory %s: %m\n", dir);
        exit(1);
    }
}

/**
 * Write a GString to a file and free it. Create necessary parent directories
 * and exit with error message on error.
 * @s: #GString whose contents to write. Will be fully freed afterwards.
 * @rootdir: optional rootdir (@NULL means "/")
 * @path: path of file to write (@rootdir will be prepended)
 * @suffix: optional suffix to append to path
 */
void g_string_free_to_file(GString* s, const char* rootdir, const char* path, const char* suffix)
{
    g_autofree char* full_path = NULL;
    g_autofree char* contents = g_string_free(s, FALSE);
    GError* error = NULL;

    full_path = g_strjoin(NULL, rootdir ?: "", G_DIR_SEPARATOR_S, path, suffix, NULL);
    safe_mkdir_p_dir(full_path);
    if (!g_file_set_contents(full_path, contents, -1, &error)) {
        /* the mkdir() just succeeded, there is no sensible
         * method to test this without root privileges, bind mounts, and
         * simulating ENOSPC */
        // LCOV_EXCL_START
        g_fprintf(stderr, "ERROR: cannot create file %s: %s\n", path, error->message);
        exit(1);
        // LCOV_EXCL_END
    }
}

/**
 * Remove all files matching given glob.
 */
void
unlink_glob(const char* rootdir, const char* _glob)
{
    glob_t gl;
    int rc;
    g_autofree char* rglob = g_strjoin(NULL, rootdir ?: "", G_DIR_SEPARATOR_S, _glob, NULL);

    rc = glob(rglob, 0, NULL, &gl);
    if (rc != 0 && rc != GLOB_NOMATCH) {
        // LCOV_EXCL_START
        g_fprintf(stderr, "failed to glob for %s: %m\n", rglob);
        return;
        // LCOV_EXCL_STOP
    }

    for (size_t i = 0; i < gl.gl_pathc; ++i)
        unlink(gl.gl_pathv[i]);
}
