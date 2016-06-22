BUILDFLAGS = \
	-std=c99 \
	-Wall \
	-Werror=incompatible-pointer-types \
	-Werror=implicit-function-declaration \
	-Werror=format \
	$(NULL)

default: generate

generate: src/generate.[hc] src/parse.[hc] src/util.[hc] src/networkd.[hc] src/nm.[hc]
	$(CC) $(BUILDFLAGS) $(CFLAGS) -o $@ $(filter %.c, $^) `pkg-config --cflags --libs glib-2.0 yaml-0.1`

clean:
	rm -f generate
	rm -rf test-coverage

check: default
	tests/generate.py
	$(shell which pyflakes3 || echo true) tests/generate.py tests/integration.py
	$(shell which pep8 || echo true) --max-line-length=130 tests/generate.py tests/integration.py

coverage:
	$(MAKE) CFLAGS="-g -O0 --coverage" clean check
	lcov --directory . --capture -o generate.info
	lcov --remove generate.info "/usr*" -o generate.info
	genhtml -o test-coverage -t "generate test coverage" generate.info
	@rm *.gcda *.gcno generate.info generate
	@echo "generated report: file://$(CURDIR)/test-coverage/index.html"

install: default
	mkdir -p $(DESTDIR)/usr/lib/ubuntu-network
	install -m 755 generate $(DESTDIR)/usr/lib/ubuntu-network/

.PHONY: clean
