BUILDFLAGS = \
	-std=c99 \
	-D_XOPEN_SOURCE=500 \
	-Wall \
	-Werror \
	$(NULL)

SYSTEMD_GENERATOR_DIR=$(shell pkg-config --variable=systemdsystemgeneratordir systemd)

PYCODE = netplan/ $(wildcard src/*.py) $(wildcard tests/*.py)

default: generate doc/netplan.5 doc/netplan.html

generate: src/generate.[hc] src/parse.[hc] src/util.[hc] src/networkd.[hc] src/nm.[hc]
	$(CC) $(BUILDFLAGS) $(CFLAGS) -o $@ $(filter %.c, $^) `pkg-config --cflags --libs glib-2.0 gio-2.0 yaml-0.1 uuid`

clean:
	rm -f generate doc/*.html doc/*.[1-9]
	rm -f *.gcda *.gcno generate.info
	rm -rf test-coverage .coverage

check: default linting
	tests/generate.py
	tests/cli.py

linting:
	$(shell which pyflakes3 || echo true) $(PYCODE)
	$(shell which pycodestyle || which pep8 || echo true) --max-line-length=130 $(PYCODE)

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
	mkdir -p $(DESTDIR)/usr/sbin $(DESTDIR)/lib/netplan $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR)
	mkdir -p $(DESTDIR)/usr/share/man/man5 $(DESTDIR)/usr/share/doc/netplan
	install -m 755 generate $(DESTDIR)/lib/netplan/
	install -m 755 src/netplan $(DESTDIR)/usr/sbin/
	ln -s /lib/netplan/generate $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR)/netplan
	install -m 644 doc/*.html $(DESTDIR)/usr/share/doc/netplan/
	install -m 644 doc/*.5 $(DESTDIR)/usr/share/man/man5/
	install -D -m 644 src/netplan-wpa@.service $(DESTDIR)/`pkg-config --variable=systemdsystemunitdir systemd`/netplan-wpa@.service

%.html: %.md
	pandoc -s --toc -o $@ $<

doc/netplan.5: doc/netplan.md
	pandoc -s -o $@ $<
	# add NAME section (looks ugly in HTML, thus only do it here)
	sed -i '/^.TH/ a\.SH NAME\nnetplan \\- YAML network configuration abstraction for various backends' $@

.PHONY: clean
