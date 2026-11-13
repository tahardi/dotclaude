gitleaks_version = v8.30.1
actionlint_version = v1.7.12
zizmor_version = 1.31.1
osv_scanner_version = v2.7.0
govulncheck_version = v1.9.0

security_results = security-results

online = curl --silent --head --max-time 5 --output /dev/null $(1) \
	|| { [ -z "$${CI:-}" ] || { echo "error: cannot reach $(1) for $(2)"; exit 1; }; \
	echo "warning: skipping $(2): cannot reach $(1)"; exit 0; }

security_deps = security-deps-osv-scanner
ifneq ($(wildcard go.mod),)
security_deps += security-deps-govulncheck
endif
ifneq ($(wildcard package-lock.json),)
security_deps += security-deps-npm-audit
endif

.PHONY: security
security: \
	security-secrets \
	security-workflows \
	security-pins \
	security-deps

.PHONY: security-secrets
security-secrets:
	@$(call online,https://proxy.golang.org,gitleaks); \
	go run github.com/zricethezav/gitleaks/v8@$(gitleaks_version) git \
		--redact \
		--no-banner \
		.

.PHONY: security-workflows
security-workflows:
	@$(call online,https://proxy.golang.org,actionlint); \
	go run github.com/rhysd/actionlint/cmd/actionlint@$(actionlint_version)
	@$(call online,https://pypi.org,zizmor); \
	uvx zizmor==$(zizmor_version) \
		--offline \
		.

.PHONY: security-pins
security-pins:
ifneq ($(wildcard package.json),)
	@test -f package-lock.json || { echo "error: package.json has no package-lock.json"; exit 1; }
	@python3 -c 'import json, re, sys; \
		d = json.load(open("package.json")); \
		bad = [f"{n}@{v}" for s in ("dependencies", "devDependencies") for n, v in d.get(s, {}).items() \
			if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?", v)]; \
		bad and sys.exit("error: package.json versions are not exact: " + ", ".join(bad))'
endif
ifneq ($(wildcard package-lock.json),)
	@$(call online,https://registry.npmjs.org,npm audit signatures); \
	npm audit signatures
endif
ifneq ($(wildcard Cargo.toml),)
	@test -f Cargo.lock || { echo "error: Cargo.toml has no Cargo.lock"; exit 1; }
endif
ifneq ($(wildcard requirements*.txt),)
	@! grep \
		--extended-regexp \
		--invert-match \
		--with-filename \
		'^[[:space:]]*(#|-|$$)|==' \
		requirements*.txt \
		|| { echo "error: requirements lines above must pin with =="; exit 1; }
endif

.PHONY: security-deps
security-deps: $(security_deps)

$(security_results):
	@mkdir -p $@

.PHONY: security-deps-osv-scanner
security-deps-osv-scanner: | $(security_results)
	@$(call online,https://api.osv.dev,osv-scanner); \
	code=0; \
	go run github.com/google/osv-scanner/v2/cmd/osv-scanner@$(osv_scanner_version) scan source \
		--recursive \
		--allow-no-lockfiles \
		--format json \
		--output-file $(security_results)/osv-scanner.json \
		. \
		|| code=$$?; \
	[ $$code -le 1 ] || echo "warning: osv-scanner failed: exit $$code"; \
	echo "osv-scanner results: $(security_results)/osv-scanner.json"

.PHONY: security-deps-govulncheck
security-deps-govulncheck: | $(security_results)
	@$(call online,https://vuln.go.dev,govulncheck); \
	code=0; \
	go run golang.org/x/vuln/cmd/govulncheck@$(govulncheck_version) \
		-format json \
		./... \
		> $(security_results)/govulncheck.json \
		|| code=$$?; \
	[ $$code -eq 0 ] || echo "warning: govulncheck failed: exit $$code"; \
	echo "govulncheck results: $(security_results)/govulncheck.json"

.PHONY: security-deps-npm-audit
security-deps-npm-audit: | $(security_results)
	@$(call online,https://registry.npmjs.org,npm audit); \
	code=0; \
	npm audit \
		--json \
		> $(security_results)/npm-audit.json \
		|| code=$$?; \
	{ [ $$code -le 1 ] && python3 -c 'import json, sys; sys.exit("error" in json.load(open(sys.argv[1])))' \
		$(security_results)/npm-audit.json; } \
		|| echo "warning: npm audit failed: exit $$code"; \
	echo "npm audit results: $(security_results)/npm-audit.json"
