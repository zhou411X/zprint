.PHONY: build test install deb

build:
	/usr/bin/python3 -m compileall -q zprint_app install.py build_deb.py

test: build
	GSETTINGS_BACKEND=memory GDK_BACKEND=x11 xvfb-run -a /usr/bin/python3 -m unittest discover -s tests -v

install: build
	sh install.sh

deb: build
	sh build_deb.sh
