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

# Mirrors rather than copies. `cp -r skill/. $(SKILL_DIR)/` merges: it overwrites
# the files it has and leaves behind any the new version dropped, so an upgrade
# produced a mixture of two releases. Same reason `uninstall` is a script.
install: ## Install the skill into ~/.claude/skills/, replacing any older version
	$(PY) scripts/install.py $(SKILL_DIR)

install-all: ## Update every host copy on this machine (Claude Code, Codex, Antigravity)
	$(PY) scripts/install.py --all

# Delegates rather than running `rm -rf $(SKILL_DIR)` here: the directory is a
# variable, so the recipe is only ever as safe as what the variable holds, and
# make is absent on some machines this repo is developed on -- which would put
# the guard out of reach of the tests exactly where it matters most.
uninstall: ## Remove the copy that `install` put in ~/.claude/skills/
	$(PY) scripts/uninstall.py $(SKILL_DIR)

package: ## Build workflowwright.zip for a claude.ai account upload
	$(PY) scripts/build_package.py

clean:
	@rm -rf build examples/*.html examples/*.mermaid examples/*-design.md
	@find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
