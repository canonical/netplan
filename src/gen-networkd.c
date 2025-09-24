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
#include <string.h>
#include <unistd.h>
#include <ctype.h>
#include <errno.h>
#include <net/if.h>
#include <sys/stat.h>

#include <glib.h>
#include <glib/gprintf.h>

#include "networkd.h"
#include "parse.h"
#include "names.h"
#include "util.h"
#include "util-internal.h"
#include "validation.h"

/**
 * Query sysfs for the MAC address (up to 20 bytes for infiniband) of @ifname
 * The caller owns the returned string and needs to free it.
 */
STATIC char*
_netplan_sysfs_get_mac_by_ifname(const char* ifname, const char* rootdir)
{
    g_autofree gchar* content = NULL;
    g_autofree gchar* sysfs_path = NULL;
    sysfs_path = g_build_path(G_DIR_SEPARATOR_S, rootdir != NULL ? rootdir : G_DIR_SEPARATOR_S,
                              "sys", "class", "net", ifname, "address", NULL);

    if (!g_file_get_contents (sysfs_path, &content, NULL, NULL)) {
        g_debug("%s: Cannot read file contents.", __func__);
        return NULL;
    }

    // Trim whitespace & clone value
    return g_strdup(g_strstrip(content));
}

/**
 * Query sysfs for the driver used by @ifname
 * The caller owns the returned string and needs to free it.
 */
STATIC char*
_netplan_sysfs_get_driver_by_ifname(const char* ifname, const char* rootdir)
{
    g_autofree gchar* link = NULL;
    g_autofree gchar* sysfs_path = NULL;
    sysfs_path = g_build_path(G_DIR_SEPARATOR_S, rootdir != NULL ? rootdir : G_DIR_SEPARATOR_S,
                              "sys", "class", "net", ifname, "device", "driver", NULL);

    link = g_file_read_link(sysfs_path, NULL);
    if (!link) {
        g_debug("%s: Cannot read symlink of %s.", __func__, sysfs_path);
        return NULL;
    }

    return g_path_get_basename(link);
}

STATIC void
_netplan_query_system_interfaces(GHashTable* tbl)
{
    g_assert(tbl != NULL);
    struct if_nameindex *if_nidxs, *intf;
    if_nidxs = if_nameindex();
    if (if_nidxs != NULL) {
        for (intf = if_nidxs; intf->if_index != 0 || intf->if_name != NULL; intf++)
            g_hash_table_add(tbl, g_strdup(intf->if_name));
        if_freenameindex(if_nidxs);
    }
}

typedef struct wait_online_data {
    gboolean ignore_carrier;
    gboolean degraded;
    gboolean routable;
} WaitOnlineData;

/**
 * Enumerate all network interfaces (/sys/clas/net/...) and check
 * netplan_netdef_match_interface() to see if they match the current NetDef
 */
STATIC void
_netplan_enumerate_interfaces(const NetplanNetDefinition* def, GHashTable* ifaces, GHashTable* tbl, const char* set_name, WaitOnlineData* data, const char* rootdir)
{
    g_assert(ifaces != NULL);
    g_assert(tbl != NULL);

    GHashTableIter iter;
    gpointer key;
    g_hash_table_iter_init (&iter, ifaces);
    while (g_hash_table_iter_next (&iter, &key, NULL)) {
        const char* ifname = key;
        if (g_hash_table_contains(tbl, ifname) || (set_name && g_hash_table_contains(tbl, set_name))) {
            continue;
        }
        g_autofree gchar* mac = _netplan_sysfs_get_mac_by_ifname(ifname, rootdir);
        g_autofree gchar* driver = _netplan_sysfs_get_driver_by_ifname(ifname, rootdir);
        if (netplan_netdef_match_interface(def, ifname, mac, driver)) {
            // Duplicate the data for every interface matched,
            // so we can have them free'ed one-by-one in the end.
            WaitOnlineData* d = g_malloc0(sizeof(WaitOnlineData));
            *d = *data;
            g_hash_table_replace(tbl, set_name ? g_strdup(set_name) : g_strdup(ifname), d);
        }
    }
}

