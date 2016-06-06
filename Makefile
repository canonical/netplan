BUILDFLAGS = \
	-std=c99 \
	-Wall \
	-Werror=incompatible-pointer-types \
	$(NULL)

default: ubuntu-network-emit

src/parse.c: src/parse.h

ubuntu-network-emit: src/emit.c src/parse.c
	$(CC) $(BUILDFLAGS) $(CFLAGS) -o $@ $^ `pkg-config --cflags --libs glib-2.0 yaml-0.1`

clean:
	rm -f ubuntu-network-emit

.PHONY: clean
