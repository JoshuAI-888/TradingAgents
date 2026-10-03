# Release CI coverage and clean-runtime check

Latest update: [required lint resolution and complete local regressions](lint-release-check.md). The failure counts below are the initial audit, not the final candidate status.

3 October 2026. The existing GitHub workflow's `pytest -q` follows root `testpaths = ["tests"]`. It does not collect the portal/worker suites, and no existing step ran the JavaScript Desk contracts. Passing that workflow could therefore miss screener regressions.

Added a separate `portal-mvp` job on Python 3.12 (deployment major/minor) and Node 22. It installs the project plus declared portal/worker requirements, pytest and httpx, explicitly runs `web/api/tests web/worker/tests`, then both screener/Desk UI contract files. Existing root, smoke-install and strict lint jobs remain intact.

Built a clean disposable Python 3.12.13 virtual environment from those dependencies. Initial collection exposed missing engine installation (`langchain_core`); the final job now installs the project as the Render worker does. Final local clean-runtime result: **787 tests pass in 19.97 seconds**. JavaScript contracts: **186 pass**. Workflow YAML parses; `git diff --check` passes. These are local equivalents, not GitHub-hosted Linux or deployment acceptance.

Required lint was also actually inspected, rather than inferred from regression tests. The initial candidate scan reports 1,687 findings; an isolated snapshot of committed HEAD `3d150c2` reports 645. Most are layout/import rules, with additional fixture/import and correctness findings. Corrected the missing `threading` import in the worker Runner protocol annotation. The full lint gate still fails and has not been waived, skipped or described as green. No broad automatic cleanup was performed in this checkpoint. [Audit snapshot](ci-gate-audit.json) records the initial counts and scope.

GitHub access confirms the candidate branch exists remotely and no open repository PR was returned. No new PR, push, merge or deploy occurred while the candidate's lint and live-data gates remain unresolved. Next release work includes resolving required lint safely, freezing a tested review commit, live US/HK classification/preset qualification and target-platform cutover. Production data access remains subject to the specifically requested consent; this CI change does not bypass it.
