#include <glib.h>
#include <glib/gstdio.h>

#include "parse.h"
#include "networkd.h"

static void nd_iterator(gpointer key, gpointer value, gpointer user_data)
{
    write_networkd_conf((net_definition*) value, (const char*) user_data);
}

/* really crappy demo main() function to exercise the parser and networkd writer */
int main(int argc, char **argv)
{
    GError *err = NULL;

    if (!parse_yaml(argv[1], &err)) {
        g_fprintf(stderr, "%s\n", err->message);
        g_error_free(err);
        return 1;
    }

    g_hash_table_foreach(netdefs, nd_iterator, argc >= 3 ? argv[2] : NULL);
    return 0;
}
