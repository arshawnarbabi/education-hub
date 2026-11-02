PYTHON ?= python3
VENV := .venv

$(VENV)/.installed: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet -r requirements.txt
	touch $@

.PHONY: demo test prove clean
demo: $(VENV)/.installed
	$(VENV)/bin/python demo.py

test: $(VENV)/.installed
	$(VENV)/bin/python -m unittest discover -s tests -t .

prove: $(VENV)/.installed
	$(VENV)/bin/python tools/mutation_check.py

clean:
	rm -rf $(VENV)
