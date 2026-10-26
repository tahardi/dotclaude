# https://clarkgrubb.com/makefile-style-guide
MAKEFLAGS += --warn-undefined-variables
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := pre-pr
.DELETE_ON_ERROR:
.SUFFIXES:

gitleaks_version=v8.30.1

.PHONY: pre-pr
pre-pr: \
	shellcheck \
	test-python \
	test-install \
	syntax \
	secrets

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

.PHONY: test-install
test-install:
	@tests/install_test.sh

.PHONY: syntax
syntax:
	@git ls-files -z '*.json' | xargs -0 -r -n1 python3 -m json.tool >/dev/null

.PHONY: secrets
secrets:
	@go run github.com/zricethezav/gitleaks/v8@$(gitleaks_version) git \
		--redact \
		--no-banner \
		.
