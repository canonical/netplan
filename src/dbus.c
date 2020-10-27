#include <errno.h>
#include <stdbool.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
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

static gint _try_child_stdin = -1;
static GPid _try_child_pid = -1;

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

static int method_get(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    gint exit_status = 0;

    gchar *argv[] = {SBINDIR "/" "netplan", "get", "all", NULL};

    // for tests only: allow changing what netplan to run
    if (getuid() != 0 && getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    if (err != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan get: %s", err->message);

    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL)
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan get failed: %s\nstdout: '%s'\nstderr: '%s'", err->message, stdout, stderr);

    return sd_bus_reply_method_return(m, "s", stdout);
}

static int method_set(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    g_autofree gchar* origin = NULL;
    gint exit_status = 0;
    char* config_delta = NULL;
    char* origin_hint = NULL;

    if (sd_bus_message_read(m, "ss", &config_delta, &origin_hint) < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot extract config_delta or origin_hint");

    if (!!strcmp(origin_hint, ""))
        origin = g_strdup_printf("--origin-hint=%s", origin_hint);
    else
        origin = g_strdup("");

    gchar *argv[] = {SBINDIR "/" "netplan", "set", config_delta, origin, NULL};

    // for tests only: allow changing what netplan to run
    if (getuid() != 0 && getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    if (err != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan set %s: %s", config_delta, err->message);

    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL)
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan set failed: %s\nstdout: '%s'\nstderr: '%s'", err->message, stdout, stderr);

    return sd_bus_reply_method_return(m, "b", true);
}

static int
_netplan_try_is_child_alive(sd_bus_message *m, sd_bus_error *ret_error)
{
    int status = -1;
    int r = -1;

    if (_try_child_pid < 0)
        return sd_bus_reply_method_return(m, "b", false);
        //XXX: return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "Invalid netplan try PID");

    r = (int)waitpid(_try_child_pid, &status, WNOHANG);
    if (r > 0 && status == 0) {
        /* The child already exited. Cannot send signal. Cleanup. */
        _try_child_pid = -1;
        return sd_bus_reply_method_return(m, "b", false);
    }
    //TODO: handle error cases

    return 0;
}

static int method_try(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *timeout = NULL;
    guint seconds = 0;
    int status = -1;
    int r = -1;

    /* There seems to be an old 'netlan try' process... Is it still running? */
    if (_try_child_pid > 0) {
        r = (int)waitpid(_try_child_pid, &status, WNOHANG);
        /* The child already exited. Cleanup. */
        if (r > 0 && status == 0)
            _try_child_pid = -1;
        else
            return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan try: already running");
    }

    if (sd_bus_message_read_basic (m, 'u', &seconds) < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot extract timeout_seconds");
    if (seconds > 0)
        timeout = g_strdup_printf("--timeout=%u", seconds);
    gchar *argv[] = {SBINDIR "/" "netplan", "try", timeout, NULL};

    // for tests only: allow changing what netplan to run
    if (getuid() != 0 && getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    g_spawn_async_with_pipes("/", argv, NULL, G_SPAWN_DO_NOT_REAP_CHILD|G_SPAWN_STDOUT_TO_DEV_NULL,
                             NULL, NULL, &_try_child_pid, &_try_child_stdin, NULL, NULL, &err);
    if (err != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan try: %s", err->message);

    // TODO: set a timer (via event-loop) to send a Changed() signal via DBus
    //       And cancel/cleanup the try command (i.e. _try_child_pid = -1)

    return sd_bus_reply_method_return(m, "b", true);
}

static int method_try_cancel(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    GError *error = NULL;
    GIOChannel *stdin = NULL;
    int status = -1;
    int r = _netplan_try_is_child_alive(m, ret_error);

    if (r != 0)
        return r;

    /* Child does not exist or exited already ... */
    // XXX: isn't this checked in _netplan_try_is_child_alive() already?
    if (_try_child_pid < 0 || waitpid (_try_child_pid, &status, WNOHANG) < 0)
        return sd_bus_reply_method_return(m, "b", false);

    /* Send cancel signal to 'netplan try' process */
    kill(_try_child_pid, SIGINT);
    waitpid (_try_child_pid, &status, 0);
    g_spawn_check_exit_status(status, &error);
    if (error != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan try failed: %s", error->message);
    if (!WIFEXITED(status))
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan try failed: status code %d (IFEXITED)", WEXITSTATUS(status));
    //XXX: remove debugging output
    printf("Child exited with status code %d\n", WEXITSTATUS(status));

    g_spawn_close_pid (_try_child_pid);
    _try_child_pid = -1;

    return sd_bus_reply_method_return(m, "b", true);
}

static int method_try_confirm(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    // TODO: move this into Apply()
    GError *error = NULL;
    int status = -1;
    int r = _netplan_try_is_child_alive(m, ret_error);

    if (r != 0)
        return r;

     /* Child does not exist or exited already ... */
    // XXX: isn't this checked in _netplan_try_is_child_alive() already?
    if (_try_child_pid < 0 || waitpid (_try_child_pid, &status, WNOHANG) < 0)
        return sd_bus_reply_method_return(m, "b", false);

    /* Send confirm signal to 'netplan try' process */
    kill(_try_child_pid, SIGUSR1);
    waitpid(_try_child_pid, &status, 0);
    g_spawn_check_exit_status(status, &error);
    if (error != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan try failed: %s", error->message);
    if (!WIFEXITED(status))
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan try failed: status code %d (IFEXITED)", WEXITSTATUS(status));
    //XXX: remove debugging output
    printf("Child exited with status code %d\n", WEXITSTATUS(status));

    g_spawn_close_pid (_try_child_pid);
    _try_child_pid = -1;

    return sd_bus_reply_method_return(m, "b", true);
}

static const sd_bus_vtable netplan_vtable[] = {
    SD_BUS_VTABLE_START(0),
    SD_BUS_METHOD("Apply", "", "b", method_apply, 0),
    SD_BUS_METHOD("Info", "", "a(sv)", method_info, 0),
    SD_BUS_METHOD("Get", "", "s", method_get, 0),
    SD_BUS_METHOD("Set", "ss", "b", method_set, 0),
    SD_BUS_METHOD("Try", "u", "b", method_try, 0),
    SD_BUS_METHOD("Cancel", "", "b", method_try_cancel, 0),
    SD_BUS_METHOD("Confirm", "", "b", method_try_confirm, 0),
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
