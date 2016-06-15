BUILDFLAGS = \
	-std=c99 \
	-Wall \
	-Werror=incompatible-pointer-types \
	-Werror=implicit-function-declaration \
	-Werror=format \
	$(NULL)

default: ubuntu-network-generate

src/parse.c: src/parse.h
src/util.c: src/util.h
src/networkd.c: src/networkd.h
src/nm.c: src/nm.h

ubuntu-network-generate: src/generate.c src/parse.c src/util.c src/networkd.c src/nm.c
	$(CC) $(BUILDFLAGS) $(CFLAGS) -o $@ $^ `pkg-config --cflags --libs glib-2.0 yaml-0.1`

clean:
	rm -f ubuntu-network-generate

check: default
	tests/generate.py
	$(shell which pyflakes3 || echo true) tests/generate.py tests/integration.py
	$(shell which pep8 || echo true) --max-line-length=130 tests/generate.py tests/integration.py

install: default
	mkdir -p $(DESTDIR)/usr/lib/ubuntu-network
	install -m 755 ubuntu-network-generate $(DESTDIR)/usr/lib/ubuntu-network/

.PHONY: clean
