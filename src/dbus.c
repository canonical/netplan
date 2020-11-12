#include <errno.h>
#include <stdbool.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <glob.h>
#include <sys/types.h>
#include <sys/wait.h>

#include <glib.h>
#include <glib/gstdio.h>
#include <gio/gio.h>
#include <systemd/sd-bus.h>
#include <systemd/sd-event.h>

#include "_features.h"
#include "util.h"

typedef struct {
    sd_bus *bus;
    sd_event_source *try_es;
    GPid try_pid; /* semaphore. There can only be one 'netplan try' child process at a time */
    const char *config_id; /* current config ID, during any io.netplan.Netplan.Config calls */
    char *handler_id; /* copy of pending config ID, during io.netplan.Netplan.Config.Try() */
    GHashTable *config_slots; /* references to the /io/netplan/Netplan/config/<ID> objects */
} NetplanData;

static const char* NETPLAN_SUBDIRS[3] = {"etc", "run", "lib"};
static const char* NETPLAN_GLOBAL_CONFIG = "BACKUP";
static char* NETPLAN_ROOT = "/"; /* Can be modified for testing netplan-dbus */

static int
terminate_try_child_process(int status, NetplanData *d, const char *config_id)
{
    sd_bus_message *msg = NULL;
    g_autofree gchar *path = NULL;
    int r = 0;

    if (!WIFEXITED(status))
        fprintf(stderr, "'netplan try' exited with status: %d\n", WEXITSTATUS(status)); // LCOV_EXCL_LINE

    /* Cleanup current 'netplan try' child process */
    sd_event_source_unref(d->try_es);
    d->try_es = NULL;
    g_spawn_close_pid (d->try_pid);
    d->try_pid = -1; /* unlock semaphore */

    /* Send .Changed() signal on DBus */
    if (config_id) {
        path = g_strdup_printf("/io/netplan/Netplan/config/%s", config_id);
        r = sd_bus_message_new_signal(d->bus, &msg, path,
                                      "io.netplan.Netplan.Config", "Changed");
    } else
        r = sd_bus_message_new_signal(d->bus, &msg, "/io/netplan/Netplan",
                                      "io.netplan.Netplan", "Changed");
    if (r < 0) {
        // LCOV_EXCL_START
        fprintf(stderr, "Could not create .Changed() signal: %s\n", strerror(-r));
        return r;
        // LCOV_EXCL_STOP
    }

    r = sd_bus_send(d->bus, msg, NULL);
    if (r < 0)
        fprintf(stderr, "Could not send .Changed() signal: %s\n", strerror(-r)); // LCOV_EXCL_LINE
    sd_bus_message_unrefp(&msg);
    return r;
}

static int
_try_accept(bool accept, sd_bus_message *m, NetplanData *d, sd_bus_error *ret_error)
{
    g_autoptr(GError) error = NULL;
    int status = -1;
    int signal = SIGUSR1;
    if (!accept) signal = SIGINT;

    /* Child does not exist or exited already ... */
    if (d->try_pid < 0)
        return sd_bus_reply_method_return(m, "b", false);

    /* Do not send the accept/reject signal, if this call is for another config state */
    if (d->handler_id != NULL && g_strcmp0(d->config_id, d->handler_id))
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "Another 'netplan try' process is already running");

    /* ATTENTION: There might be a race here:
     * When this accept/reject method is called at the same time as the 'netplan try'
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
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan try failed: %s", error->message); // LCOV_EXCL_LINE

    terminate_try_child_process(status, d, d->config_id);
    return sd_bus_reply_method_return(m, "b", true);
}

static int
_copy_yaml_state(char *src_root, char *dst_root, sd_bus_error *ret_error)
{
    glob_t gl;
    g_autoptr(GError) err = NULL;
    int r = find_yaml_glob(src_root, &gl);
    if (!!r)
        // LCOV_EXCL_START
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "Failed glob for YAML files\n");
        // LCOV_EXCL_STOP

    /* Copy all *.yaml files from "/SRC_ROOT/{etc,run,lib}/netplan/" to
     * "/DST_ROOT/{etc,run,lib}/netplan/" */
    GFile *source = NULL;
    GFile *dest = NULL;
    gchar *dest_path = NULL;
    size_t len = strlen(src_root);
    for (size_t i = 0; i < gl.gl_pathc; ++i) {
        dest_path = g_strjoin(NULL, dst_root, (gl.gl_pathv[i])+len, NULL);
        source = g_file_new_for_path(gl.gl_pathv[i]);
        dest = g_file_new_for_path(dest_path);
        g_file_copy(source, dest, G_FILE_COPY_OVERWRITE
                                 |G_FILE_COPY_NOFOLLOW_SYMLINKS
                                 |G_FILE_COPY_ALL_METADATA,
                    NULL, NULL, NULL, &err);
        if (err != NULL) {
            // LCOV_EXCL_START
            r = sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                  "Failed to copy file %s -> %s: %s\n",
                                  g_file_get_path(source), g_file_get_path(dest),
                                  err->message);
            g_object_unref(source);
            g_object_unref(dest);
            g_free(dest_path);
            return r;
            // LCOV_EXCL_STOP
        }
        g_object_unref(source);
        g_object_unref(dest);
        g_free(dest_path);
    }
    globfree(&gl);
    return r;
}

