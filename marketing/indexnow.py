"""Tell search engines that use IndexNow (Bing, Yandex, Naver and others) that the site's pages have changed.

IndexNow is free and needs no account: the key is a public file on the site (marketing/src/assets/<key>.txt, served at the site root).
It sends only the public page addresses from sitemap.xml. It does not tell Google, which needs Search Console (see VISIBILITY_STRATEGY.md).

    python marketing/indexnow.py          # after the site is live; the publish workflow runs it on every deploy
"""
import glob
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
keys = [os.path.basename(p)[:-4] for p in glob.glob(os.path.join(HERE, "src", "assets", "*.txt")) if re.fullmatch(r"[0-9a-f]{32}\.txt", os.path.basename(p))]
if not keys:
    sys.exit("no IndexNow key file found in src/assets")
key = keys[0]
site = json.load(open(os.path.join(HERE, "src", "site.json"), encoding="utf8"))
base = site["url"].rstrip("/")
host = site["domain"]
sitemap = open(os.path.join(HERE, "public", "sitemap.xml"), encoding="utf8").read()
urls = re.findall(r"<loc>([^<]+)</loc>", sitemap)
body = json.dumps({"host": host, "key": key, "keyLocation": f"{base}/{key}.txt", "urlList": urls}).encode()
req = urllib.request.Request("https://api.indexnow.org/IndexNow", data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print("IndexNow accepted", len(urls), "urls, HTTP", r.status)
except urllib.error.HTTPError as e:  # 202 means received but key not verified yet: it is retried after the key file is live
    print("IndexNow answered HTTP", e.code, "for", len(urls), "urls")
except Exception as e:
    print("IndexNow not reached:", e)
