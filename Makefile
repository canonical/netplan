BUILDFLAGS = \
	-std=c99 \
	-D_XOPEN_SOURCE=500 \
	-Wall \
	-Werror \
	$(NULL)

SYSTEMD_GENERATOR_DIR=$(shell pkg-config --variable=systemdsystemgeneratordir systemd)
SYSTEMD_UNIT_DIR=$(shell pkg-config --variable=systemdsystemunitdir systemd)
BASH_COMPLETIONS_DIR=$(shell pkg-config --variable=completionsdir bash-completion || echo "/etc/bash_completion.d")

ROOTPREFIX ?= /
PREFIX ?= /usr
ROOTLIBEXECDIR ?= $(ROOTPREFIX)/lib
SBINDIR ?= $(PREFIX)/sbin
DATADIR ?= $(PREFIX)/share
DOCDIR ?= $(DATADIR)/doc
MANDIR ?= $(DATADIR)/man

PYCODE = netplan/ $(wildcard src/*.py) $(wildcard tests/*.py)

# Order: Fedora/Mageia/openSUSE || Debian/Ubuntu || null
PYFLAKES3 ?= $(shell which pyflakes-3 || which pyflakes3 || echo true)
PYCODESTYLE3 ?= $(shell which pycodestyle-3 || which pycodestyle || which pep8 || echo true)
NOSETESTS3 ?= $(shell which nosetests-3 || which nosetests3 || echo true)

default: generate doc/netplan.html doc/netplan.5 doc/netplan-generate.8 doc/netplan-apply.8 doc/netplan-try.8

generate: src/generate.[hc] src/parse.[hc] src/util.[hc] src/networkd.[hc] src/nm.[hc]
	$(CC) $(BUILDFLAGS) $(CFLAGS) -o $@ $(filter %.c, $^) `pkg-config --cflags --libs glib-2.0 gio-2.0 yaml-0.1 uuid`

clean:
	rm -f generate doc/*.html doc/*.[1-9]
	rm -f *.gcda *.gcno generate.info
	rm -rf test-coverage .coverage

check: default linting
	tests/cli.py
	$(NOSETESTS3) -v --with-coverage
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
	lcov --directory . --capture -o generate.info
	lcov --remove generate.info "/usr*" -o generate.info
	genhtml -o test-coverage/C/ -t "generate test coverage" generate.info

python-coverage:
	python3-coverage html -d test-coverage/python --omit=/usr* || true
	python3-coverage xml --omit=/usr* || true

install: default
	mkdir -p $(DESTDIR)/$(SBINDIR) $(DESTDIR)/$(ROOTLIBEXECDIR)/netplan $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR)
	mkdir -p $(DESTDIR)/$(MANDIR)/man5 $(DESTDIR)/$(MANDIR)/man8
	mkdir -p $(DESTDIR)/$(DOCDIR)/netplan/examples
	mkdir -p $(DESTDIR)/$(DATADIR)/netplan/netplan
	install -m 755 generate $(DESTDIR)/$(ROOTLIBEXECDIR)/netplan/
	find netplan/ -name '*.py' -exec install -Dm 644 "{}" "$(DESTDIR)/$(DATADIR)/netplan/{}" \;
	install -m 755 src/netplan.script $(DESTDIR)/$(DATADIR)/netplan/
	ln -sr $(DESTDIR)/$(DATADIR)/netplan/netplan.script $(DESTDIR)/$(SBINDIR)/netplan
	ln -sr $(DESTDIR)/$(ROOTLIBEXECDIR)/netplan/generate $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR)/netplan
	install -m 644 doc/*.html $(DESTDIR)/$(DOCDIR)/netplan/
	install -m 644 examples/*.yaml $(DESTDIR)/$(DOCDIR)/netplan/examples/
	install -m 644 doc/*.5 $(DESTDIR)/$(MANDIR)/man5/
	install -m 644 doc/*.8 $(DESTDIR)/$(MANDIR)/man8/
	install -D -m 644 src/netplan-wpa@.service $(DESTDIR)/$(SYSTEMD_UNIT_DIR)/netplan-wpa@.service
	install -T -D -m 644 netplan.completions $(DESTDIR)/$(BASH_COMPLETIONS_DIR)/netplan

%.html: %.md
	pandoc -s --toc -o $@ $<

doc/netplan.5: doc/manpage-header.md doc/netplan.md doc/manpage-footer.md
	pandoc -s -o $@ $^

%.8: %.md
	pandoc -s -o $@ $^

.PHONY: clean
