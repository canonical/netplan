#include <stdlib.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "nm.h"
#include "parse.h"
#include "util.h"

GString* udev_rules;

/**
 * Append NM device specifier of @def to @s.
 */
static void
g_string_append_netdef_match(GString* s, const net_definition* def)
{
    if (def->match.driver) {
        g_fprintf(stderr, "ERROR: NetworkManager definitions do not support matching by driver\n");
        exit(1);
    }
    if (def->match.mac) {
        if (def->match.original_name) {
            g_fprintf(stderr, "ERROR: NetworkManager definitions can only use one match: property\n");
            exit(1);
        }
        g_string_append_printf(s, "mac:%s", def->match.mac);
    } else if (def->match.original_name || def->set_name || def->type >= ND_VIRTUAL) {
        char *n;

        if (def->match.mac) {
            g_fprintf(stderr, "ERROR: NetworkManager definitions can only use one match: property\n");
            exit(1);
        }
        /* we always have the renamed name here */
        if (def->type >= ND_VIRTUAL)
            n = def->id;
        else if (def->set_name)
            n = def->set_name;
        else if (def->match.original_name)
            n = def->match.original_name;
        g_string_append_printf(s, "interface-name:%s", n);
    } else {
        /* no matches → match all devices of that type */
        switch (def->type) {
            case ND_ETHERNET:
                g_string_append(s, "type:ethernet");
                break;
            case ND_WIFI:
                g_string_append(s, "type:wifi");
                break;
            default:
                g_assert_not_reached();
        }
    }
}

/**
 * Generate NetworkManager configuration in @rootdir/run/NetworkManager/ from
 * the parsed #netdefs.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
void
write_nm_conf(net_definition* def, const char* rootdir)
{
    g_autofree char* conf_path = NULL;

    if (def->backend != BACKEND_NM) {
        g_debug("NetworkManager: definition %s is not for us (backend %i)", def->id, def->backend);
        return;
    }

    conf_path = g_build_path("/", rootdir ?: "/", "run/NetworkManager/conf.d", def->id, NULL);
    g_debug("NetworkManager: creating %s", conf_path);
}

static void
nd_append_non_nm_ids(gpointer key, gpointer value, gpointer str)
{
    net_definition* nd = value;

    if (nd->backend != BACKEND_NM) {
        if (nd->match.driver) {
            /* NM cannot match on drivers, so ignore these via udev rules */
            if (!udev_rules)
                udev_rules = g_string_new(NULL);
            g_string_append_printf(udev_rules, "ACTION==\"add|change\", SUBSYSTEM==\"net\", ENV{ID_NET_DRIVER}==\"%s\", ENV{NM_UNMANAGED}=\"1\"\n", nd->match.driver);
        } else {
            g_string_append_netdef_match((GString*) str, nd);
            g_string_append((GString*) str, ",");
        }
    }
}

void
write_nm_conf_finish(const char* rootdir)
{
    GString *s = NULL;
    GError* error = NULL;
    g_autofree char* contents = NULL;
    g_autofree char* path = NULL;

    if (g_hash_table_size(netdefs) == 0)
        return;

    /* Set all devices not managed by us to unmanaged, so that NM does not
     * auto-connect and interferes */
    s = g_string_new("[keyfile]\n# devices managed by networkd\nunmanaged-devices+=");
    g_hash_table_foreach(netdefs, nd_append_non_nm_ids, s);

    contents = g_string_free(s, FALSE);

    path = g_build_path("/", rootdir ?: "/", "run/NetworkManager/conf.d/ubuntu-network.conf", NULL);
    safe_mkdir_p_dir(path);
    if (!g_file_set_contents(path, contents, -1, &error)) {
        g_fprintf(stderr, "ERROR: cannot create file %s: %s\n", path, error->message);
        exit(1);
    }

    /* write generated udev rules */
    if (udev_rules) {
        g_autofree char* rules_path = g_build_path("/", rootdir ?: "/", "run/udev/rules.d/90-ubuntu-network.rules", NULL);
        g_autofree char* rules_contents = NULL;

        rules_contents = g_string_free(udev_rules, FALSE);
        udev_rules = NULL;

        safe_mkdir_p_dir(rules_path);
        if (!g_file_set_contents(rules_path, rules_contents, -1, &error)) {
            g_fprintf(stderr, "ERROR: cannot create file %s: %s\n", rules_path, error->message);
            exit(1);
        }
    }
}