STATIC gboolean
write_regdom(const NetplanNetDefinition* def, const char* generator_dir, gboolean validation_only, GError** error)
{
    g_assert(generator_dir != NULL);
    g_assert(def->regulatory_domain != NULL);
    g_autofree gchar* id_escaped = NULL;
    g_autofree char* link = g_strjoin(NULL, generator_dir,
                                      "/network.target.wants/netplan-regdom.service", NULL);
    g_autofree char* path = g_strjoin(NULL, generator_dir, "/netplan-regdom.service", NULL);

    GString* s = g_string_new("[Unit]\n");
    g_string_append(s, "Description=Netplan regulatory-domain configuration\n");
    g_string_append(s, "After=network.target\n");
    g_string_append(s, "ConditionFileIsExecutable="SBINDIR"/iw\n");
    g_string_append(s, "\n[Service]\nType=oneshot\n");
    g_string_append_printf(s, "ExecStart="SBINDIR"/iw reg set %s\n", def->regulatory_domain);

    g_autofree char* new_s = _netplan_scrub_systemd_unit_contents(s->str);
    g_string_free(s, TRUE);
    s = g_string_new(new_s);

    if (validation_only) {
        g_string_free(s, TRUE);
        return TRUE;
    }

    mode_t orig_umask = umask(022);
    _netplan_g_string_free_to_file(s, NULL, path, NULL);
    umask(orig_umask);
    _netplan_safe_mkdir_p_dir(link);
    if (symlink(path, link) < 0 && errno != EEXIST) {
        // LCOV_EXCL_START
        g_set_error(error, NETPLAN_FILE_ERROR, errno, "failed to create enablement symlink: %m\n");
        return FALSE;
        // LCOV_EXCL_STOP
    }
    return TRUE;
}

/* netplan-feature: generated-supplicant */
STATIC void
write_wpa_unit(const NetplanNetDefinition* def, const char* generator_dir, gboolean validation_only)
{
    g_assert(generator_dir != NULL);
    g_autofree gchar *stdouth = NULL;

    stdouth = systemd_escape(def->id);

    GString* s = g_string_new("[Unit]\n");
    g_autofree char* path = g_strjoin(NULL, generator_dir, "/netplan-wpa-", stdouth, ".service", NULL);
    g_string_append_printf(s, "Description=WPA supplicant for netplan %s\n", stdouth);
    g_string_append(s, "DefaultDependencies=no\n");
    g_string_append_printf(s, "Requires=sys-subsystem-net-devices-%s.device\n", stdouth);
    g_string_append_printf(s, "After=sys-subsystem-net-devices-%s.device\n", stdouth);
    g_string_append(s, "Before=network.target\nWants=network.target\n\n");
    g_string_append(s, "[Service]\nType=simple\n");
    g_string_append_printf(s, "ExecStart=/sbin/wpa_supplicant -c /run/netplan/wpa-%s.conf -i%s", stdouth, stdouth);

    if (def->type != NETPLAN_DEF_TYPE_WIFI) {
        g_string_append(s, " -Dwired\n");
    } else {
        g_string_append(s, " -Dnl80211,wext\n");
    }

    g_string_append_printf(s, "ExecReload=/sbin/wpa_cli -i %s reconfigure\n", stdouth);

    g_autofree char* new_s = _netplan_scrub_systemd_unit_contents(s->str);
    g_string_free(s, TRUE);
    if (!validation_only) {
        s = g_string_new(new_s);
        mode_t orig_umask = umask(022);
        _netplan_g_string_free_to_file(s, NULL, path, NULL);
        umask(orig_umask);
    }
}

/**
 * Generate networkd configuration in @rootdir/run/systemd/network/ from the
 * parsed #netdefs.
 * @generator_dir: If not %NULL, generate configuration in this root directory
 *                 (useful for testing).
 * @has_been_written: TRUE if @def applies to networkd, FALSE otherwise.
 * Returns: FALSE on error.
 */
