# Author: Tishneet
.PHONY: up down test test-integration integration-up demo bedrock-smoke aws-build build-WorkflowFunction
up:
	bash scripts/dev.sh up --build
down:
	bash scripts/dev.sh down
test:
	bash scripts/dev.sh --profile test run --build --rm test
test-integration:
	bash scripts/dev.sh --profile integration-test run --build --rm test-integration
integration-up:
	bash scripts/dev.sh --profile integration up --build
demo:
	bash scripts/dev.sh exec api python -m scripts.demo
aws-build:
	bash scripts/aws_build.sh
bedrock-smoke:
	bash scripts/bedrock_smoke.sh
build-WorkflowFunction:
	python3 scripts/build_lambda.py
