PYTHON ?= python3

.PHONY: check test denylist proofs demo docker

## check: everything CI runs (tests, denylist, proofs)
check: test proofs

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

## docker: build the container image
docker:
	docker build -t svrf .
