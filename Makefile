NETPLAN_SOVER=0.0

BUILDFLAGS = \
	-g \
	-fPIC \
	-std=c99 \
	-D_XOPEN_SOURCE=500 \
	-DSBINDIR=\"$(SBINDIR)\" \
	-Wall \
	-Werror \
	$(NULL)

SYSTEMD_GENERATOR_DIR=$(shell pkg-config --variable=systemdsystemgeneratordir systemd)
SYSTEMD_UNIT_DIR=$(shell pkg-config --variable=systemdsystemunitdir systemd)
BASH_COMPLETIONS_DIR=$(shell pkg-config --variable=completionsdir bash-completion || echo "/etc/bash_completion.d")

GCOV ?= gcov
ROOTPREFIX ?=
PREFIX ?= /usr
LIBDIR ?= $(PREFIX)/lib
ROOTLIBEXECDIR ?= $(ROOTPREFIX)/lib
LIBEXECDIR ?= $(PREFIX)/lib
SBINDIR ?= $(PREFIX)/sbin
DATADIR ?= $(PREFIX)/share
DOCDIR ?= $(DATADIR)/doc
MANDIR ?= $(DATADIR)/man
INCLUDEDIR ?= $(PREFIX)/include

PYCODE = netplan/ $(wildcard src/*.py) $(wildcard tests/*.py) $(wildcard tests/generator/*.py) $(wildcard tests/dbus/*.py)

# Order: Fedora/Mageia/openSUSE || Debian/Ubuntu || null
PYFLAKES3 ?= $(shell which pyflakes-3 || which pyflakes3 || echo true)
PYCODESTYLE3 ?= $(shell which pycodestyle-3 || which pycodestyle || which pep8 || echo true)
NOSETESTS3 ?= $(shell which nosetests-3 || which nosetests3 || echo true)

default: netplan/_features.py generate netplan-dbus dbus/io.netplan.Netplan.service doc/netplan.html doc/netplan.5 doc/netplan-generate.8 doc/netplan-apply.8 doc/netplan-try.8

%.o: src/%.c
	$(CC) $(BUILDFLAGS) $(CFLAGS) $(LDFLAGS) -c $^ `pkg-config --cflags --libs glib-2.0 gio-2.0 yaml-0.1 uuid`

libnetplan.so.$(NETPLAN_SOVER): parse.o util.o validation.o error.o
	$(CC) -shared -Wl,-soname,libnetplan.so.$(NETPLAN_SOVER) $(BUILDFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $^ `pkg-config --libs glib-2.0 gio-2.0 yaml-0.1`
	ln -snf libnetplan.so.$(NETPLAN_SOVER) libnetplan.so

#generate: src/generate.[hc] src/parse.[hc] src/util.[hc] src/networkd.[hc] src/nm.[hc] src/validation.[hc] src/error.[hc]
generate: libnetplan.so.$(NETPLAN_SOVER) nm.o networkd.o openvswitch.o generate.o sriov.o
	$(CC) $(BUILDFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $^ -L. -lnetplan `pkg-config --cflags --libs glib-2.0 gio-2.0 yaml-0.1 uuid`

netplan-dbus: src/dbus.c src/_features.h util.o
	$(CC) $(BUILDFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $^ `pkg-config --cflags --libs libsystemd glib-2.0 gio-2.0`

src/_features.h: src/[^_]*.[hc]
	printf "#include <stddef.h>\nstatic const char *feature_flags[] __attribute__((__unused__)) = {\n" > $@
	awk 'match ($$0, /netplan-feature:.*/ ) { $$0=substr($$0, RSTART, RLENGTH); print "\""$$2"\"," }' $^ >> $@
	echo "NULL, };" >> $@

netplan/_features.py: src/[^_]*.[hc]
	echo "# Generated file" > $@
	echo "NETPLAN_FEATURE_FLAGS = [" >> $@
	awk 'match ($$0, /netplan-feature:.*/ ) { $$0=substr($$0, RSTART, RLENGTH); print "    \""$$2"\"," }' $^ >> $@
	echo "]" >> $@

