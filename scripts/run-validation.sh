#!/bin/bash
docker run --rm \
  --network ad_campaign_budget_pacer_pacer-network \
  -v $(pwd)/scripts:/scripts \
  -e IN_DOCKER=1 \
  python:3.11-slim \
  bash -c "pip install requests && python /scripts/validate-running-system.py"