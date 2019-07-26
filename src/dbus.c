#include <errno.h>
#include <stdbool.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/wait.h>

#include <glib.h>
#include <systemd/sd-bus.h>

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

static const sd_bus_vtable netplan_vtable[] = {
    SD_BUS_VTABLE_START(0),
    SD_BUS_METHOD("Apply", "", "b", method_apply, 0),
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
