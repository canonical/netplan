default: ubuntu-network-emit

ubuntu-network-emit: src/emit.c
	$(CC) $(CFLAGS) -Wall -std=c99 -o $@ src/emit.c `pkg-config --cflags --libs glib-2.0 yaml-0.1`

clean:
	rm -f ubuntu-network-emit

.PHONY: clean