clean:
	rm -f netplan/_features.py src/_features.h
	rm -f generate doc/*.html doc/*.[1-9]
	rm -f *.o *.so*
	rm -f netplan-dbus dbus/*.service
	rm -f *.gcda *.gcno generate.info
	rm -rf test-coverage .coverage coverage.xml
	find . | grep -E "(__pycache__|\.pyc)" | xargs rm -rf

check: default linting
	tests/cli.py
	LD_LIBRARY_PATH=. $(NOSETESTS3) -v --with-coverage
	tests/validate_docs.sh

linting:
	$(PYFLAKES3) $(PYCODE)
	$(PYCODESTYLE3) --max-line-length=130 $(PYCODE)

coverage: | pre-coverage c-coverage python-coverage

pre-coverage:
	rm -f .coverage
	$(MAKE) CFLAGS="-g -O0 --coverage" clean check
	mkdir -p test-coverage/C test-coverage/python

check-coverage: coverage
	@if grep headerCovTableEntryHi test-coverage/C/index.html | grep -qv '100.*%'; then \
	    echo "FAIL: Test coverage not 100%!" >&2; exit 1; \
	fi
	python3-coverage report --omit=/usr* --show-missing --fail-under=100

c-coverage:
	lcov --directory . --capture --gcov-tool=$(GCOV) -o generate.info
	lcov --remove generate.info "/usr*" -o generate.info
	genhtml -o test-coverage/C/ -t "generate test coverage" generate.info

python-coverage:
	python3-coverage html -d test-coverage/python --omit=/usr* || true
	python3-coverage xml --omit=/usr* || true

install: default
	mkdir -p $(DESTDIR)/$(SBINDIR) $(DESTDIR)/$(ROOTLIBEXECDIR)/netplan $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR) $(DESTDIR)/$(LIBDIR)
	mkdir -p $(DESTDIR)/$(MANDIR)/man5 $(DESTDIR)/$(MANDIR)/man8
	mkdir -p $(DESTDIR)/$(DOCDIR)/netplan/examples
	mkdir -p $(DESTDIR)/$(DATADIR)/netplan/netplan
	mkdir -p $(DESTDIR)/$(INCLUDEDIR)/netplan
	install -m 755 generate $(DESTDIR)/$(ROOTLIBEXECDIR)/netplan/
	find netplan/ -name '*.py' -exec install -Dm 644 "{}" "$(DESTDIR)/$(DATADIR)/netplan/{}" \;
	install -m 755 src/netplan.script $(DESTDIR)/$(DATADIR)/netplan/
	ln -srf $(DESTDIR)/$(DATADIR)/netplan/netplan.script $(DESTDIR)/$(SBINDIR)/netplan
	ln -srf $(DESTDIR)/$(ROOTLIBEXECDIR)/netplan/generate $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR)/netplan
	# lib
	install -m 644 *.so.* $(DESTDIR)/$(LIBDIR)/
	ln -snf libnetplan.so.$(NETPLAN_SOVER) $(DESTDIR)/$(LIBDIR)/libnetplan.so
	# headers, dev data
	install -m 644 src/*.h $(DESTDIR)/$(INCLUDEDIR)/netplan/
	# TODO: install pkg-config once available
	# docs, data
	install -m 644 doc/*.html $(DESTDIR)/$(DOCDIR)/netplan/
	install -m 644 examples/*.yaml $(DESTDIR)/$(DOCDIR)/netplan/examples/
	install -m 644 doc/*.5 $(DESTDIR)/$(MANDIR)/man5/
	install -m 644 doc/*.8 $(DESTDIR)/$(MANDIR)/man8/
	install -T -D -m 644 netplan.completions $(DESTDIR)/$(BASH_COMPLETIONS_DIR)/netplan
	# dbus
	mkdir -p $(DESTDIR)/$(DATADIR)/dbus-1/system.d $(DESTDIR)/$(DATADIR)/dbus-1/system-services
	install -m 755 netplan-dbus $(DESTDIR)/$(ROOTLIBEXECDIR)/netplan/
	install -m 644 dbus/io.netplan.Netplan.conf $(DESTDIR)/$(DATADIR)/dbus-1/system.d/
	install -m 644 dbus/io.netplan.Netplan.service $(DESTDIR)/$(DATADIR)/dbus-1/system-services/

%.service: %.service.in
	sed -e "s#@ROOTLIBEXECDIR@#$(ROOTLIBEXECDIR)#" $< > $@


%.html: %.md
	pandoc -s --toc -o $@ $<

doc/netplan.5: doc/manpage-header.md doc/netplan.md doc/manpage-footer.md
	pandoc -s -o $@ $^

%.8: %.md
	pandoc -s -o $@ $^

.PHONY: clean
