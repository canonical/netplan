BUILDFLAGS = \
	-std=c99 \
	-D_XOPEN_SOURCE=500 \
	-Wall \
	-Werror=incompatible-pointer-types \
	-Werror=implicit-function-declaration \
	-Werror=format \
	$(NULL)

SYSTEMD_GENERATOR_DIR=$(shell pkg-config --variable=systemdsystemgeneratordir systemd)

default: generate doc/netplan.5 doc/netplan.html

generate: src/generate.[hc] src/parse.[hc] src/util.[hc] src/networkd.[hc] src/nm.[hc]
	$(CC) $(BUILDFLAGS) $(CFLAGS) -o $@ $(filter %.c, $^) `pkg-config --cflags --libs glib-2.0 yaml-0.1`

clean:
	rm -f generate doc/*.html doc/*.[1-9]
	rm -rf test-coverage

check: default
	tests/generate.py
	tests/cli.py
	$(shell which pyflakes3 || echo true) src/netplan tests/generate.py tests/integration.py tests/cli.py
	$(shell which pycodestyle || which pep8 || echo true) --max-line-length=130 src/netplan tests/generate.py tests/integration.py tests/cli.py

coverage:
	$(MAKE) CFLAGS="-g -O0 --coverage" clean check
	lcov --directory . --capture -o generate.info
	lcov --remove generate.info "/usr*" -o generate.info
	genhtml -o test-coverage -t "generate test coverage" generate.info
	@rm *.gcda *.gcno generate.info generate
	@echo "generated report: file://$(CURDIR)/test-coverage/index.html"

install: default
	mkdir -p $(DESTDIR)/usr/sbin $(DESTDIR)/lib/netplan $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR)
	mkdir -p $(DESTDIR)/usr/share/man/man5 $(DESTDIR)/usr/share/doc/netplan
	install -m 755 generate $(DESTDIR)/lib/netplan/
	install -m 755 src/netplan $(DESTDIR)/usr/sbin/
	ln -s /lib/netplan/generate $(DESTDIR)/$(SYSTEMD_GENERATOR_DIR)/netplan
	install -m 644 doc/*.html $(DESTDIR)/usr/share/doc/netplan/
	install -m 644 doc/*.5 $(DESTDIR)/usr/share/man/man5/

%.html: %.md
	pandoc -s --toc -o $@ $<

%.5: %.md
	pandoc -s -o $@ $<

.PHONY: clean
