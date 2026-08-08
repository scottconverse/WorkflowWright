SKILL_DIR ?= $(HOME)/.claude/skills/workflowwright
PY        ?= python3
SPEC      ?= skill/assets/example-spec.json

.PHONY: help test example scaffold validate install uninstall package site site-check clean
help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

test: ## Run the suite (no network, credentials, or token spend)
	cd tests && $(PY) -m unittest discover -s . -p 'test_*.py' -v

example: ## Render the bundled example spec into examples/
	$(PY) skill/scripts/render_workflow.py $(SPEC) --out examples

scaffold: ## Generate a runnable workflow package from SPEC into build/
	$(PY) skill/scripts/scaffold_workflow.py $(SPEC) --out build/workflow

# Deliberately does not depend on `example`: re-rendering without Playwright
# replaces the committed artifact's inline SVG with a CDN fallback, and the
# page embeds that diagram directly. Refresh the example explicitly instead.
site: ## Rebuild the GitHub Pages landing page from the rendered example
	$(PY) docs/build_site.py

site-check: ## Fail if docs/index.html is stale relative to the example artifact
	$(PY) docs/build_site.py --check

validate: ## Check the plugin and marketplace manifests with Claude Code's validator
	claude plugin validate ./skill
	claude plugin validate .

install: ## Copy the skill into ~/.claude/skills/
	@mkdir -p $(SKILL_DIR)
	@cp -r skill/. $(SKILL_DIR)/
	@echo "installed -> $(SKILL_DIR)"

uninstall: ## Remove the copy that `install` put in ~/.claude/skills/
	@rm -rf $(SKILL_DIR)
	@echo "removed -> $(SKILL_DIR)"
	@echo "note: this removes only the local copy. A plugin install is removed with"
	@echo "      /plugin uninstall, and an account skill in its own settings."

package: ## Build workflowwright.zip for a claude.ai account upload
	$(PY) scripts/build_package.py

clean:
	@rm -rf build examples/*.html examples/*.mermaid examples/*-design.md
	@find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
