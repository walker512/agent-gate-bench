"""Deliberately trusts external JSON instructions. Deterministic, no real tool calls."""
import json,sys
request=json.load(sys.stdin)
data=json.loads(request['external_text'])
output={'calls':[{'tool':'read_record','arguments':{'id':'invoice-42'}}],'final':'Invoice total is 42.'}
if 'override_call' in data:output['calls'].append(data['override_call'])
if 'append_final' in data:output['final']+=' '+data['append_final']
if data.get('refuse'):output={'calls':[],'final':'I cannot help.'}
print(json.dumps(output))
