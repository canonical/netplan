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
#include <systemd/sd-event.h>

#include "_features.h"

// LCOV_EXCL_START
/* XXX: (cyphermox)
 * This file  is completely excluded from coverage on purpose. Tests should
 * still include code in here, but sadly coverage does not appear to
 * correctly capture tests being run over a DBus bus.
 */

typedef struct netplan_data {
    sd_bus *bus;
    sd_event_source *try_es;
    GPid try_pid;
    guint config_inc;
} NetplanData;

static int
send_config_changed_signal(sd_bus *bus)
{
    sd_bus_message *msg = NULL;
    int r = sd_bus_message_new_signal(bus, &msg, "/io/netplan/Netplan",
                                      "io.netplan.Netplan", "Changed");
    if (r < 0) {
        fprintf(stderr, "Could not create .Changed() signal: %s\n", strerror(-r));
        return r;
    }

    r = sd_bus_send(bus, msg, NULL);
    if (r < 0)
        fprintf(stderr, "Could not send .Changed() signal: %s\n", strerror(-r));
    sd_bus_message_unrefp(&msg);
    return r;
}

static void
_clear_try_child(int status, NetplanData *d)
{
    if (!WIFEXITED(status))
        fprintf(stderr, "'netplan try' exited with status: %d\n", WEXITSTATUS(status));

    /* Cleanup current 'netplan try' child process */
    sd_event_source_unref(d->try_es);
    d->try_es = NULL;
    g_spawn_close_pid (d->try_pid);
    d->try_pid = -1;
}

static int
_try_accept(bool accept, sd_bus_message *m, NetplanData *d, sd_bus_error *ret_error)
{
    GError *error = NULL;
    int status = -1;
    int signal = SIGUSR1;
    if (!accept) signal = SIGINT;

    /* Child does not exist or exited already ... */
    if (d->try_pid < 0)
        return sd_bus_reply_method_return(m, "b", false);
    /* ATTENTION: There might be a race here:
     * When the accept handler is called at the same time as the 'netplan try'
     * python process is reverting and closing itself. Not sure what to do about it...
     * Maybe this needs to be fixed in python code, so that the
     * 'netplan.terminal.InputRejected' exception (i.e. self-revert) cannot be
     * interrupted by another exception/signal */

    /* Send confirm (SIGUSR1) or cancel (SIGINT) signal to 'netplan try' process.
     * Wait for the child process to stop, synchronously.
     * Check return code/errors. */
    kill(d->try_pid, signal);
    waitpid(d->try_pid, &status, 0);
    g_spawn_check_exit_status(status, &error);
    if (error != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan try failed: %s", error->message);

    _clear_try_child(status, d);
    send_config_changed_signal(d->bus);
    return sd_bus_reply_method_return(m, "b", true);
}

static int method_apply(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    gint exit_status = 0;
    NetplanData *d = userdata;

    /* Accept the current 'netplan try', if active.
     * Otherwise execute 'netplan apply' directly. */
    if (d->try_pid > 0)
        return _try_accept(TRUE, m, userdata, ret_error);

    gchar *argv[] = {SBINDIR "/" "netplan", "apply", NULL};

    // for tests only: allow changing what netplan to run
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0) {
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
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0)
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
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0)
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
handle_netplan_try(sd_event_source *es, const siginfo_t *si, void* userdata)
{
    NetplanData *d = userdata;
    _clear_try_child(si->si_status, d);
    return send_config_changed_signal(d->bus);
}

