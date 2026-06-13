.PHONY: help install db pipeline generate load clean rfm model export dashboard real reset

help:
	@echo "make install    - pip install requirements"
	@echo "make db         - create the analytics role + instacart database"
	@echo "make pipeline   - run the full pipeline (synthetic data)"
	@echo "make real       - run the pipeline on real CSVs in data/raw (no generate)"
	@echo "make dashboard  - rebuild dashboard/preview.html from extracts"
	@echo "make <stage>    - run a single stage: generate|load|clean|rfm|model|export"

install:
	pip install -r requirements.txt

db:
	createuser analytics --pwprompt --superuser || true
	createdb instacart -O analytics || true

pipeline:
	python run_pipeline.py

real:
	python run_pipeline.py --no-generate

generate load clean rfm model export:
	python run_pipeline.py --only $@

dashboard:
	python dashboard/build_preview.py
