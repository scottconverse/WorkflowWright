SKILL_DIR ?= $(HOME)/.claude/skills/agent-workflow-architect
PY        ?= python3
SPEC      ?= skill/assets/example-spec.json

.PHONY: help test example scaffold install package clean
help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

test: ## Run the suite (no network, credentials, or token spend)
	cd tests && $(PY) -m unittest discover -s . -p 'test_*.py' -v

example: ## Render the bundled example spec into examples/
	$(PY) skill/scripts/render_workflow.py $(SPEC) --out examples

scaffold: ## Generate a runnable workflow package from SPEC into build/
	$(PY) skill/scripts/scaffold_workflow.py $(SPEC) --out build/workflow

install: ## Copy the skill into ~/.claude/skills/
	@mkdir -p $(SKILL_DIR)
	@cp -r skill/. $(SKILL_DIR)/
	@echo "installed -> $(SKILL_DIR)"

package: ## Build a distributable .skill archive
	@rm -rf build/pkg && mkdir -p build/pkg/agent-workflow-architect
	@cp -r skill/. build/pkg/agent-workflow-architect/
	@cd build/pkg && zip -qr ../agent-workflow-architect.skill agent-workflow-architect \
		-x '*__pycache__*' '*.pyc'
	@echo "built -> build/agent-workflow-architect.skill"

clean:
	@rm -rf build examples/*.html examples/*.mermaid examples/*-design.md
	@find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
