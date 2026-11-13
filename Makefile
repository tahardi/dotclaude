# https://clarkgrubb.com/makefile-style-guide
MAKEFLAGS += --warn-undefined-variables
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := pre-pr
.DELETE_ON_ERROR:
.SUFFIXES:

include security.mk

.PHONY: pre-pr
pre-pr: \
	shellcheck \
	test-python \
	test-scripts \
	test-install \
	syntax \
	security

.PHONY: shellcheck
shellcheck:
	@git ls-files -z '*.sh' | xargs -0 -r shellcheck

.PHONY: test-python
test-python:
	@for dir in skills/*/scripts; do \
		if compgen -G "$$dir/test_*.py" >/dev/null; then \
			python3 -m unittest discover -s $$dir -p 'test_*.py'; \
		fi; \
	done

.PHONY: test-scripts
test-scripts:
	@python3 -m unittest discover -s scripts -p 'test_*.py'

.PHONY: test-install
test-install:
	@tests/install_test.sh

.PHONY: syntax
syntax:
	@git ls-files -z '*.json' | xargs -0 -r -n1 python3 -m json.tool >/dev/null
	@git ls-files -z '*.yaml' '*.yml' | xargs \
		-0 \
		-r \
		python3 \
		-c 'import sys, yaml; [yaml.safe_load(open(p)) for p in sys.argv[1:]]'
