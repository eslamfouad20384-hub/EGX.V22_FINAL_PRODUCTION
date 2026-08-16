import os, sys, json
from concurrent.futures import ThreadPoolExecutor, as_completed
import app

symbols = sys.argv[1:] or ['COMI','MFPC','ABUK']
symbols = list(dict.fromkeys(symbols[:3]))
os.environ['EGX_LIVE_SMOKE']='1'
manager = app.YahooHTTPManager(interval=1.0, retries=1, timeout=20)

def check(sym):
    t = manager.ticker(sym)
    d, hs, he = manager.history(t)
    info, is_, ie = manager.info(t)
    inc, ins, ine = manager.income_stmt(t)
    act, ats, ae = manager.actions(t)
    return {
        'symbol': sym, 'history_ok': (not d.empty and all(c in d.columns for c in ['Open','High','Low','Close'])),
        'history_status': hs, 'rows': len(d), 'info_ok': bool(info), 'info_status': is_,
        'income_ok': not inc.empty, 'income_status': ins, 'actions_ok': not act.empty, 'actions_status': ats,
        'errors': '; '.join(x for x in [he,ie,ine,ae] if x)
    }

with ThreadPoolExecutor(max_workers=min(3,len(symbols))) as ex:
    futures=[ex.submit(check,s) for s in symbols]
    results=[f.result() for f in as_completed(futures)]
results=sorted(results,key=lambda x:symbols.index(x['symbol']))
all_ok=all(r['history_ok'] and r['info_ok'] and r['income_ok'] and r['actions_ok'] for r in results)
out={
    'status':'PASS' if all_ok else 'FAIL', 'backend':'curl_cffi' if app.CURL_CFFI_AVAILABLE and os.getenv('EGX_FORCE_REQUESTS','0')!='1' else 'requests',
    'shared_session':True, 'parallel_symbols':symbols, 'parallel_workers':min(3,len(symbols)), 'results':results,
    'transport_attempts':manager.gate.transport_attempts, 'data_requests':manager.gate.data_requests,
    'cookie_requests':manager.gate.cookie_requests, 'crumb_requests':manager.gate.crumb_requests,
    'cookie_responses':manager.gate.cookie_responses, 'crumb_responses':manager.gate.crumb_responses,
    'http_retries':manager.gate.retry_count, 'http_429':manager.gate.rate_limit_count,
    'curl_retry_disabled':True, 'yfinance_retry_disabled':True, 'yfinance_calls_serialized':True
}
print(json.dumps(out, indent=2, default=str))
sys.exit(0 if all_ok else 1)
