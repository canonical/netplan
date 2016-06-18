#include <stdlib.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "networkd.h"
#include "parse.h"
#include "util.h"

/**
 * Append [Match] section of @def to @s.
 */
static void
append_match_section(net_definition* def, GString* s, gboolean match_rename)
{
    /* Note: an empty [Match] section is interpreted as matching all devices,
     * which is what we want for the simple case that you only have one device
     * (of the given type) */

    g_string_append(s, "[Match]\n");
    if (def->match.driver)
        g_string_append_printf(s, "Driver=%s\n", def->match.driver);
    if (def->match.mac)
        g_string_append_printf(s, "MACAddress=%s\n", def->match.mac);
    /* name matching is special: if the .link renames the interface, the
     * .network has to use the renamed one, otherwise the original one */
    if (!match_rename && def->match.original_name)
        g_string_append_printf(s, "OriginalName=%s\n", def->match.original_name);
    if (match_rename) {
        if (def->type >= ND_VIRTUAL)
            g_string_append_printf(s, "Name=%s\n", def->id);
        else if (def->set_name)
            g_string_append_printf(s, "Name=%s\n", def->set_name);
        else if (def->match.original_name)
            g_string_append_printf(s, "Name=%s\n", def->match.original_name);
    }
}

static void
write_link_file(net_definition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;

    g_assert(def->type < ND_VIRTUAL);

    /* do we need to write a .link file? */
    if (!def->set_name && !def->wake_on_lan)
        return;

    /* build file contents */
    s = g_string_sized_new(200);
    append_match_section(def, s, FALSE);

    g_string_append(s, "\n[Link]\n");
    if (def->set_name)
        g_string_append_printf(s, "Name=%s\n", def->set_name);
    /* FIXME: Should this be turned from bool to str and support multiple values? */
    g_string_append_printf(s, "WakeOnLan=%s\n", def->wake_on_lan ? "magic" : "off");

    g_string_free_to_file(s, rootdir, path, ".link");
}

static void
write_netdev_file(net_definition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;

    g_assert(def->type >= ND_VIRTUAL);

    /* build file contents */
    s = g_string_sized_new(200);
    g_string_append_printf(s, "[NetDev]\nName=%s\n", def->id);

    switch (def->type) {
        case ND_BRIDGE:
            g_string_append(s, "Kind=bridge\n");
            break;

        default:
            g_assert_not_reached();
    }

    g_string_free_to_file(s, rootdir, path, ".netdev");
}

static void
write_network_file(net_definition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;

    /* do we need to write a .network file? */
    if (!def->dhcp4 && !def->bridge)
        return;

    /* build file contents */
    s = g_string_sized_new(200);
    append_match_section(def, s, TRUE);

    g_string_append(s, "\n[Network]\n");
    if (def->dhcp4)
        g_string_append(s, "DHCP=ipv4\n");
    if (def->bridge)
        g_string_append_printf(s, "Bridge=%s\n", def->bridge);

    g_string_free_to_file(s, rootdir, path, ".network");
}

/**
 * Generate networkd configuration in @rootdir/run/systemd/network/ from the
 * parsed #netdefs.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 */
void
write_networkd_conf(net_definition* def, const char* rootdir)
{
    g_autofree char* path_base = g_build_path(G_DIR_SEPARATOR_S, "run/systemd/network", def->id, NULL);

    /* We want this for all backends when renaming, as *.link files are
     * evaluated by udev, not networkd itself or NetworkManager. */
    if (def->type < ND_VIRTUAL &&
            (def->backend == BACKEND_NETWORKD || def->set_name))
        write_link_file(def, rootdir, path_base);

    if (def->backend != BACKEND_NETWORKD) {
        g_debug("networkd: definition %s is not for us (backend %i)", def->id, def->backend);
        return;
    }

    if (def->type >= ND_VIRTUAL)
        write_netdev_file(def, rootdir, path_base);
    write_network_file(def, rootdir, path_base);
}
