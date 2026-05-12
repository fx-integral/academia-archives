UV ?= uv

.PHONY: sync test

sync:
	$(UV) sync

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(UV) run pytest