gboolean
_netplan_netdef_generate_networkd(
        __unused const NetplanState* np_state,
        const NetplanNetDefinition* def,
        const char *generator_dir,
        gboolean* has_been_written,
        GError** error)
{
    /* TODO: make use of netplan_netdef_get_output_filename() */
    g_autofree char* escaped_netdef_id = g_uri_escape_string(def->id, NULL, TRUE);
    g_autofree char* path_base = g_strjoin(NULL, "run/systemd/network/10-netplan-", escaped_netdef_id, NULL);
    SET_OPT_OUT_PTR(has_been_written, FALSE);
    gboolean validation_only = _netplan_state_get_flags(np_state) & NETPLAN_STATE_VALIDATION_ONLY;

    if (def->regulatory_domain)
        write_regdom(def, generator_dir, validation_only, NULL); /* overwrites global regdom */

    if (def->backend != NETPLAN_BACKEND_NETWORKD) {
        g_debug("networkd: definition %s is not for us (backend %i)", def->id, def->backend);
        return TRUE;
    }

    if (def->type == NETPLAN_DEF_TYPE_MODEM) {
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: %s: networkd backend does not support GSM/CDMA modem configuration\n", def->id);
        return FALSE;
    }

    if (def->type == NETPLAN_DEF_TYPE_WIFI || def->has_auth) {
        g_autofree char* link = g_strjoin(NULL, generator_dir,
                                          "/systemd-networkd.service.wants/netplan-wpa-", escaped_netdef_id, ".service", NULL);
        g_autofree char* slink = g_strjoin(NULL, generator_dir, "/netplan-wpa-", escaped_netdef_id, ".service", NULL);
        if (def->type == NETPLAN_DEF_TYPE_WIFI && def->has_match) {
            g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED, "ERROR: %s: networkd backend does not support wifi with match:, only by interface name\n", def->id);
            return FALSE;
        }

        g_debug("Creating wpa_supplicant unit %s", slink);
        write_wpa_unit(def, generator_dir, validation_only);

        if (!validation_only) {
            g_debug("Creating wpa_supplicant service enablement link %s", link);
            _netplan_safe_mkdir_p_dir(link);
            if (symlink(slink, link) < 0 && errno != EEXIST) {
                // LCOV_EXCL_START
                g_set_error(error, NETPLAN_FILE_ERROR, errno, "failed to create enablement symlink: %m\n");
                return FALSE;
                // LCOV_EXCL_STOP
            }
        }
    }

    if (def->set_mac &&
        !_is_valid_macaddress(def->set_mac) &&
        !_is_macaddress_special_nd_option(def->set_mac)) {
        g_set_error(error, NETPLAN_BACKEND_ERROR, NETPLAN_ERROR_UNSUPPORTED,
                    "ERROR: %s: networkd backend does not support the MAC address option '%s'\n",
                    def->id, def->set_mac);
        return FALSE;
    }

    SET_OPT_OUT_PTR(has_been_written, TRUE);
    return TRUE;
}

/**
 * Implementing Ubuntu's "Definition of an "online" system specification:
 * https://discourse.ubuntu.com/t/spec-definition-of-an-online-system/27838
 */
