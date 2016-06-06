BUILDFLAGS = \
	-std=c99 \
	-Wall \
	-Werror=incompatible-pointer-types \
	-Werror=implicit-function-declaration \
	-Werror=format \
	$(NULL)

default: ubuntu-network-emit

src/parse.c: src/parse.h
src/util.c: src/util.h
src/networkd.c: src/networkd.h

ubuntu-network-emit: src/emit.c src/parse.c src/util.c src/networkd.c
	$(CC) $(BUILDFLAGS) $(CFLAGS) -o $@ $^ `pkg-config --cflags --libs glib-2.0 yaml-0.1`

clean:
	rm -f ubuntu-network-emit

.PHONY: clean