static bool
_clear_tmp_state(const char *config_id, NetplanData *d)
{
    g_autofree gchar *rootdir = NULL;
    /* Remove tmp YAML files */
    rootdir = g_strdup_printf("%s/netplan-config-%s", g_get_tmp_dir(), config_id);
    unlink_glob(rootdir, "/{etc,run,lib}/netplan/*.yaml");

    /* Remove tmp state directories */
    char *subdir = NULL;
    for (int i = 0; i < 3; i++) {
        subdir = g_strdup_printf("%s/%s/netplan", rootdir, NETPLAN_SUBDIRS[i]);
        rmdir(subdir);
        g_free(subdir);
        subdir = g_strdup_printf("%s/%s", rootdir, NETPLAN_SUBDIRS[i]);
        rmdir(subdir);
        g_free(subdir);
    }
    rmdir(rootdir);

    /* No cleanup of DBus object needed, if config_id points to NETPLAN_GLOBAL_CONFIG (backup) */
    if (config_id != NETPLAN_GLOBAL_CONFIG) {
        /* Clear config object from DBus, by unref the appropriate slot */
        sd_bus_slot *slot = g_hash_table_lookup(d->config_slots, config_id);
        sd_bus_slot_unref(slot); /* Clear value/slot */
        g_hash_table_remove(d->config_slots, config_id); /* Clear key */
        /* TODO: HashTable error handling */
    }

    return TRUE;
}

/**
 * io.netplan.Netplan methods
 */

static int
method_apply(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
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
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    // LCOV_EXCL_START
    if (err != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "cannot run netplan apply: %s", err->message);
    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL)
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                "netplan apply failed: %s\nstdout: '%s'\nstderr: '%s'",
                                err->message, stdout, stderr);
    // LCOV_EXCL_STOP

    return sd_bus_reply_method_return(m, "b", true);
}

static int
method_info(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    sd_bus_message *reply = NULL;
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    gint exit_status = 0;

    exit_status = sd_bus_message_new_method_return(m, &reply);
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_open_container(reply, 'a', "(sv)");
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_open_container(reply, 'r', "sv");
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_append(reply, "s", "Features");
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_open_container(reply, 'v', "as");
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_append_strv(reply, (char**)feature_flags);
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_close_container(reply);
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_close_container(reply);
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    exit_status = sd_bus_message_close_container(reply);
    if (exit_status < 0)
       return exit_status; // LCOV_EXCL_LINE

    return sd_bus_send(NULL, reply, NULL);
}

static int
method_get(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    g_autofree gchar *root_dir = NULL;
    gint exit_status = 0;

    if (d->config_id)
        root_dir = g_strdup_printf("--root-dir=%s/netplan-config-%s", g_get_tmp_dir(), d->config_id);
    gchar *argv[] = {SBINDIR "/" "netplan", "get", "all", root_dir, NULL};

    // for tests only: allow changing what netplan to run
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    if (err != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan get: %s", err->message); // LCOV_EXCL_LINE

    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL)
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan get failed: %s\nstdout: '%s'\nstderr: '%s'", err->message, stdout, stderr); // LCOV_EXCL_LINE

    return sd_bus_reply_method_return(m, "s", stdout);
}

