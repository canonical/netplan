#include <errno.h>
#include <stdbool.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/wait.h>

#include <glib.h>
#include <systemd/sd-bus.h>

#include "_features.h"

// LCOV_EXCL_START
/* XXX: (cyphermox)
 * This file  is completely excluded from coverage on purpose. Tests should
 * still include code in here, but sadly coverage does not appear to
 * correctly capture tests being run over a DBus bus.
 */

static int method_apply(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    gint exit_status = 0;

    gchar *argv[] = {SBINDIR "/" "netplan", "apply", NULL};

    // for tests only: allow changing what netplan to run
    if (getuid() != 0 && getenv("DBUS_TEST_NETPLAN_CMD") != 0) {
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");
    }

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    if (err != NULL) {
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan apply: %s", err->message);
    }
    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL) {
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan apply failed: %s\nstdout: '%s'\nstderr: '%s'", err->message, stdout, stderr);
    }
    
    return sd_bus_reply_method_return(m, "b", true);
}

static int method_info(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    sd_bus_message *reply = NULL;
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    gint exit_status = 0;

    exit_status = sd_bus_message_new_method_return(m, &reply);
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_open_container(reply, 'a', "(sv)");
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_open_container(reply, 'r', "sv");
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_append(reply, "s", "Features");
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_open_container(reply, 'v', "as");
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_append_strv(reply, (char**)feature_flags);
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_close_container(reply);
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_close_container(reply);
    if (exit_status < 0)
       return exit_status;

    exit_status = sd_bus_message_close_container(reply);
    if (exit_status < 0)
       return exit_status;

    return sd_bus_send(NULL, reply, NULL);
}

/* Call via busctl as:
 * busctl call io.netplan.Netplan /io/netplan/Netplan io.netplan.Netplan Get sa{ss} ethernets.ens3 0 */
static int method_get(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    g_autofree gchar* root_dir = NULL;
    g_autofree gchar* root = NULL;
    gint exit_status = 0;
    char *key;
    char *arg;
    char* value;

    if (sd_bus_message_read_basic(m, 's', &key) < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot extract setting key");

    int r = sd_bus_message_enter_container(m, 'a', "{ss}");
    if (r > 0) {
        for (;;) {
            r = sd_bus_message_enter_container(m, 'e', "ss");
            if (r <= 0)
                break;
            else {
                if (sd_bus_message_read(m, "ss", &arg, &value) >= 0) {
                    if (!strcmp(arg, "root-dir"))
                        root_dir = g_strdup(value);
                    else
                        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "unknown argument: %s (%s)", key, value);
                }
                sd_bus_message_exit_container(m);
            }
        }
        sd_bus_message_exit_container(m);
    }

    if (root_dir)
        root = g_strdup_printf("--root-dir=%s", root_dir);
    else
        root = g_strdup("");

    gchar *argv[] = {SBINDIR "/" "netplan", "get", key, root, NULL};

    // for tests only: allow changing what netplan to run
    if (getuid() != 0 && getenv("DBUS_TEST_NETPLAN_CMD") != 0) {
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");
    }

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    if (err != NULL) {
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan get %s: %s", key, err->message);
    }
    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL) {
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan get failed: %s\nstdout: '%s'\nstderr: '%s'", err->message, stdout, stderr);
    }

    return sd_bus_reply_method_return(m, "s", stdout);
}

/* Call via busctl as:
 * busctl call io.netplan.Netplan /io/netplan/Netplan io.netplan.Netplan Set ssa{ss} ethernets.ens3 "{addresses: [5.6.7.8/24], dhcp4: false}" 1 "origin-hint" "90-test" */
static int method_set(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    g_autofree gchar* key_value = NULL;
    g_autofree gchar* origin_hint = NULL;
    g_autofree gchar* origin = NULL;
    g_autofree gchar* root_dir = NULL;
    g_autofree gchar* root = NULL;
    gint exit_status = 0;
    char* key;
    char* value;

    if (sd_bus_message_read(m, "ss", &key, &value) < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot extract setting key/value");
    key_value = g_strdup_printf("%s=%s", key, value);

    int r = sd_bus_message_enter_container(m, 'a', "{ss}");
    if (r > 0) {
        for (;;) {
            r = sd_bus_message_enter_container(m, 'e', "ss");
            if (r <= 0)
                break;
            else {
                if (sd_bus_message_read(m, "ss", &key, &value) >= 0) {
                    if (!strcmp(key, "origin-hint"))
                        origin_hint = g_strdup(value);
                    else if (!strcmp(key, "root-dir"))
                        root_dir = g_strdup(value);
                    else
                        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "unknown argument: %s (%s)", key, value);
                }
                sd_bus_message_exit_container(m);
            }
        }
        sd_bus_message_exit_container(m);
    }

    if (root_dir)
        root = g_strdup_printf("--root-dir=%s", root_dir);
    else
        root = g_strdup("");
    if (origin_hint)
        origin = g_strdup_printf("--origin-hint=%s", origin_hint);
    else
        origin = g_strdup("");

    gchar *argv[] = {SBINDIR "/" "netplan", "set", key_value, root, origin, NULL};

    // for tests only: allow changing what netplan to run
    if (getuid() != 0 && getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    if (err != NULL) {
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan set %s: %s", key_value, err->message);
    }
    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL) {
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan set failed: %s\nstdout: '%s'\nstderr: '%s'", err->message, stdout, stderr);
    }

    return sd_bus_reply_method_return(m, "b", true);
}

static const sd_bus_vtable netplan_vtable[] = {
    SD_BUS_VTABLE_START(0),
    SD_BUS_METHOD("Apply", "", "b", method_apply, 0),
    SD_BUS_METHOD("Info", "", "a(sv)", method_info, 0),
    SD_BUS_METHOD("Get", "sa{ss}", "s", method_get, 0),
    SD_BUS_METHOD("Set", "ssa{ss}", "b", method_set, 0),
    SD_BUS_VTABLE_END
};

int main(int argc, char *argv[]) {
    sd_bus_slot *slot = NULL;
    sd_bus *bus = NULL;
    int r;
   
    r = sd_bus_open_system(&bus);
    if (r < 0) {
        fprintf(stderr, "Failed to connect to system bus: %s\n", strerror(-r));
        goto finish;
    }

    r = sd_bus_add_object_vtable(bus,
                                     &slot,
                                     "/io/netplan/Netplan",  /* object path */
                                     "io.netplan.Netplan",   /* interface name */
                                     netplan_vtable,
                                     NULL);
    if (r < 0) {
        fprintf(stderr, "Failed to issue method call: %s\n", strerror(-r));
        goto finish;
    }

    r = sd_bus_request_name(bus, "io.netplan.Netplan", 0);
    if (r < 0) {
        fprintf(stderr, "Failed to acquire service name: %s\n", strerror(-r));
        goto finish;
    }

    for (;;) {
        r = sd_bus_process(bus, NULL);
        if (r < 0) {
            fprintf(stderr, "Failed to process bus: %s\n", strerror(-r));
            goto finish;
        }
        if (r > 0)
            continue;

        /* Wait for the next request to process */
        r = sd_bus_wait(bus, (uint64_t) -1);
        if (r < 0) {
            fprintf(stderr, "Failed to wait on bus: %s\n", strerror(-r));
            goto finish;
        }
    }

finish:
    sd_bus_slot_unref(slot);
    sd_bus_unref(bus);

    return r < 0 ? EXIT_FAILURE : EXIT_SUCCESS;
}

// LCOV_EXCL_STOP
