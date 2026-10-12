# -*- coding: utf-8 -*-
"""WoS 内部接口后端（vendored，本技能自带，运行不依赖外部仓库）。

来源：wos-request 仓库 engine/wos_requests.py @ 5b42177（2026-07-13 摘取）。
仅保留本技能所需的会话自举与检索函数（bootstrap / run_query /
fetch_records_json / EXPORT_BATCH），并裁剪了未用到的导出函数、CLI 入口和 import；
函数体保持与上游逐字一致，便于 diff 同步。
接口知识的研发真相源仍是上游仓库 docs/wos_api_reference.md；
上游接口变化修复后，需手动同步本文件并更新上述提交号。

会话原理（全部服务端 302，requests 可跟随）：
    GET webofknowledge.com 的 transfer 入口
      → access.clarivate.com/login?detectSession=true（出口 IP 机构会话检测，授权则放行）
      → 落地 URL 带 SID；会话 Cookie 由 requests.Session 自动持有。
    检索接口 SID 放 query `?SID=`；导出接口 SID 放头 `x-1p-wos-sid`，不可混用。
"""
import re, json
from urllib.parse import urlparse
import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
# 服务端 302 起点(www.webofscience.com 是 JS 跳转, requests 跟不到, 所以直接用 webofknowledge transfer)
TRANSFER = ("https://www.webofknowledge.com/?mode=Nextgen&action=transfer"
            "&path=%2Fwos%2Fwoscc%2Fbasic-search&DestApp=UA&DestParams=")
EXPORT_BATCH = 1000     # 导出接口单批上限
ANALYZES = ["TP.Value.6","REVIEW.Value.6","EARLY ACCESS.Value.6","OA.Value.6","DR.Value.6",
            "ECR.Value.6","PY.Field_D.6","FPY.Field_D.6","DT.Value.6","AU.Value.6",
            "DX2NG.Value.6","PEERREVIEW.Value.6","STK.Value.10"]


def bootstrap():
    """跟随 302 链拿到 SID + 会话 Cookie。返回 (session, sid, origin)。"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    r = s.get(TRANSFER, allow_redirects=True, timeout=60)
    chain = [h.url for h in r.history] + [r.url]
    sid = None
    for u in chain:
        m = re.search(r"[?&]SID=([A-Za-z0-9]+)", u)
        if m:
            sid = m.group(1)
    if "access.clarivate.com/login" in r.url or not sid:
        raise RuntimeError("未获得 SID(可能本机出口 IP 未被机构授权,落到了登录页)。final=%s" % r.url)
    origin = "{0.scheme}://{0.netloc}".format(urlparse(r.url))   # 如 https://webofscience.clarivate.cn
    return s, sid, origin


def _ndjson(text):
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except ValueError:
                pass


def run_query(s, sid, origin, query_rows, sort="relevance"):
    """POST runQuerySearch,返回 (qid, records_found)。"""
    body = {
        "product": "WOSCC", "searchMode": "general", "viewType": "search", "serviceMode": "summary",
        "search": {"mode": "general", "database": "WOSCC", "query": query_rows,
                   "sets": [], "options": {"lemmatize": "On"}},
        "retrieve": {"count": 1, "history": True, "jcr": True, "sort": sort,
                     "analyzes": ANALYZES, "locale": "en"},
        "eventMode": None,
    }
    r = s.post(origin + "/api/wosnx/core/runQuerySearch?SID=" + sid,
               data=json.dumps(body),
               headers={"accept": "application/x-ndjson",
                        "content-type": "text/plain;charset=UTF-8",
                        "origin": origin,
                        "referer": origin + "/wos/woscc/basic-search"},
               timeout=90)
    r.raise_for_status()
    for o in _ndjson(r.text):
        if o.get("key") == "searchInfo":
            return o["payload"]["QueryID"], o["payload"]["RecordsFound"]
    raise RuntimeError("runQuerySearch 未返回 searchInfo(检索式可能非法):" + r.text[:300])


def fetch_records_json(s, sid, origin, qid, target, sort="relevance", page_size=100):
    """用 runQueryGetRecordsStream 分页抓结构化 JSON(合并每 20 条一个 chunk)。"""
    out = []
    first = 1
    while first <= target:
        count = min(page_size, target - first + 1)
        body = {"qid": qid, "retrieve": {"first": first, "count": count, "sort": sort, "jcr": True},
                "product": "WOSCC", "searchMode": "general", "viewType": "records"}
        r = s.post(origin + "/api/wosnx/core/runQueryGetRecordsStream?SID=" + sid,
                   data=json.dumps(body),
                   headers={"accept": "application/x-ndjson",
                            "content-type": "text/plain;charset=UTF-8", "origin": origin},
                   timeout=120)
        r.raise_for_status()
        merged = {}
        for o in _ndjson(r.text):
            if o.get("key") == "records":
                merged.update(o["payload"])
        for k in sorted(merged, key=int):
            rec = merged[k]
            def g(path, default=None):
                cur = rec
                try:
                    for p in path:
                        cur = cur[p]
                    return cur
                except (KeyError, IndexError, TypeError):
                    return default
            authors = [a["wos_standard"] for a in (g(["names", "author", "en"], []) or []) if a]
            ids = {i["type"]: i["value"] for i in rec.get("identifiers", [])}
            out.append({
                "pos": int(k), "ut": rec.get("ut"),
                "doi": rec.get("doi") or ids.get("doi"),
                "title": g(["titles", "item", "en", 0, "title"]),
                "source": g(["titles", "source", "en", 0, "title"]),
                "authors": authors,
                "pubyear": g(["pub_info", "pubyear"]),
                "doctypes": rec.get("doctypes", []),
                "times_cited": g(["citation_related", "counts", "WOSCC"]),
                "abstract": re.sub(r"<[^>]+>", "", g(["abstract", "basic", "en", "abstract"], "") or ""),
            })
        first += count
    return out