static int
method_set(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    g_autoptr(GError) err = NULL;
    g_autofree gchar *stdout = NULL;
    g_autofree gchar *stderr = NULL;
    g_autofree gchar *origin = NULL;
    g_autofree gchar *root_dir = NULL;
    gint exit_status = 0;
    char *config_delta = NULL;
    char *origin_hint = NULL;

    if (sd_bus_message_read(m, "ss", &config_delta, &origin_hint) < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot extract config_delta or origin_hint"); // LCOV_EXCL_LINE

    if (!!strcmp(origin_hint, ""))
        origin = g_strdup_printf("--origin-hint=%s", origin_hint);
    else
        origin = g_strdup("");

    if (d->config_id)
        root_dir = g_strdup_printf("--root-dir=%s/netplan-config-%s", g_get_tmp_dir(), d->config_id);
    gchar *argv[] = {SBINDIR "/" "netplan", "set", config_delta, origin, root_dir, NULL};

    // for tests only: allow changing what netplan to run
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    g_spawn_sync("/", argv, NULL, 0, NULL, NULL, &stdout, &stderr, &exit_status, &err);
    if (err != NULL)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan set %s: %s", config_delta, err->message); // LCOV_EXCL_LINE

    g_spawn_check_exit_status(exit_status, &err);
    if (err != NULL)
       return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "netplan set failed: %s\nstdout: '%s'\nstderr: '%s'", err->message, stdout, stderr); // LCOV_EXCL_LINE

    return sd_bus_reply_method_return(m, "b", true);
}

static int
netplan_try_cancelled_cb(sd_event_source *es, const siginfo_t *si, void* userdata)
{
    NetplanData *d = userdata;
    g_autofree gchar *state_dir = NULL;
    int r = 0;
    if (d->handler_id) {
        /* Delete GLOBAL state */
        unlink_glob(NETPLAN_ROOT, "/{etc,run,lib}/netplan/*.yaml");
        /* Restore GLOBAL backup config state to main rootdir */
        state_dir = g_strdup_printf("%s/netplan-config-%s", g_get_tmp_dir(), NETPLAN_GLOBAL_CONFIG);
        _copy_yaml_state(state_dir, NETPLAN_ROOT, NULL);

        /* Clear GLOBAL backup and config state */
        _clear_tmp_state(NETPLAN_GLOBAL_CONFIG, d);
        _clear_tmp_state(d->handler_id, d);
    }

    r = terminate_try_child_process(si->si_status, d, d->handler_id);
    /* free and reset handler_id, i.e. copy of config state ID */
    g_free(d->handler_id);
    d->handler_id = NULL; /* unlock pending config ID */
    return r;
}

static int
method_try(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    g_autoptr(GError) err = NULL;
    g_autofree gchar *timeout = NULL;
    gint child_stdin = -1; /* child process needs an input to function correctly */
    guint seconds = 0;
    int r = -1;
    NetplanData *d = userdata;

    /* Fail if another 'netplan try' process is already running.
     * 'try_pid' can be pre-set to G_MAXINT, if called via method_config_try() */
    if (d->try_pid > 0 && d->try_pid != G_MAXINT)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot run netplan try: already running");

    if (sd_bus_message_read_basic (m, 'u', &seconds) < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED, "cannot extract timeout_seconds"); // LCOV_EXCL_LINE
    if (seconds > 0)
        timeout = g_strdup_printf("--timeout=%u", seconds);
    gchar *argv[] = {SBINDIR "/" "netplan", "try", timeout, NULL};

    // for tests only: allow changing what netplan to run
    if (getenv("DBUS_TEST_NETPLAN_CMD") != 0)
       argv[0] = getenv("DBUS_TEST_NETPLAN_CMD");

    /* Launch 'netplan try' child process, lock 'try_pid' to real PID */
    g_spawn_async_with_pipes("/", argv, NULL,
                             G_SPAWN_DO_NOT_REAP_CHILD|G_SPAWN_STDOUT_TO_DEV_NULL,
                             NULL, NULL, &d->try_pid, &child_stdin, NULL, NULL, &err);
    if (err)
        // LCOV_EXCL_START
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "cannot run netplan try: %s", err->message);
        // LCOV_EXCL_STOP

    /* Register an event handler, trigged when the child process exits */
    if (d->config_id)
        d->handler_id = g_strdup(d->config_id); /* to free in event handler */
    r = sd_event_add_child(sd_bus_get_event(d->bus), &d->try_es, d->try_pid,
                           WEXITED, netplan_try_cancelled_cb, d);
    if (r < 0)
        // LCOV_EXCL_START
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "cannot watch 'netplan try' child: %s", strerror(-r));
        // LCOV_EXCL_STOP

    return sd_bus_reply_method_return(m, "b", true);
}

