SKILL_DIR ?= $(HOME)/.claude/skills/workflowwright
PY        ?= python3
SPEC      ?= skill/assets/example-spec.json

.PHONY: help test example scaffold install package site site-check clean
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

install: ## Copy the skill into ~/.claude/skills/
	@mkdir -p $(SKILL_DIR)
	@cp -r skill/. $(SKILL_DIR)/
	@echo "installed -> $(SKILL_DIR)"

package: ## Build a distributable .skill archive
	@rm -rf build/pkg && mkdir -p build/pkg/workflowwright
	@cp -r skill/. build/pkg/workflowwright/
	@cd build/pkg && zip -qr ../workflowwright.skill workflowwright \
		-x '*__pycache__*' '*.pyc'
	@echo "built -> build/workflowwright.skill"

clean:
	@rm -rf build examples/*.html examples/*.mermaid examples/*-design.md
	@find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
