PYTHON ?= python3

.PHONY: check test denylist proofs demo docker wheel images screenshots dashboard-sample

## check: everything CI runs (tests, denylist, proofs, docker build + smoke test)
check: test proofs docker

## test: the Python suite, including the denylist scan and the demo end to end
test:
	PYTHONPATH=src:tests $(PYTHON) -m unittest discover -s tests -t tests -v

## denylist: only the denylist scan
denylist:
	PYTHONPATH=src:tests $(PYTHON) -m unittest -v test_denylist

## proofs: build the Lean project and check the axioms of the main theorems
proofs:
	cd proofs && lake build
	cd proofs && lake env lean CheckAxioms.lean | tee .lake/axioms.txt
	@! grep -E "sorryAx|Classical.choice" proofs/.lake/axioms.txt

## demo: run the local demo and print the summary table
demo:
	$(PYTHON) demo/run_demo.py

## docker: build the container image and smoke test it (what CI's "container" job runs)
docker:
	docker build -t svrf .
	docker run --rm --entrypoint svrf svrf --version

## wheel: build the sdist/wheel (python -m build) and smoke test installing it in a fresh venv
wheel:
	rm -rf dist .venv-wheel-check
	$(PYTHON) -m venv .venv-wheel-check
	.venv-wheel-check/bin/pip install --quiet --upgrade pip build
	.venv-wheel-check/bin/python -m build
	.venv-wheel-check/bin/pip install --quiet dist/svrf-*.whl
	.venv-wheel-check/bin/svrf --version
	rm -rf .venv-wheel-check

## images: regenerate docs/img/*.svg from docs/BENCHMARK.md and docs/demo.cast (a test checks they are fresh)
images:
	$(PYTHON) demo/readme_images.py

## screenshots: docs/img/dashboard*.png from the sample receipts (needs playwright + chromium locally)
screenshots:
	$(PYTHON) demo/screenshot_dashboard.py

## dashboard-sample: build the dashboard from the bundled anonymized receipts into build/dashboard/
dashboard-sample:
	PYTHONPATH=src $(PYTHON) -m svrf dashboard --receipts demo/sample-receipts --out build/dashboard --title "SVRF merge train (sample data)"
