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
#include <errno.h>
#include <sys/stat.h>

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

        case ND_BOND:
            g_string_append(s, "Kind=bond\n");
            break;

        case ND_VLAN:
            g_string_append_printf(s, "Kind=vlan\n\n[VLAN]\nId=%u\n", def->vlan_id);
            break;

        default:
            g_assert_not_reached(); /* LCOV_EXCL_LINE */
    }

    g_string_free_to_file(s, rootdir, path, ".netdev");
}

static void
write_network_file(net_definition* def, const char* rootdir, const char* path)
{
    GString* s = NULL;

    /* do we need to write a .network file? */
    if (!def->dhcp4 && !def->dhcp6 && !def->bridge && !def->bond &&
        !def->ip4_addresses && !def->ip6_addresses && !def->gateway4 && !def->gateway6 &&
        !def->has_vlans)
        return;

    /* build file contents */
    s = g_string_sized_new(200);
    append_match_section(def, s, TRUE);

    g_string_append(s, "\n[Network]\n");
    if (def->dhcp4 && def->dhcp6)
        g_string_append(s, "DHCP=yes\n");
    else if (def->dhcp4)
        g_string_append(s, "DHCP=ipv4\n");
    else if (def->dhcp6)
        g_string_append(s, "DHCP=ipv6\n");
    if (def->ip4_addresses)
        for (unsigned i = 0; i < def->ip4_addresses->len; ++i)
            g_string_append_printf(s, "Address=%s\n", g_array_index(def->ip4_addresses, char*, i));
    if (def->ip6_addresses)
        for (unsigned i = 0; i < def->ip6_addresses->len; ++i)
            g_string_append_printf(s, "Address=%s\n", g_array_index(def->ip6_addresses, char*, i));
    if (def->gateway4)
        g_string_append_printf(s, "Gateway=%s\n", def->gateway4);
    if (def->gateway6)
        g_string_append_printf(s, "Gateway=%s\n", def->gateway6);
    if (def->bridge)
        g_string_append_printf(s, "Bridge=%s\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n", def->bridge);
    if (def->bond)
        g_string_append_printf(s, "Bond=%s\nLinkLocalAddressing=no\nIPv6AcceptRA=no\n", def->bond);
    if (def->has_vlans) {
        /* iterate over all netdefs to find VLANs attached to us */
        GHashTableIter i;
        net_definition* nd;
        g_hash_table_iter_init(&i, netdefs);
        while (g_hash_table_iter_next (&i, NULL, (gpointer*) &nd))
            if (nd->vlan_link == def)
                g_string_append_printf(s, "VLAN=%s\n", nd->id);
    }

    g_string_free_to_file(s, rootdir, path, ".network");
}

static void
write_wpa_conf(net_definition* def, const char* rootdir)
{
    GHashTableIter iter;
    wifi_access_point* ap;
    GString* s = g_string_new("ctrl_interface=/run/wpa_supplicant\n\n");
    g_autofree char* path = g_strjoin(NULL, "run/netplan/wpa-", def->id, ".conf", NULL);
    mode_t orig_umask;

    g_debug("%s: Creating wpa_supplicant configuration file %s", def->id, path);
    g_hash_table_iter_init(&iter, def->access_points);
    while (g_hash_table_iter_next(&iter, NULL, (gpointer) &ap)) {
        g_string_append_printf(s, "network={\n  ssid=\"%s\"\n", ap->ssid);
        if (ap->password)
            g_string_append_printf(s, "  psk=\"%s\"\n", ap->password);
        else
            g_string_append(s, "  key_mgmt=NONE\n");
        switch (ap->mode) {
            case WIFI_MODE_INFRASTRUCTURE:
                /* default in wpasupplicant */
                break;
            case WIFI_MODE_ADHOC:
                g_string_append(s, "  mode=1\n");
                break;
            case WIFI_MODE_AP:
                g_fprintf(stderr, "ERROR: %s: networkd does not support wifi in access point mode\n", def->id);
                exit(1);
        }
        g_string_append(s, "}\n");
    }

    /* use tight permissions as this contains secrets */
    orig_umask = umask(077);
    g_string_free_to_file(s, rootdir, path, NULL);
    umask(orig_umask);
}