static int
method_cancel(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    return _try_accept(FALSE, m, userdata, ret_error);
}

/**
 * io.netplan.Netplan.Config methods
 */

static int
method_config_apply(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    g_autofree gchar *state_dir = NULL;
    int r = 0;
    /* trim 27 chars (i.e. "/io/netplan/Netplan/config/") from path to get the config ID */
    d->config_id = sd_bus_message_get_path(m) + 27;

    if (d->try_pid < 0) {
        /* Delete GLOBAL state */
        unlink_glob(NETPLAN_ROOT, "/{etc,run,lib}/netplan/*.yaml");
        /* Copy current config state to GLOBAL */
        state_dir = g_strdup_printf("%s/netplan-config-%s", g_get_tmp_dir(), d->config_id);
        _copy_yaml_state(state_dir, NETPLAN_ROOT, ret_error);
        d->handler_id = g_strdup(d->config_id);
    }

    r = method_apply(m, d, ret_error);
    _clear_tmp_state(d->config_id, d);

    /* unlock current config ID and handler ID */
    d->config_id = NULL;
    g_free(d->handler_id);
    d->handler_id = NULL;
    return r;
}

static int
method_config_get(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    /* trim 27 chars (i.e. "/io/netplan/Netplan/config/") from path to get the config ID */
    d->config_id = sd_bus_message_get_path(m) + 27;
    int r = method_get(m, userdata, ret_error);
    /* Reset config_id for next method call */
    d->config_id = NULL;
    return r;
}

static int
method_config_set(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    /* trim 27 chars (i.e. "/io/netplan/Netplan/config/") from path to get the config ID */
    d->config_id = sd_bus_message_get_path(m) + 27;
    int r = method_set(m, d, ret_error);
    /* Reset config_id for next method call */
    d->config_id = NULL;
    return r;
}

static int
method_config_try(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    g_autofree gchar *path = NULL;
    g_autofree gchar *state_dir = NULL;
    if (d->try_pid > 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "Another Try() is currently in progress: PID %d\n", d->try_pid);

    int r = 0;
    /* Lock current child process temporarily until we have a real PID */
    d->try_pid = G_MAXINT;
    d->config_id = sd_bus_message_get_path(m) + 27;

    /* Backup GLOBAL state */
    path = g_strdup_printf("%s/netplan-config-%s", g_get_tmp_dir(), NETPLAN_GLOBAL_CONFIG);
    /* Create {etc,run,lib} subdirs with owner r/w permissions */
    char *subdir = NULL;
    for (int i = 0; i < 3; i++) {
        subdir = g_strdup_printf("%s/%s/netplan", path, NETPLAN_SUBDIRS[i]);
        r = g_mkdir_with_parents(subdir, 0700);
        if (r < 0)
            // LCOV_EXCL_START
            return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                    "Failed to create '%s': %s\n", subdir, strerror(errno));
            // LCOV_EXCL_STOP
        g_free(subdir);
    }

    /* Copy main *.yaml files from /{etc,run,lib}/netplan/ to GLOBAL backup dir */
    _copy_yaml_state(NETPLAN_ROOT, path, ret_error);

    /* Clear main *.yaml files */
    unlink_glob(NETPLAN_ROOT, "/{etc,run,lib}/netplan/*.yaml");

    /* Copy current config *.yaml state to main rootdir (i.e. /etc/netplan/) */
    state_dir = g_strdup_printf("%s/netplan-config-%s", g_get_tmp_dir(), d->config_id);
    _copy_yaml_state(state_dir, NETPLAN_ROOT, ret_error);

    /* Exec try */
    return method_try(m, userdata, ret_error);
}

