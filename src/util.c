#include <stdlib.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "util.h"

/**
 * Generate IDs, to be used as file names if net_definition does not set an ID.
 */
const char*
generate_id(void)
{
    static unsigned id = 0;
    static char buf[100];

    g_assert(g_snprintf(buf, sizeof(buf), "id%u", id++) < sizeof(buf) - 1);
    return buf;
}

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
