# if Podman is available, prefer using it over docker
ifeq ($(shell command -v podman 2> /dev/null),)
    CONTAINER=docker
else
    CONTAINER=podman
endif

# By default, 'make' will run the 'dev' target
.PHONY: all
all: build-dev dev

build-dev:
	$(CONTAINER)-compose -f dev-compose.yaml build

build:
	$(CONTAINER)-compose -f compose.yaml build

dev:
	$(CONTAINER)-compose -f dev-compose.yaml up

prod:
	$(CONTAINER)-compose -f compose.yaml up
