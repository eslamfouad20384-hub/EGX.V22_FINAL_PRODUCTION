# EGX Smart Investment & Entry Analyzer V22.0 QA/PRODUCTION

V22 combines the strongest V18/V19 architecture and fixes the remaining Yahoo integration and peer-universe issues.

## Yahoo HTTP / Cookie / Crumb policy

- `curl_cffi.requests.Session` is the primary session when available.
- A real `curl_cffi` Session is passed to yfinance; no custom wrapper object is used.
- yfinance network retry configuration is disabled (`yf.config.network.retries = 0`).
- This does **not** claim that yfinance performs exactly one HTTP request per operation. yfinance may perform internal cookie/crumb strategy requests.
- V22 classifies and counts `cookie`, `crumb`, and `data` transport attempts separately.
- The application's transport retry policy never retries cookie/crumb requests.
- Data transport retries are limited to 429 and transient 5xx / transport exceptions.
- `Retry-After` is honored when supplied.
- Requests fallback is explicit with `EGX_FORCE_REQUESTS=1`, or automatic only when curl_cffi is unavailable. A broken curl_cffi installation is not silently hidden.
- Diagnostics expose `transport_attempts`, `data_requests`, `cookie_requests`, `crumb_requests`, and `http_429`.

## Real Yahoo integration test

Normal QA uses deterministic tests and does not require the network.

After installing the locked requirements, run a real external integration test:

```bash
python qa_live.py COMI
```

Or include it in release QA:

```bash
EGX_LIVE_SMOKE=1 python qa_release.py
```

This actually exercises `curl_cffi/requests -> yfinance -> Yahoo` and validates real OHLC columns. A live test can legitimately fail because of network errors or Yahoo 429; that is reported rather than hidden.

## Peer eligibility

`peer_eligible` is independent from `fundamentals_ok`.

A peer can participate in valuation when it has a valid price, sector class, and at least one usable valuation multiple (P/E, P/B, or EV/EBITDA with currency consistency), even if other fundamentals are incomplete.

## Standard QA

```bash
pip install -r requirements.txt
python qa_release.py
streamlit run app.py
```

For reproducible versions:

```bash
pip install -r requirements-lock.txt
```
