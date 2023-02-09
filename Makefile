.PHONY: clean default check linting pre-coverage

DESTDIR ?= ../tmproot

default: _build
	meson compile -C _build

_build:
	meson setup _build --prefix=/usr

_build-cov:
	meson setup _build-cov --prefix=/usr -Db_coverage=true

clean:
	rm -f netplan/_features.py src/_features.h src/_features.h.gch
	rm -f generate doc/*.html doc/*.[1-9]
	rm -f *.o *.so*
	rm -f netplan-dbus dbus/*.service
	rm -f *.gcda *.gcno generate.info
	rm -f tests/ctests/*.gcda tests/ctests/*.gcno
	rm -rf test-coverage .coverage coverage.xml
	find . | grep -E "(__pycache__|\.pyc)" | xargs rm -rf
	rm -rf build
	rm -rf _build
	rm -rf _build-cov
	rm -rf _leakcheckbuild
	rm -rf tmproot

check: default
	meson test -C _build --verbose

linting: _build
	meson test -C _build --verbose linting
	meson test -C _build --verbose codestyle

pre-coverage: _build-cov
	meson compile -C _build-cov

check-coverage: pre-coverage
	meson test -C _build-cov

install: default
	meson install -C _build --destdir $(DESTDIR)