gboolean
_netplan_networkd_generate_wait_online(const NetplanState* np_state, const char* rootdir, const char* generator_dir)
{
    g_assert(generator_dir != NULL);
    // Set of all current network interfaces, potentially not yet renamed
    g_autoptr (GHashTable) system_interfaces = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    _netplan_query_system_interfaces(system_interfaces);

    // Hash set of non-optional interfaces to wait for
    g_autoptr (GHashTable) non_optional_interfaces = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, g_free);

    // Walk over non-optional NetDefs managed by networkd
    NetplanStateIterator iter;
    netplan_state_iterator_init(np_state, &iter);
    while (netplan_state_iterator_has_next(&iter)) {
        NetplanNetDefinition* def = netplan_state_iterator_next(&iter);
        if (def->backend != NETPLAN_BACKEND_NETWORKD) {
            continue;
        }

        /* When activation-mode is used we default to being optional.
         * Otherwise, systemd might wait indefinitely for the interface to
         * come online.
         */
        if (!(def->optional || def->activation_mode)) {
            WaitOnlineData* d = g_malloc0(sizeof(WaitOnlineData));
            d->ignore_carrier = def->ignore_carrier;

            // Check if we have any IP configuration
            // bond and bridge members will never ask for link-local addresses (see above)
            struct address_iter* addr_iter = _netplan_netdef_new_address_iter(def);
            d->routable =   _netplan_address_iter_next(addr_iter) != NULL // Does it define a static IP?
                          || netplan_netdef_get_dhcp4(def)
                          || netplan_netdef_get_dhcp6(def)
                          || def->accept_ra == NETPLAN_RA_MODE_ENABLED;
            d->degraded =    (   netplan_netdef_get_link_local_ipv4(def)
                              && !(netplan_netdef_get_bond_link(def) || netplan_netdef_get_bridge_link(def)))
                          || (   netplan_netdef_get_link_local_ipv6(def)
                              && !(netplan_netdef_get_bond_link(def) || netplan_netdef_get_bridge_link(def)));
            _netplan_address_iter_free(addr_iter);

            // Not all bond members need to be connected (have carrier) for the parent to be ready
            NetplanNetDefinition* bond_parent = netplan_netdef_get_bond_link(def);
            if (bond_parent && !d->routable && !d->degraded) {
                g_info("Not all bond members need to be connected for %s to be ready. "
                       "Consider marking %s as \"optional: true\", to avoid blocking "
                       "systemd-networkd-wait-online.", bond_parent->id, def->id);
            }

            // no matching => single physical interface, ignoring non-existing interfaces
            // OR: virtual interfaces, those will be created later on and cannot have a matching condition
            gboolean physical_no_match_or_virtual = FALSE
                || (!netplan_netdef_has_match(def) && g_hash_table_contains(system_interfaces, def->id))
                || (netplan_netdef_get_type(def) >= NETPLAN_DEF_TYPE_VIRTUAL);
            if (physical_no_match_or_virtual) { // one individual interface
                WaitOnlineData* data = g_malloc0(sizeof(WaitOnlineData));
                *data = *d;
                g_hash_table_replace(non_optional_interfaces, g_strdup(def->id), data);
            } else if (def->set_name) { // matching on a single interface, to be renamed
                _netplan_enumerate_interfaces(def, system_interfaces, non_optional_interfaces, def->set_name, d, rootdir);
            } else { // matching on potentially multiple interfaces
                // XXX: we shouldn't run this enumeration for every NetDef...
                _netplan_enumerate_interfaces(def, system_interfaces, non_optional_interfaces, NULL, d, rootdir);
            }

            g_free(d);
        }
    }

    // Always create run/systemd/generator.late/systemd-networkd-wait-online.service.d/10-netplan.conf override
    // The "ConditionPathIsSymbolicLink" is Netplan's s-n-wait-online enablement symlink,
    // as we want to run this waiting logic only if enabled by Netplan.
    g_autofree gchar* override = g_strdup_printf("%s/systemd-networkd-wait-online.service.d/10-netplan.conf", generator_dir);
    GString* content = g_string_new("[Unit]\n"
        "ConditionPathIsSymbolicLink=/run/systemd/generator/network-online.target.wants/systemd-networkd-wait-online.service\n");
    if (g_hash_table_size(non_optional_interfaces) == 0) {
        mode_t orig_umask = umask(022);
        _netplan_g_string_free_to_file(content, NULL, override, NULL);
        umask(orig_umask);
        return FALSE;
    }
    // ELSE:
    GString* linklocal_str = g_string_new("");
    GString* routable_str  = g_string_new("");

    GHashTableIter giter;
    gpointer key, value;
    g_hash_table_iter_init (&giter, non_optional_interfaces);
    while (g_hash_table_iter_next (&giter, &key, &value)) {
        const char* ifname = key;
        const WaitOnlineData* data = value;
        // write routeable
        if (data->routable && g_strcmp0(ifname, "lo")) {
            g_string_append_printf(routable_str, " -i %s", ifname);
        }
        // write non_routable
        // XXX: We should be checking IFF_LOOPBACK instead of interface name.
        //      But don't have access to the flags here.
        if (!g_strcmp0(ifname, "lo")) {
            g_string_append_printf(linklocal_str, " -i %s:carrier", ifname); // "carrier" as min-oper state for loopback
        } else if (data->degraded) {
            g_string_append_printf(linklocal_str, " -i %s:%s", ifname, "degraded");
        } else if (!data->ignore_carrier) {
            g_string_append_printf(linklocal_str, " -i %s:%s", ifname, "carrier");
        }
    }

    // allow waiting for "--dns"
    if (routable_str->len > 0) {
        g_string_append(content, "After=systemd-resolved.service\n");
    }
    // clear old s-n-wait-online command
    g_string_append(content, "\n[Service]\nExecStart=\n");

    // wait for all link-local (degraded/carrier) interface
    if (linklocal_str->len > 0) {
        g_string_append_printf(content, "ExecStart=/lib/systemd/systemd-networkd-wait-online%s\n", linklocal_str->str);
    }
    g_string_free(linklocal_str, TRUE);
    // wait for any routable interface
    if (routable_str->len > 0) {
        g_string_append_printf(content, "ExecStart=/lib/systemd/systemd-networkd-wait-online --any --dns -o routable%s\n", routable_str->str);
    }
    g_string_free(routable_str, TRUE);

    g_autofree char* new_content = _netplan_scrub_systemd_unit_contents(content->str);
    g_string_free(content, TRUE);
    content = g_string_new(new_content);
    mode_t orig_umask = umask(022);
    _netplan_g_string_free_to_file(content, NULL, override, NULL);
    umask(orig_umask);
    return TRUE;
}