static int
method_config_cancel(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    g_autofree gchar *state_dir = NULL;
    int r = 0;
    /* trim 27 chars (i.e. "/io/netplan/Netplan/config/") from path to get the config ID */
    d->config_id = sd_bus_message_get_path(m) + 27;

    /* Cancel the current 'netplan try' process */
    if (d->try_pid > 0)
        r = method_cancel(m, d, ret_error);
    else
        r = sd_bus_reply_method_return(m, "b", true);

    if (d->handler_id && !g_strcmp0(d->config_id, d->handler_id)) {
        /* Delete GLOBAL state */
        unlink_glob(NETPLAN_ROOT, "/{etc,run,lib}/netplan/*.yaml");
        /* Restore GLOBAL backup config state to main rootdir */
        state_dir = g_strdup_printf("%s/netplan-config-%s", g_get_tmp_dir(), NETPLAN_GLOBAL_CONFIG);
        _copy_yaml_state(state_dir, NETPLAN_ROOT, ret_error);

        /* Clear GLOBAL backup and config state */
        _clear_tmp_state(NETPLAN_GLOBAL_CONFIG, d);

        /* Clear pending Try() handler ID */
        g_free(d->handler_id);
        d->handler_id = NULL;
    }

    /* Clear tmp state */
    _clear_tmp_state(d->config_id, d);
    d->config_id = NULL;
    return r;
}

static const sd_bus_vtable config_vtable[] = {
    SD_BUS_VTABLE_START(0),
    SD_BUS_METHOD("Apply", "", "b", method_config_apply, 0),
    SD_BUS_METHOD("Get", "", "s", method_config_get, 0),
    SD_BUS_METHOD("Set", "ss", "b", method_config_set, 0),
    SD_BUS_METHOD("Try", "u", "b", method_config_try, 0),
    SD_BUS_METHOD("Cancel", "", "b", method_config_cancel, 0),
    SD_BUS_VTABLE_END
};

/**
 * Link between io.netplan.Netplan and io.netplan.Netplan.Config
 */

static int
method_config(sd_bus_message *m, void *userdata, sd_bus_error *ret_error)
{
    NetplanData *d = userdata;
    sd_bus_slot *slot = NULL;
    g_autoptr(GError) err = NULL;
    g_autofree gchar *path = NULL;
    int r = 0;

    /* Create temp. directory, according to "netplan-config-XXXXXX" template */
    path = g_dir_make_tmp("netplan-config-XXXXXX", &err);
    if (err != NULL)
        // LCOV_EXCL_START
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "Failed to create temp dir: %s\n", err->message);
        // LCOV_EXCL_STOP

    /* Extract the last 6 randomly generated chars (i.e. "XXXXXX" from template) */
    const char *id = path + strlen(path) - 6;
    const char *obj_path = g_strdup_printf("/io/netplan/Netplan/config/%s", id);
    r = sd_bus_add_object_vtable(d->bus, &slot, obj_path,
                                 "io.netplan.Netplan.Config", config_vtable, userdata);
    // LCOV_EXCL_START
    if (r < 0)
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "Failed to add 'config' object: %s\n", strerror(-r));
    if (!g_hash_table_insert(d->config_slots, g_strdup(id), slot))
        return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                 "Failed to add object slot to HashTable\n");
    // LCOV_EXCL_STOP

    /* Create {etc,run,lib} subdirs with owner r/w permissions */
    char *subdir = NULL;
    for (int i = 0; i < 3; i++) {
        subdir = g_strdup_printf("%s/%s/netplan", path, NETPLAN_SUBDIRS[i]);
        r = g_mkdir_with_parents(subdir, 0700);
        if (r < 0)
            // LCOV_EXCL_START
            return sd_bus_error_setf(ret_error, SD_BUS_ERROR_FAILED,
                                    "Failed to create '%s': %s\n", subdir, strerror(errno));
            // LCOV_EXCL_STOP
        g_free(subdir);
    }

    /* Copy all *.yaml files from /{etc,run,lib}/netplan/ to temp dir */
    _copy_yaml_state(NETPLAN_ROOT, path, ret_error);

    return sd_bus_reply_method_return(m, "o", obj_path);
}

