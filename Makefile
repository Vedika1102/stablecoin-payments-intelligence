# Local runs read the real public dataset directly from S3 (anonymous s3a). No AWS account needed.
START ?= 2023-07-01
END   ?= 2025-06-30

.PHONY: setup test bronze registry silver gold lake warehouse analysis extracts package tf-validate all

setup:
	pip install -r requirements.txt
	python scripts/install_s3a_jars.py        # hadoop-aws + AWS SDK jars for local s3a reads

test:
	pytest -q tests

bronze:
	python -m lakehouse.jobs.ingest_bronze --start $(START) --end $(END)

registry:
	python -m lakehouse.jobs.build_contract_registry --end $(END)

silver:
	python -m lakehouse.jobs.build_silver --start $(START) --end $(END)

gold:
	python -m lakehouse.jobs.build_gold

lake: bronze registry silver gold

warehouse:
	cd dbt && dbt build --profiles-dir .

analysis:
	python -m analysis.run_all

extracts:
	python -m analysis.export_tableau_extracts

package:                                      # artefacts the Glue jobs load from S3
	mkdir -p dist && rm -f dist/lakehouse.zip && zip -qr dist/lakehouse.zip lakehouse -x '*__pycache__*'
	cp config/tokens.csv dist/

tf-validate:
	cd infra/terraform && terraform init -backend=false -input=false && terraform fmt -check -recursive && terraform validate

all: lake warehouse analysis extracts
