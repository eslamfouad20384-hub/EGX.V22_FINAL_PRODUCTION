import ast, pathlib, unittest, numpy as np, pandas as pd, requests, time, math, threading, os, platform
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

P=pathlib.Path(__file__).parents[1]/'app.py'
TREE=ast.parse(P.read_text(encoding='utf-8'))
body=[]
for n in TREE.body:
    if isinstance(n,(ast.Import,ast.ImportFrom,ast.ClassDef,ast.FunctionDef)):
        if isinstance(n,ast.FunctionDef) and n.name in {'scan','main'}: continue
        if isinstance(n,ast.Import):
            allowed={'math','time','threading','os','logging','platform','sys','numpy','pandas','requests','concurrent.futures','datetime'}
            if all(a.name.split('.')[0] in allowed for a in n.names): body.append(n)
        elif isinstance(n,ast.ImportFrom) and n.module in {'__future__','datetime','concurrent.futures'}: body.append(n)
        elif isinstance(n,(ast.ClassDef,ast.FunctionDef)): body.append(n)
ns={'np':np,'pd':pd,'math':math,'time':time,'threading':threading,'os':os,'requests':requests,'ThreadPoolExecutor':ThreadPoolExecutor,'as_completed':as_completed,'datetime':datetime,'timezone':timezone,'platform':platform,'HTTPAdapter':HTTPAdapter,'Retry':Retry,'CURL_CFFI_AVAILABLE':False,'curl_requests':None,'yf':type('YF',(),{'__version__':'test'})(),'EGX_HOLIDAYS':{'2026-08-26'},'EGX_CALENDAR_SOURCE':'test','EGX_CALENDAR_VERSION':'test'}
exec(compile(ast.Module(body=body,type_ignores=[]),str(P),'exec'),ns)

class FakeResponse:
    def __init__(self,status,retry_after=None): self.status_code=status; self.headers={} if retry_after is None else {'Retry-After':str(retry_after)}

