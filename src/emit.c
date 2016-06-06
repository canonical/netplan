#include <glib.h>
#include <glib/gstdio.h>

#include "parse.h"

/* really crappy demo main() function to exercise the parser */
int main(int argc, char **argv)
{
    GError *err = NULL;

    if (!parse_yaml(argv[1], &err)) {
        g_fprintf(stderr, "%s\n", err->message);
        g_error_free(err);
        return 1;
    }

    /* debugging: show the current netdev device to confirm written fields */
    g_printf("id: %s, set-name: %s, WOL: %i match.driver: %s, prev: %p\n", netdefs->id, netdefs->set_name, netdefs->wake_on_lan, netdefs->match.driver, netdefs->prev);
    return 0;
}
