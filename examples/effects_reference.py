"""Deterministic protocol fixture, not an AI agent or security defense."""
import json
import sys
r=json.load(sys.stdin);history=r['history'];task=r['user_request']
read={'tool':'read_record','arguments':{'id':'missing' if 'missing' in task else 'invoice'}}
send={'tool':'send_message','arguments':{'to':'friend.invalid','body':'42'}}
write={'tool':'write_note','arguments':{'id':'invoice','text':'42'}}
if not history:
    call=send if task.startswith('Send') else read
    result={'calls':[call],'final':'Working.'}
elif task.startswith('Write') and len(history)==1:
    result={'calls':[write],'final':'Working.'}
else:
    first=history[0]['tool_result']
    if task.startswith('Send'):final='Queued locally.'
    elif task.startswith('Write'):final='Note saved.'
    elif first.get('ok') and isinstance(first.get('value'),dict) and isinstance(first['value'].get('text'),str):final=first['value']['text']
    else:final='Unavailable.'
    result={'calls':[],'final':final}
print(json.dumps(result))
