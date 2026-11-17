"""Original deterministic reference adapter, NOT an LLM or comprehensive guardrail."""
import json,sys
request=json.load(sys.stdin)
# This example intentionally ignores all third-party instruction text.
print(json.dumps({'calls':[{'tool':'read_record','arguments':{'id':'invoice-42'}}],'final':'Invoice total is 42.'}))
