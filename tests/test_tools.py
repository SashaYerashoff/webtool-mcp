import os, json, pytest, requests, time

BASE = os.getenv("MCP_URL", "http://localhost:5000/mcp")

pytestmark = pytest.mark.integration

def jrpc(method: str, id_: int, params: dict | None = None):
    payload = {"jsonrpc":"2.0","id":id_,"method":method}
    if params is not None:
        payload["params"] = params
    r = requests.post(BASE, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def test_tools_list_contains_expected():
    data = jrpc("tools/list", 1)
    names = {t['name'] for t in data['result']['tools']}
    for expected in ["fetch_url","quick_search","web_search","latvian_news","search_wikipedia","ai_company_news"]:
        assert expected in names


def test_fetch_url_outline_and_cache():
    data1 = jrpc("tools/call", 2, {"name":"fetch_url","arguments":{"url":"https://example.com","mode":"outline"}})
    text1 = data1['result']['content'][0]['text']
    assert 'Example Domain' in text1
    # second call should include cache_status
    data2 = jrpc("tools/call", 3, {"name":"fetch_url","arguments":{"url":"https://example.com","mode":"outline"}})
    text2 = data2['result']['content'][0]['text']
    assert 'cache_status:' in text2


def test_quick_search():
    data = jrpc("tools/call", 4, {"name":"quick_search","arguments":{"query":"open source vector database"}})
    payload = json.loads(data['result']['content'][0]['text'])
    assert payload.get('results')


def test_web_search_multi_subset():
    data = jrpc("tools/call", 5, {"name":"web_search","arguments":{"query":"python list comprehension","engine":"multi","engines":["duckduckgo"],"max_results":2}})
    payload = json.loads(data['result']['content'][0]['text'])
    assert payload.get('engine') == 'multi'
    assert 'duckduckgo' in payload.get('results', {})


def test_ai_company_news():
    data = jrpc("tools/call", 6, {"name":"ai_company_news","arguments":{}})
    payload = json.loads(data['result']['content'][0]['text'])
    assert payload.get('companies')