static const sd_bus_vtable netplan_vtable[] = {
    SD_BUS_VTABLE_START(0),
    SD_BUS_METHOD("Apply", "", "b", method_apply, 0),
    SD_BUS_METHOD("Info", "", "a(sv)", method_info, 0),
    SD_BUS_METHOD("Get", "", "s", method_get, 0),
    SD_BUS_METHOD("Set", "ss", "b", method_set, 0),
    SD_BUS_METHOD("Try", "u", "b", method_try, 0),
    SD_BUS_METHOD("Cancel", "", "b", method_cancel, 0),
    SD_BUS_METHOD("Config", "", "o", method_config, 0),
    SD_BUS_VTABLE_END
};

/**
 * DBus setup
 */

static int
terminate_mainloop_cb(sd_event_source *es, const struct signalfd_siginfo *si, void* userdata) {
    sd_event *event = userdata;
    /* Gracefully terminate the mainloop, to write GCOV output */
    sd_event_exit(event, 0);
    return 0;
}

int
main(int argc, char *argv[])
{
    sd_bus_slot *slot = NULL;
    sd_bus *bus = NULL;
    sd_event *event = NULL;
    NetplanData *data = g_new0(NetplanData, 1);
    sigset_t mask;
    int r;

    // for tests only: allow changing which rootdir to use to copy files around
    if (getenv("DBUS_TEST_NETPLAN_ROOT") != 0)
        NETPLAN_ROOT = getenv("DBUS_TEST_NETPLAN_ROOT");

    /* TODO: consider sd_bus_default(&bus) for easier testing on session/user bus */
    r = sd_bus_open_system(&bus);
    if (r < 0) {
        // LCOV_EXCL_START
        fprintf(stderr, "Failed to connect to system bus: %s\n", strerror(-r));
        goto finish;
        // LCOV_EXCL_STOP
    }

    r = sd_event_new(&event);
    if (r < 0) {
        // LCOV_EXCL_START
        fprintf(stderr, "Failed to create event loop: %s\n", strerror(-r));
        goto finish;
        // LCOV_EXCL_STOP
    }

    /* Initialize the userdata */
    data->bus = bus;
    data->try_pid = -1;
    data->config_id = NULL;
    data->handler_id = NULL;
    /* TODO: define a proper free/cleanup function for sd_bus_slot_unref() */
    data->config_slots = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);

    r = sd_bus_add_object_vtable(bus, &slot,
                                 "/io/netplan/Netplan",  /* object path */
                                 "io.netplan.Netplan",   /* interface name */
                                 netplan_vtable,
                                 data);
    if (r < 0) {
        // LCOV_EXCL_START
        fprintf(stderr, "Failed to issue method call: %s\n", strerror(-r));
        goto finish;
        // LCOV_EXCL_STOP
    }

    r = sd_bus_request_name(bus, "io.netplan.Netplan", 0);
    if (r < 0) {
        fprintf(stderr, "Failed to acquire service name: %s\n", strerror(-r));
        goto finish;
    }

    r = sd_bus_attach_event(bus, event, SD_EVENT_PRIORITY_NORMAL);
    if (r < 0) {
        // LCOV_EXCL_START
        fprintf(stderr, "Failed to attach event loop: %s\n", strerror(-r));
        goto finish;
        // LCOV_EXCL_STOP
    }

    /* Mask the SIGCHLD signal, so we can listen to it via mainloop */
    sigemptyset(&mask);
    sigaddset(&mask, SIGCHLD);
    sigaddset(&mask, SIGTERM);
    sigprocmask(SIG_BLOCK, &mask, NULL);

    /* Start the event loop, wait for requests */
    sd_event_add_signal(event, NULL, SIGTERM, terminate_mainloop_cb, event);
    r = sd_event_loop(event);
    if (r < 0)
        fprintf(stderr, "Failed mainloop: %s\n", strerror(-r)); // LCOV_EXCL_LINE
finish:
    g_free(data);
    sd_event_unref(event);
    sd_bus_slot_unref(slot);
    sd_bus_unref(bus);
    /* TODO: unref all slots from HashTable */

    return r < 0 ? EXIT_FAILURE : EXIT_SUCCESS;
}
