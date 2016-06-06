#include <glib.h>
#include <glib/gstdio.h>

#include "parse.h"
#include "networkd.h"

/* really crappy demo main() function to exercise the parser and networkd writer */
int main(int argc, char **argv)
{
    GError *err = NULL;

    if (!parse_yaml(argv[1], &err)) {
        g_fprintf(stderr, "%s\n", err->message);
        g_error_free(err);
        return 1;
    }

    for (net_definition *n = netdefs; n; n = n->prev)
        write_networkd_conf(n, argc >= 3 ? argv[2] : NULL);
    return 0;
}
