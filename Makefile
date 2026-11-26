# if Podman is available, prefer using it over docker
# (single-line detection: valid GNU make, and it keeps the file parseable by
# shell linters, which cannot read make's ifeq/else/endif conditionals)
CONTAINER ?= $(shell command -v podman > /dev/null 2>&1 && echo podman || echo docker)

# Image coordinates used by the image-* targets. Override on the command line:
#   make image-push IMAGE_REGISTRY=registry.oci.internal IMAGE_TAG=v1.2.3
IMAGE_REGISTRY ?= ghcr.io/linux-duks
IMAGE_NAME ?= duks-server
IMAGE_TAG ?= latest
IMAGE ?= $(IMAGE_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

# Containerfile of the production image (serves the Flask API and ships the
# static frontend the nginx pod copies out of it).
IMAGE_FILE ?= server/Containerfile.prod
IMAGE_CONTEXT ?= server/

# Kubernetes coordinates used by the chart-*/data-* targets.
HELM ?= helm
KUBECTL ?= kubectl
CHART ?= chart
NAMESPACE ?= duks
RELEASE ?= duks
# Selector for the pod whose /data volume receives ./data (the api pod). It
# relies on the chart's component labels; see chart/templates/_helpers.tpl.
DATA_DIR ?= ./data
# Mount path of the data volume inside the api pod (values: persistence.mountPath).
POD_DATA_PATH ?= /data
API_POD_SELECTOR ?= app.kubernetes.io/name=duks,app.kubernetes.io/component=api

# By default, 'make' will run the 'dev' target
.PHONY: all
all: build-dev dev

##@ Compose (local)

.PHONY: build-dev dev build prod
build-dev: ## Build the development image
	$(CONTAINER)-compose -f dev-compose.yaml build

dev: ## Run the development stack (foreground)
	$(CONTAINER)-compose -f dev-compose.yaml up

build: ## Build the production compose images
	$(CONTAINER)-compose -f compose.yaml build

prod: ## Run the production compose stack (foreground)
	$(CONTAINER)-compose -f compose.yaml up

##@ Image

.PHONY: image-build image-push image-publish
image-build: ## Build the production image as $(IMAGE)
	$(CONTAINER) build -f $(IMAGE_FILE) -t $(IMAGE) $(IMAGE_CONTEXT)

image-push: ## Push $(IMAGE)
	$(CONTAINER) push $(IMAGE)

image-publish: image-build image-push ## Build and push $(IMAGE)

##@ Kubernetes

.PHONY: chart-lint chart-template chart-install chart-uninstall chart-package data-sync
chart-lint: ## Lint the Helm chart
	$(HELM) lint $(CHART)

chart-template: ## Render the chart for the current values (no cluster access)
	$(HELM) template $(RELEASE) $(CHART) --namespace $(NAMESPACE)

chart-install: ## Install/upgrade the release in $(NAMESPACE)
	$(HELM) upgrade --install $(RELEASE) $(CHART) --namespace $(NAMESPACE) --create-namespace

chart-uninstall: ## Remove the release from $(NAMESPACE)
	$(HELM) uninstall $(RELEASE) --namespace $(NAMESPACE)

chart-package: ## Package the chart into a .tgz next to it
	$(HELM) package $(CHART)

data-sync: ## Copy ./data into the running api pod's data volume
	@test -d "$(DATA_DIR)" || { echo "error: $(DATA_DIR) does not exist" >&2; exit 1; }
	$(eval POD := $(shell $(KUBECTL) -n $(NAMESPACE) get pods -l '$(API_POD_SELECTOR)' -o jsonpath='{.items[0].metadata.name}' 2>/dev/null))
	@test -n "$(POD)" || { echo "error: no api pod found in namespace $(NAMESPACE) (selector: $(API_POD_SELECTOR))" >&2; exit 1; }
	@echo "==> copying $(DATA_DIR)/ into $(POD):$(POD_DATA_PATH)"
	tar -C "$(DATA_DIR)" -cf - . | $(KUBECTL) -n $(NAMESPACE) exec -i $(POD) -- tar -C $(POD_DATA_PATH) --strip-components=1 -xf -
	@echo "==> done. $(POD_DATA_PATH) now contains:"
	@$(KUBECTL) -n $(NAMESPACE) exec $(POD) -- ls -1 $(POD_DATA_PATH)

##@ Help

.PHONY: help
help: ## Show this help
	@echo "Usage: make [target]"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)
