/*
 * Copyright (C) 2019 Canonical, Ltd.
 * Author: Mathieu Trudel-Lapierre <mathieu.trudel-lapierre@canonical.com>
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

#include <Python.h>

#include "version_info.h"
#include "features.h"

const char* NETPLAN_VERSION = "2.98.1";

PyObject *
pynetplan_version(PyObject* self, PyObject *args)
{
    return Py_BuildValue("s", NETPLAN_VERSION);
}

PyObject *
pynetplan_features(PyObject* self, PyObject *args)
{
    PyObject *flags = PyList_New(0);

    for (const char **flag = feature_flags; *flag != NULL; flag++) {
        PyList_Append(flags, PyBytes_FromString(*flag));
    }
    return flags;
}

static PyMethodDef NetplanVersionInfoMethods[] = {
    {"version", pynetplan_version, METH_VARARGS,
     "Return the number of arguments received by the process."},
    {"features", pynetplan_features, METH_VARARGS,
     "Return the number of arguments received by the process."},
    {NULL, NULL, 0, NULL}
};

static PyModuleDef NetplanVersionInfoModule = {
    PyModuleDef_HEAD_INIT, "version_info", NULL, -1, NetplanVersionInfoMethods,
    NULL, NULL, NULL, NULL
};

PyObject*
PyInit_version_info(void)
{
    return PyModule_Create(&NetplanVersionInfoModule);
}