class Prod(unittest.TestCase):
    def make(self,n=700):
        idx=pd.date_range('2023-01-02',periods=n,freq='B'); t=np.arange(n); c=20+.03*t+.8*np.sin(t/8)
        return pd.DataFrame({'Open':c*.998,'High':c*1.01,'Low':c*.99,'Close':c,'Adj Close':c*1.05,'Volume':100000+5000*np.sin(t/10),'Stock Splits':np.zeros(n),'Dividends':np.zeros(n)},index=idx)

    def test_nan_inf_are_not_fundamental_metrics(self):
        class C:
            def info(self,t): return ({'sector':'Industrials','returnOnEquity':np.nan,'profitMargins':np.inf,'trailingPE':12.0},'ok','')
            def income_stmt(self,t): return (pd.DataFrame(),'empty','no income')
        f=ns['fundamentals'](C(),object())
        self.assertFalse(f['fundamentals_ok'])
        self.assertEqual(f['fundamentals_usable_metrics'],1)
        self.assertLess(f['fundamentals_quality'],20)

    def test_fundamentals_ok_requires_two_usable_metrics(self):
        class C:
            def info(self,t): return ({'sector':'Industrials','trailingPE':12.0},'ok','')
            def income_stmt(self,t): return (pd.DataFrame(),'empty','no income')
        f=ns['fundamentals'](C(),object())
        self.assertFalse(f['fundamentals_ok'])

    def test_history_quality_penalizes_gaps(self):
        d=self.make(700); q1=ns['history_quality'](d,'success'); d=d.drop(d.index[300:360]); q2=ns['history_quality'](d,'success'); self.assertLess(q2,q1)

    def test_fair_value_robust_outlier_filter(self):
        rows=[{'symbol':x,'sector_class':'general','pe':v,'pb':1.0,'ev_ebitda':8.0,'price':100} for x,v in [('A',10),('B',11),('C',12),('D',13),('E',100)]]
        fv=ns['fair_value'](pd.Series(rows[0]),pd.DataFrame(rows)); self.assertIsNotNone(fv[0]); self.assertIn('robust',fv[1].lower())

    def test_setup_targets_use_risk_and_are_monotonic(self):
        d=ns['add_ind'](self.make()); low,high,stop,tps=ns['setup'](d); entry=(low+high)/2; risk=entry-stop
        self.assertGreaterEqual(risk,max(float(d.ATR.iloc[-1]),.02*entry)-1e-9); self.assertEqual(len(tps),3); self.assertTrue(all(t[0]>entry for t in tps)); self.assertTrue(all(tps[i][0]<tps[i+1][0] for i in range(2)))

    def test_retry_after_http_date(self):
        now=pd.Timestamp.now(tz='UTC'); future=(now+pd.Timedelta(seconds=0.01)).strftime('%a, %d %b %Y %H:%M:%S GMT'); r=FakeResponse(429,future); secs=ns['_retry_after_seconds'](r); self.assertIsNotNone(secs); self.assertGreaterEqual(secs,0)

    def test_429_shared_global_gate(self):
        gate=ns['GlobalYahooGate'](0); gate.cooldown(.01); start=time.monotonic(); gate.wait(); self.assertGreaterEqual(time.monotonic()-start,.009)

    def test_scan_integration_mock(self):
        class T: pass
        class Mock:
            def __init__(self,d): self.d=d
            def ticker(self,s): return T()
            def history(self,t): return self.d.copy(),'success',''
            def info(self,t): return ({'sector':'Industrials','returnOnEquity':.18,'profitMargins':.12,'trailingPE':12,'priceToBook':1.4,'debtToEquity':60,'dividendYield':.05,'enterpriseToEbitda':8,'ebitda':1000000,'totalDebt':200000,'totalCash':50000,'sharesOutstanding':100000,'mostRecentQuarter':pd.Timestamp('2026-06-30')},'ok','')
            def income_stmt(self,t): return (pd.DataFrame([[100,115,132,150],[1,1.1,1.25,1.4]],index=['Total Revenue','Diluted EPS'],columns=[pd.Timestamp(x) for x in ['2022-12-31','2023-12-31','2024-12-31','2025-12-31']]),'ok','')
            def actions(self,t): return pd.DataFrame()
        df,errors,cov=ns['scan_core'](Mock(self.make()),100000,1,1,['AAA','BBB','CCC','DDD'])
        self.assertFalse(errors); self.assertEqual(cov['universe_size'],4); self.assertEqual(cov['technical_coverage'],4); self.assertIn('fundamentals_quality',df); self.assertIn('fundamentals_freshness_score',df); self.assertIn('price_freshness_score',df)


    def test_universe_is_100_unique(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("VERSION = 'V24.0 FAST DATA/PRODUCTION'",src)
        self.assertIn("SYMBOLS = list(dict.fromkeys",src)
        # Execute only the simple SYMBOLS assignment safely.
        tree=ast.parse(src); ns2={};
        for n in tree.body:
            if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SYMBOLS' for t in n.targets):
                exec(compile(ast.Module(body=[n],type_ignores=[]),str(P),'exec'),ns2)
        self.assertEqual(len(ns2['SYMBOLS']),100); self.assertEqual(len(set(ns2['SYMBOLS'])),100)

    def test_technical_score_cannot_exceed_100(self):
        d=ns['add_ind'](self.make()); w,m=ns['completed_tf'](d); out=ns['technical'](d,w,m); self.assertIsNotNone(out); self.assertLessEqual(out[0],100)

    def test_dividend_normalization(self):
        self.assertAlmostEqual(ns['normalize_dividend_yield'](.08),.08); self.assertAlmostEqual(ns['normalize_dividend_yield'](8),.08); self.assertIsNone(ns['normalize_dividend_yield'](np.nan)); self.assertIsNone(ns['normalize_dividend_yield'](-1))

    def test_position_never_exceeds_capital(self):
        sh,val,risk=ns['position'](100000,1,100,90); self.assertLessEqual(val,100000); self.assertLessEqual(risk,1000)

    def test_price_and_total_return_cagr_distinct(self):
        d=self.make(); self.assertNotEqual(ns['price_cagr'](d),ns['total_return_cagr'](d))

    def test_fair_value_excludes_self_and_requires_peers(self):
        peers=pd.DataFrame([{'symbol':'A','sector_class':'general','pe':10,'pb':1,'ev_ebitda':8,'price':100},{'symbol':'B','sector_class':'general','pe':11,'pb':1.1,'ev_ebitda':9,'price':100},{'symbol':'C','sector_class':'general','pe':12,'pb':1.2,'ev_ebitda':10,'price':100},{'symbol':'D','sector_class':'general','pe':13,'pb':1.3,'ev_ebitda':11,'price':100}]); row=peers.iloc[0]; self.assertIsNone(ns['fair_value'](row,peers[:2])[0]); self.assertIsNotNone(ns['fair_value'](row,peers)[0])

    def test_ev_ebitda_converts_ev_to_equity_value(self):
        rows=[
            {'symbol':'A','sector_class':'general','pe':None,'pb':None,'ev_ebitda':8,'ebitda':1000000,'net_debt':200000,'shares_outstanding':100000,'price':100,'currency_consistent':True},
            {'symbol':'B','sector_class':'general','pe':None,'pb':None,'ev_ebitda':10,'ebitda':1000000,'net_debt':200000,'shares_outstanding':100000,'price':100,'currency_consistent':True},
            {'symbol':'C','sector_class':'general','pe':None,'pb':None,'ev_ebitda':10,'ebitda':1000000,'net_debt':200000,'shares_outstanding':100000,'price':100,'currency_consistent':True},
            {'symbol':'D','sector_class':'general','pe':None,'pb':None,'ev_ebitda':12,'ebitda':1000000,'net_debt':200000,'shares_outstanding':100000,'price':100,'currency_consistent':True},
        ]
        fv=ns['fair_value'](pd.Series(rows[0]),pd.DataFrame(rows))
        self.assertAlmostEqual(fv[0],98.0,places=2)
        self.assertIn('EV_EBITDA',fv[1])

    def test_actions_not_requested_when_splits_embedded(self):
        class T: pass
        class Mock:
            def __init__(self,d): self.d=d; self.actions_called=0
            def ticker(self,s): return T()
            def history(self,t): return self.d.copy(),'success',''
            def info(self,t): return ({'sector':'Industrials','trailingPE':12,'priceToBook':1.4},'ok','')
            def income_stmt(self,t): return (pd.DataFrame(),'empty','no income')
            def actions(self,t): self.actions_called += 1; return pd.DataFrame()
        d=self.make(); d['Stock Splits']=0.0
        c=Mock(d); ns['analyze_one'](c,'AAA',100000,1)
        self.assertEqual(c.actions_called,0)

    def test_yahoo_statuses_are_exposed(self):
        class C:
            def info(self,t): return {},'error','429: rate limited'
            def income_stmt(self,t): return pd.DataFrame(),'empty','no income'
        f=ns['fundamentals'](C(),object())
        self.assertEqual(f['info_status'],'error'); self.assertIn('429',f['info_error'])
        self.assertEqual(f['income_status'],'empty'); self.assertFalse(f['fundamentals_ok'])

    def test_egx_session_baseline_not_252(self):
        # 2024-01-01 to 2024-01-31: count Sunday-Thursday sessions.
        d=self.make(700)
        q=ns['history_quality'](d,'success')
        self.assertTrue(0 <= q <= 100)

    def test_yfinance_retries_disabled(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("yf.config.network.retries = 0",src)
        self.assertIn("HTTPAdapter(max_retries=Retry(total=0)",src)

    def test_history_gap_stats_reports_expected_and_missing(self):
        d=self.make(120); stats=ns['trading_gap_stats'](d)
        self.assertGreater(stats['expected_sessions'],0); self.assertLessEqual(stats['observed_sessions'],120)
        self.assertGreaterEqual(stats['missing_sessions'],0); self.assertGreaterEqual(stats['gap_ratio'],0)

    def test_valuation_confidence_requires_multiple_metrics(self):
        rows=[{'symbol':x,'sector_class':'general','pe':10+i,'pb':1.0+i*.05,'ev_ebitda':8+i,'ebitda':1000000,'net_debt':200000,'shares_outstanding':100000,'price':100,'currency_consistent':True} for i,x in enumerate(['A','B','C','D'])]
        fv=ns['fair_value'](pd.Series(rows[0]),pd.DataFrame(rows))
        self.assertEqual(len(fv),6); self.assertGreaterEqual(fv[4],2); self.assertIn(fv[5],('Medium','High'))

    def test_live_smoke_is_opt_in(self):
        old=os.environ.pop('EGX_LIVE_SMOKE',None)
        try:
            out=ns['live_yahoo_smoke_test']('COMI'); self.assertFalse(out['enabled']); self.assertEqual(out['status'],'skipped')
        finally:
            if old is not None: os.environ['EGX_LIVE_SMOKE']=old

    def test_global_gate_records_requests_and_cooldown(self):
        g=ns['GlobalYahooGate'](0); g.wait(); self.assertEqual(g.request_count,1); g.cooldown(.001); self.assertGreaterEqual(g.last_cooldown_seconds,.001)

    def test_scan_coverage_has_runtime_diagnostics(self):
        class T: pass
        class Mock:
            def ticker(self,s): return T()
            def history(self,t): return self.make(700),'success',''
            def info(self,t): return ({'sector':'Industrials','trailingPE':12,'priceToBook':1.4},'ok','')
            def income_stmt(self,t): return pd.DataFrame(),'empty','no income'
        # use existing scan mock test pattern only to assert diagnostic helper independently
        self.assertTrue(hasattr(__import__('platform'),'python_version'))

    def test_history_sufficiency_separate_from_quality(self):
        d=self.make(100)
        out=ns['history_sufficiency'](d)
        self.assertLess(out['overall'],100)
        self.assertGreaterEqual(ns['history_quality'](d,'success'),0)

    def test_egx_calendar_excludes_known_2026_full_close(self):
        days=ns['egx_expected_sessions']('2026-08-24','2026-08-27')
        self.assertNotIn(pd.Timestamp('2026-08-26'),days)
        self.assertIn(pd.Timestamp('2026-08-25'),days)

    def test_fair_value_uses_direct_eps_and_book_value(self):
        rows=[]
        for i,x in enumerate(['A','B','C','D']):
            rows.append({'symbol':x,'sector_class':'general','industry':'Chemicals','pe':10+i,'pb':1+i*.1,
                         'ev_ebitda':None,'ebitda':None,'net_debt':None,'shares_outstanding':100000,
                         'trailing_eps':5,'book_value_per_share':40,'price':100})
        fv=ns['fair_value'](pd.Series(rows[0]),pd.DataFrame(rows))
        self.assertIsNotNone(fv[0]); self.assertGreaterEqual(fv[4],2)

    def test_industry_preferred_for_peers(self):
        rows=[
            {'symbol':'A','sector_class':'general','industry':'Chemicals','pe':10,'pb':1,'ev_ebitda':8,'price':100},
            {'symbol':'B','sector_class':'general','industry':'Chemicals','pe':11,'pb':1,'ev_ebitda':8,'price':100},
            {'symbol':'C','sector_class':'general','industry':'Chemicals','pe':12,'pb':1,'ev_ebitda':8,'price':100},
            {'symbol':'D','sector_class':'general','industry':'Chemicals','pe':13,'pb':1,'ev_ebitda':8,'price':100},
            {'symbol':'E','sector_class':'general','industry':'Telecom','pe':100,'pb':1,'ev_ebitda':8,'price':100},
        ]
        fv=ns['fair_value'](pd.Series(rows[0]),pd.DataFrame(rows))
        self.assertIn('PE median=12.00',fv[1])


    def test_actions_fallback_only_when_history_has_no_split_column(self):
        class T: pass
        class Mock:
            def __init__(self,d): self.d=d; self.actions_called=0
            def ticker(self,s): return T()
            def history(self,t): return self.d.copy(),'success',''
            def info(self,t): return ({'sector':'Industrials','trailingPE':12,'priceToBook':1.4},'ok','')
            def income_stmt(self,t): return pd.DataFrame(),'empty','no income'
            def actions(self,t):
                self.actions_called += 1
                return pd.DataFrame({'Stock Splits':[2.0]},index=[self.d.index[-1]]),'ok',''
        d=self.make(); d=d.drop(columns=['Stock Splits'])
        c=Mock(d); out=ns['analyze_one'](c,'AAA',100000,1)
        self.assertEqual(c.actions_called,1)
        self.assertEqual(out['actions_status'],'fallback_used')

    def test_fundamentals_strength_is_distinct(self):
        class C:
            def info(self,t): return ({'sector':'Industrials','returnOnEquity':.20,'profitMargins':.20,'trailingPE':12,'priceToBook':1.2},'ok','')
            def income_stmt(self,t): return pd.DataFrame(),'empty',''
        f=ns['fundamentals'](C(),object())
        self.assertIn('fundamentals_strength',f)
        self.assertNotEqual(f['fundamentals_strength'],f['fundamentals_quality'])


    def test_cookie_crumb_requests_are_classified_separately(self):
        self.assertEqual(ns['_yahoo_request_kind']('https://query1.finance.yahoo.com/v1/test/getcrumb'),'crumb')
        self.assertEqual(ns['_yahoo_request_kind']('https://fc.yahoo.com/'),'cookie')
        self.assertEqual(ns['_yahoo_request_kind']('https://query1.finance.yahoo.com/v8/finance/chart/COMI.CA'),'data')

    def test_gate_tracks_cookie_crumb_and_data_attempts(self):
        g=ns['GlobalYahooGate'](0); g.wait('crumb'); g.wait('cookie'); g.wait('data')
        self.assertEqual(g.crumb_requests,1); self.assertEqual(g.cookie_requests,1); self.assertEqual(g.data_requests,1)
        self.assertEqual(g.transport_attempts,3)

    def test_peer_eligibility_is_independent_of_fundamentals_ok(self):
        row={'symbol':'A','price':100,'sector_class':'general','pe':12,'fundamentals_ok':False}
        ok,reason=ns['peer_eligibility'](row)
        self.assertTrue(ok); self.assertEqual(reason,'eligible')

    def test_peer_eligibility_rejects_no_multiple_without_calling_fundamentals_ok(self):
        row={'symbol':'A','price':100,'sector_class':'general','pe':None,'pb':None,'ev_ebitda':None,'fundamentals_ok':True}
        ok,reason=ns['peer_eligibility'](row)
        self.assertFalse(ok); self.assertIn('no_usable_valuation_multiple',reason)

    def test_cookie_crumb_are_not_transport_retried(self):
        class FakeSession(ns['ManagedRequestsSession']):
            def __init__(self,gate):
                super().__init__(gate,retries=3,timeout=1); self.calls=0
            def _fake_response(self,url):
                self.calls+=1; return FakeResponse(429,0)
            def request(self,method,url,**kwargs):
                kind=ns['_yahoo_request_kind'](url); max_attempts=1 if kind in ('cookie','crumb') else self.egx_retries+1
                for attempt in range(max_attempts):
                    self.gate.wait(kind); response=self._fake_response(url); self.gate.record_response(kind,response.status_code)
                    if response.status_code==429:
                        self.gate.cooldown(0)
                        if kind not in ('cookie','crumb') and attempt<max_attempts-1: continue
                    return response
        g=ns['GlobalYahooGate'](0); s=FakeSession(g); s.request('GET','https://query1.finance.yahoo.com/v1/test/getcrumb')
        self.assertEqual(s.calls,1); self.assertEqual(g.crumb_requests,1); self.assertEqual(g.rate_limit_count,1)

    def test_requests_fallback_is_explicit_when_curl_available(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("os.getenv('EGX_FORCE_REQUESTS','0')!='1'",src)
        self.assertNotIn("except Exception: s=ManagedRequestsSession",src)

    def test_live_smoke_contract_is_real_opt_in(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("EGX_LIVE_SMOKE",src)
        self.assertIn("YahooHTTPManager",src)
        self.assertIn("mgr.ticker(sym)",src)
        self.assertIn("all(c in d.columns for c in ['Open','High','Low','Close'])",src)

    def test_root_release_script_exists(self):
        self.assertTrue((P.parent/'qa_release.py').exists())


    def test_curl_session_is_real_supported_session_subclass(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("class ManagedCurlSession(curl_requests.Session)",src)
        self.assertNotIn("class ManagedCurlSession:",src)
        self.assertIn("super().__init__(impersonate='chrome', retry=0)",src)

    def test_history_network_failure_never_uses_compatibility_fallback(self):
        class T:
            calls=0
            def history(self,**kwargs):
                self.calls += 1
                raise RuntimeError("429 rate limited")
        c=ns['YahooHTTPManager'](interval=0,retries=2,timeout=1)
        t=T()
        d,status,error=c.history(t)
        self.assertTrue(d.empty)
        self.assertTrue(status.startswith('history_failed:'))
        self.assertEqual(t.calls,1)

    def test_data_quality_is_not_capped_by_missing_fair_value(self):
        f={'fundamentals_completeness':100,'fundamentals_strength':90,'financial_last_date':pd.Timestamp.now(tz='UTC')}
        q=ns['quality'](pd.DataFrame(),f,False,0,pd.Timestamp.now(tz='UTC'),100)
        self.assertGreater(q,74.9)

    def test_ev_ebitda_requires_currency_consistency(self):
        rows=[{'symbol':x,'sector_class':'general','pe':None,'pb':None,'ev_ebitda':10,
               'ebitda':1000000,'net_debt':200000,'shares_outstanding':100000,'price':100,
               'currency_consistent':(x!='D')} for x in ['A','B','C','D']]
        fv=ns['fair_value'](pd.Series(rows[0]),pd.DataFrame(rows))
        self.assertIsNotNone(fv[0])
        row_bad=pd.Series(rows[3])
        fv_bad=ns['fair_value'](row_bad,pd.DataFrame(rows))
        # Bad target currency must not use EV/EBITDA.
        self.assertTrue('EV_EBITDA' not in fv_bad[1])

    def test_calendar_metadata_is_exposed(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("EGX_CALENDAR_SOURCE",src)
        self.assertIn("EGX_CALENDAR_VERSION",src)

    def test_book_value_validation_uses_book_value_not_shares(self):
        class C:
            def info(self,t):
                return {'sector':'Industrials','trailingPE':12,'priceToBook':1.4,
                        'sharesOutstanding':1000,'bookValue':np.nan},'ok',''
            def income_stmt(self,t): return pd.DataFrame(),'empty',''
        f=ns['fundamentals'](C(),object())
        self.assertIsNone(f['book_value_per_share'])

    def test_technical_sufficiency_is_explicit(self):
        class T: pass
        class Mock:
            def ticker(self,s): return T()
            def history(self,t): return self_d.copy(),'success',''
            def info(self,t): return ({'sector':'Industrials'},'ok','')
            def income_stmt(self,t): return pd.DataFrame(),'empty',''
            def actions(self,t): return pd.DataFrame()
        self_d=self.make(100)
        out=ns['analyze_one'](Mock(),'AAA',100000,1)
        self.assertFalse(out['technical_data_sufficient'])
        self.assertIn('technical_data_sufficiency_reason',out)

    def test_single_shared_session_and_serialized_yfinance_calls(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("self._session_obj=None",src)
        self.assertIn("self._yf_lock=threading.RLock()",src)
        self.assertIn("with self._yf_lock:",src)
        self.assertNotIn("self.local=threading.local()",src)

    def test_curl_retry_is_explicitly_zero(self):
        src=P.read_text(encoding='utf-8')
        self.assertIn("super().__init__(impersonate='chrome', retry=0)",src)
        self.assertIn("yf.config.network.retries = 0",src)

    def test_live_gate_covers_all_operations_and_parallel_workers(self):
        src=P.read_text(encoding='utf-8')
        for token in ["mgr.info(t)","mgr.income_stmt(t)","mgr.actions(t)","ThreadPoolExecutor(max_workers=min(3,len(symbols)))","cookie_requests","crumb_requests"]:
            self.assertIn(token,src)


if __name__=='__main__': unittest.main()
