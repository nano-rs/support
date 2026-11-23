# SPDX-License-Identifier: AGPL-3.0-or-later
PYTHON ?= python3

.PHONY: test test-docker lint sync fixtures

test:            ## unit tests (no Docker)
	$(PYTHON) -m unittest discover -s tests -v

test-docker:     ## also load the sample bundle into a throwaway ClickHouse
	SUPPORT_TEST_DOCKER=1 $(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m ruff check bin/support tests

sync:            ## copy bin/support into each skill's scripts/
	cp bin/support skills/nano-support-collect/scripts/support
	cp bin/support skills/nano-support-investigate/scripts/support

fixtures:        ## rebuild tests/fixtures/sample-bundle
	$(PYTHON) tests/fixtures/make_sample_bundle.py