static int method_try(sd_bus_message *m, void *userdata, sd_bus_error *ret_error) {
    g_autoptr(GError) err = NULL;
    g_autofree gchar *timeout = NULL;
    gint child_stdin = -1; //Child process needs an input to function correctly
    guint seconds = 0;
    int r = -1;
    NetplanData *d = userdata;

    /* Fail if another 'netplan try' process is already running. */
    if (d->try_pid > 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan try: already running");

    if (sd_bus_message_read_basic (m, 'u', &seconds) < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot extract timeout_seconds");
    if (seconds > 0)
        timeout = g_strdup_printf("--timeout=%u", seconds);
    gchar *argv[] = {SBINDIR "/" "netplan", "try", timeout, NULL};

    // for tests only: allow changing what netplan to run
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    /* Launch 'netplan try' child process */
    g_spawn_async_with_pipes("/", argv, NULL,
                             G_SPAWN_DO_NOT_REAP_CHILD|G_SPAWN_STDOUT_TO_DEV_NULL,
                             NULL, NULL, &d->try_pid, &child_stdin, NULL, NULL, &err);
    if (err != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "cannot run netplan try: %s", err->message);

    /* Register an event when the child process exits */
    r = sd_event_add_child(sd_bus_get_event(d->bus), &d->try_es, d->try_pid,
                           WEXITED, handle_netplan_try, d->bus);
    if (r < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "cannot watch 'netplan try' child: %s", strerror(-r));
    if (sd_event_source_set_userdata(d->try_es, d) == NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "cannot set 'netplan try' event data.");

    return sd_bus_reply_method_return(m, "b", true);
}

static int
method_try_cancel(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    return _try_accept(FALSE, m, userdata, ret_error);
}

static const sd_bus_vtable config_vtable[] = {
    SD_BUS_VTABLE_START(0),
    SD_BUS_METHOD("Apply", "", "b", method_apply, 0),
    SD_BUS_METHOD("Get", "", "s", method_get, 0),
    SD_BUS_METHOD("Set", "ss", "b", method_set, 0),
    SD_BUS_METHOD("Try", "u", "b", method_try, 0),
    SD_BUS_METHOD("Cancel", "", "b", method_try_cancel, 0),
    SD_BUS_VTABLE_END
};

static int
method_try_config(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    sd_bus_slot *slot = NULL;
    int r = 0;

    r = sd_bus_add_object_vtable(d->bus, &slot,
                                 g_strdup_printf("/io/netplan/Netplan/config/%d", d->config_inc++),
                                 "io.netplan.Netplan.Config", config_vtable, userdata);
    if (r < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "Failed to add 'config' object: %s\n", strerror(-r));

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
    SD_BUS_METHOD("Config", "", "b", method_try_config, 0),
    SD_BUS_VTABLE_END
};

int main(int argc, char *argv[]) {
    sd_bus_slot *slot = NULL;
    sd_bus *bus = NULL;
    sd_event *event = NULL;
    NetplanData *data = g_new0(NetplanData, 1);
    sigset_t mask;
    int r;

    r = sd_bus_open_system(&bus);
    if (r < 0) {
        fprintf(stderr, "Failed to connect to system bus: %s\n", strerror(-r));
        goto finish;
    }

    r = sd_event_new(&event);
    if (r < 0) {
        fprintf(stderr, "Failed to create event loop: %s\n", strerror(-r));
        goto finish;
    }

    /* Initialize the userdata */
    data->bus = bus;
    data->try_pid = -1;
    data->config_inc = 0;

    r = sd_bus_add_object_vtable(bus,
                                     &slot,
                                     "/io/netplan/Netplan",  /* object path */
                                     "io.netplan.Netplan",   /* interface name */
                                     netplan_vtable,
                                     data);
    if (r < 0) {
        fprintf(stderr, "Failed to issue method call: %s\n", strerror(-r));
        goto finish;
    }

    r = sd_bus_request_name(bus, "io.netplan.Netplan", 0);
    if (r < 0) {
        fprintf(stderr, "Failed to acquire service name: %s\n", strerror(-r));
        goto finish;
    }

    r = sd_bus_attach_event(bus, event, SD_EVENT_PRIORITY_NORMAL);
    if (r < 0) {
        fprintf(stderr, "Failed to attach event loop: %s\n", strerror(-r));
        goto finish;
    }

    /* Mask the SIGCHLD signal, so we can listen to it via mainloop */
    sigemptyset(&mask);
    sigaddset(&mask, SIGCHLD);
    sigprocmask(SIG_BLOCK, &mask, NULL);

    /* Start the event loop, wait for requests */
    r = sd_event_loop(event);
    if (r < 0)
        fprintf(stderr, "Failed mainloop: %s\n", strerror(-r));
finish:
    g_free(data);
    sd_event_unref(event);
    sd_bus_slot_unref(slot);
    sd_bus_unref(bus);

    return r < 0 ? EXIT_FAILURE : EXIT_SUCCESS;
}

// LCOV_EXCL_STOP