/**
 * Generate networkd configuration in @rootdir/run/systemd/network/ from the
 * parsed #netdefs.
 * @rootdir: If not %NULL, generate configuration in this root directory
 *           (useful for testing).
 * Returns: TRUE if @def applies to networkd, FALSE otherwise.
 */
gboolean
write_networkd_conf(net_definition* def, const char* rootdir)
{
    g_autofree char* path_base = g_strjoin(NULL, "run/systemd/network/10-netplan-", def->id, NULL);

    /* We want this for all backends when renaming, as *.link files are
     * evaluated by udev, not networkd itself or NetworkManager. */
    if (def->type < ND_VIRTUAL &&
            (def->backend == BACKEND_NETWORKD || def->set_name))
        write_link_file(def, rootdir, path_base);

    if (def->backend != BACKEND_NETWORKD) {
        g_debug("networkd: definition %s is not for us (backend %i)", def->id, def->backend);
        return FALSE;
    }

    if (def->type == ND_WIFI) {
        g_autofree char* link = g_strjoin(NULL, rootdir ?: "", "/run/systemd/system/multi-user.target.wants/netplan-wpa@", def->id, ".service", NULL);
        if (def->has_match) {
            g_fprintf(stderr, "ERROR: %s: networkd backend does not support wifi with match:, only by interface name\n", def->id);
            exit(1);
        }

        write_wpa_conf(def, rootdir);

        g_debug("Creating wpa_supplicant service enablement link %s", link);
        safe_mkdir_p_dir(link);
        if (symlink("/lib/systemd/system/netplan-wpa@.service", link) < 0 && errno != EEXIST) {
            g_fprintf(stderr, "failed to create enablement symlink: %m\n"); /* LCOV_EXCL_LINE */
            exit(1); /* LCOV_EXCL_LINE */
        }

    }

    if (def->type >= ND_VIRTUAL)
        write_netdev_file(def, rootdir, path_base);
    write_network_file(def, rootdir, path_base);
    return TRUE;
}

/**
 * Clean up all generated configurations in @rootdir from previous runs.
 */
void
cleanup_networkd_conf(const char* rootdir)
{
    unlink_glob(rootdir, "/run/systemd/network/10-netplan-*");
    unlink_glob(rootdir, "/run/netplan/*");
    unlink_glob(rootdir, "/run/systemd/system/multi-user.target.wants/netplan-wpa@*.service");
}

/**
 * Create enablement symlink for systemd-networkd.service.
 */
void
enable_networkd(const char* generator_dir)
{
    g_autofree char* link = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "multi-user.target.wants", "systemd-networkd.service", NULL);
    g_debug("We created networkd configuration, adding %s enablement symlink", link);
    safe_mkdir_p_dir(link);
    if (symlink("../systemd-networkd.service", link) < 0 && errno != EEXIST) {
        g_fprintf(stderr, "failed to create enablement symlink: %m\n"); /* LCOV_EXCL_LINE */
        exit(1); /* LCOV_EXCL_LINE */
    }

    g_autofree char* link2 = g_build_path(G_DIR_SEPARATOR_S, generator_dir, "network-online.target.wants", "systemd-networkd-wait-online.service", NULL);
    safe_mkdir_p_dir(link2);
    if (symlink("/lib/systemd/system/systemd-networkd-wait-online.service", link2) < 0 && errno != EEXIST) {
        g_fprintf(stderr, "failed to create enablement symlink: %m\n"); /* LCOV_EXCL_LINE */
        exit(1); /* LCOV_EXCL_LINE */
    }
}
