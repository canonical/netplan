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
append_match_section(net_definition* def, GString *s)
{
    /* Note: an empty [Match] section is interpreted as matching all devices,
     * which is what we want for the simple case that you only have one device
     * (of the given type) */

    g_string_append(s, "[Match]\n");
    if (def->match.driver)
        g_string_append_printf(s, "Driver=%s\n", def->match.driver);
    if (def->match.mac)
        g_string_append_printf(s, "MACAddress=%s\n", def->match.mac);
}

static void
write_link_file(net_definition* def, const char* path)
{
    GString *s = NULL;
    g_autofree char *contents = NULL;
    GError *error = NULL;

    /* do we need to write a .link file? */
    if (!def->set_name && !def->wake_on_lan)
        return;

    /* build file contents */
    s = g_string_sized_new(200);
    append_match_section(def, s);

    g_string_append(s, "\n[Link]\n");
    if (def->set_name)
        g_string_append_printf(s, "Name=%s\n", def->set_name);
    /* FIXME: Should this be turned from bool to str and support multiple values? */
    g_string_append_printf(s, "WakeOnLan=%s\n", def->wake_on_lan ? "magic" : "off");

    contents = g_string_free(s, FALSE);

    safe_mkdir_p_dir(path);
    if (!g_file_set_contents(path, contents, -1, &error)) {
        g_fprintf(stderr, "ERROR: cannot create file %s: %s\n", path, error->message);
        exit(1);
    }
}

static void
write_network_file(net_definition* def, const char* path)
{
    GString *s = NULL;
    g_autofree char *contents = NULL;
    GError *error = NULL;

    /* do we need to write a .network file? */
    if (TRUE)  /* we do not yet have any properties that need to go into a .network */
        return;

    /* build file contents */
    s = g_string_sized_new(200);
    append_match_section(def, s);

    g_string_append(s, "\n[Network]\n");
    /* FIXME: put actual properties here */

    contents = g_string_free(s, FALSE);

    safe_mkdir_p_dir(path);
    if (!g_file_set_contents(path, contents, -1, &error)) {
        g_fprintf(stderr, "ERROR: cannot create file %s: %s\n", path, error->message);
        exit(1);
    }
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
    g_autofree char *path_base = NULL;
    g_autofree char *link_path = NULL, *network_path = NULL;

    path_base = g_build_path("/", rootdir ?: "/", "run/systemd/network", def->id, NULL);
    link_path = g_strjoin(NULL, path_base, ".link", NULL);
    network_path = g_strjoin(NULL, path_base, ".network", NULL);

    write_link_file(def, link_path);
    write_network_file(def, network_path);
}
