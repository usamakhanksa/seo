#!/usr/bin/env python3
"""Best Web Developer read-only SEO/AEO/GEO integrity crawler.
Checks technical eligibility, NOT Google Search Console indexing.
No website changes, Indexing API requests, or content generation.
"""
import argparse
import csv
import datetime as dt
import gzip
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path

ROOT = "https://bestwebdeveloper.org"
HOST = "bestwebdeveloper.org"
AGENT = "BWD-SEO-Integrity/1.1 (+https://bestwebdeveloper.org/contact/)"
HEADERS = {"User-Agent": AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.3",
           "Accept-Encoding": "identity"}

class SEOParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.desc = ""
        self.robots = []
        self.canonical = []
        self.hreflang = 0
        self.jsonld = 0
        self.h1 = 0
        self.lang = ""
        self.in_title = False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.h1 += 1
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.jsonld += 1
        elif tag == "meta":
            key = a.get("name", "").lower()
            if key == "description":
                self.desc = a.get("content", "")
            if key in ("robots", "googlebot"):
                self.robots.append(a.get("content", ""))
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            if "canonical" in rel:
                self.canonical.append(a.get("href", ""))
            if "alternate" in rel and a.get("hreflang"):
                self.hreflang += 1
    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
    def handle_data(self, data):
        if self.in_title:
            self.title += data

class SafeRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.hops = []
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never fetch unexpected external hosts when auditing a WordPress URL.
        if urllib.parse.urlsplit(newurl).hostname not in (HOST, "www." + HOST):
            raise urllib.error.HTTPError(newurl, 470, "external redirect", headers, fp)
        self.hops.append((code, newurl))
        if len(self.hops) > 7:
            raise urllib.error.HTTPError(newurl, 508, "too many redirects", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch(url, max_bytes=700000, timeout=17):
    redirects = SafeRedirects()
    opener = urllib.request.build_opener(redirects)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.geturl(), dict(r.headers.items()), r.read(max_bytes + 1), redirects.hops, ""
    except urllib.error.HTTPError as e:
        return e.code, e.geturl(), dict(e.headers.items()) if e.headers else {}, e.read(12000), redirects.hops, ""
    except Exception as e:
        return 0, url, {}, b"", redirects.hops, str(e)

def parse_robots(source):
    groups, agents, rules = [], [], []
    for raw in source.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            continue
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents and value:
            rules.append((key, value))
    if agents:
        groups.append((agents, rules))
    return groups

def robots_allows(url, groups, agent="googlebot"):
    matches, strongest = [], 0
    for agents, rules in groups:
        score = max([len(a) for a in agents if a != "*" and a in agent] or [0])
        if score > strongest:
            strongest, matches = score, [rules]
        elif score == strongest and score:
            matches.append(rules)
    if not matches:
        matches = [rules for agents, rules in groups if "*" in agents]
    parts = urllib.parse.urlsplit(url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    choices = []
    for rules in matches:
        for action, pattern in rules:
            anchored = pattern.endswith("$")
            cleaned = pattern[:-1] if anchored else pattern
            reg = "^" + "".join(".*" if ch == "*" else re.escape(ch) for ch in cleaned)
            if anchored:
                reg += "$"
            if re.search(reg, path):
                choices.append((len(cleaned.replace("*", "")), action == "allow"))
    if not choices:
        return True
    longest = max(c[0] for c in choices)
    return any(allowed for size, allowed in choices if size == longest)

def sitemap_inventory():
    queue = [ROOT + "/sitemap_index.xml"]
    seen, urls, errors = set(), set(), []
    while queue and len(seen) < 120 and len(urls) < 30000:
        address = queue.pop(0)
        if address in seen:
            continue
        seen.add(address)
        if urllib.parse.urlsplit(address).hostname != HOST:
            errors.append({"sitemap": address, "error": "off-site sitemap URL"})
            continue
        status, final, headers, body, hops, err = fetch(address, max_bytes=6000000)
        if status != 200:
            errors.append({"sitemap": address, "http_status": status, "error": err})
            continue
        try:
            if body[:2] == b"\x1f\x8b" or address.endswith(".gz"):
                body = gzip.decompress(body)
            tree = ET.fromstring(body)
            locs = [x.text.strip() for x in tree.iter()
                    if x.tag.rsplit("}", 1)[-1] == "loc" and x.text]
            tag = tree.tag.rsplit("}", 1)[-1]
            if tag == "sitemapindex":
                queue.extend(locs)
            elif tag == "urlset":
                urls.update(x for x in locs if urllib.parse.urlsplit(x).hostname == HOST)
            else:
                errors.append({"sitemap": address, "error": "unrecognized XML root " + tag})
        except Exception as e:
            errors.append({"sitemap": address, "error": repr(e)})
    return urls, errors, len(seen)

def read_baseline(path):
    reasons = defaultdict(set)
    rows = 0
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            url = item["url"].strip()
            if urllib.parse.urlsplit(url).hostname == HOST:
                reasons[url].add(item["gsc_reason"])
                rows += 1
    return reasons, rows

def read_scheduled(path):
    scheduled = {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            scheduled[row["slug"]] = dt.date.fromisoformat(row["scheduled_date"])
    return scheduled

def inspect(url, reasons, robots, scheduled):
    today = dt.datetime.now(dt.timezone.utc).date()
    slug = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]
    result = {
        "url": url, "historic_gsc_reasons": "; ".join(sorted(reasons)),
        "http_status": "", "redirect_hops": "", "final_url": "",
        "robots_allowed_for_googlebot": "", "meta_robots": "",
        "canonical": "", "title": "", "meta_description": "",
        "h1_count": "", "jsonld_count": "", "hreflang_count": "", "html_lang": "",
        "outcome": "", "evidence": "", "google_index_status": "NOT_VERIFIED"}
    if slug in scheduled and today < scheduled[slug]:
        result["outcome"] = "SCHEDULED_FUTURE_ARTICLE"
        result["evidence"] = "WordPress future post confirmed, publish date " + str(scheduled[slug])
        return result
    if not robots_allows(url, robots):
        result["robots_allowed_for_googlebot"] = "false"
        result["outcome"] = "ROBOTS_EXCLUSION"
        result["evidence"] = "Disallowed by current robots.txt; may be intentional"
        return result
    result["robots_allowed_for_googlebot"] = "true"
    status, final, headers, body, hops, err = fetch(url)
    result.update(http_status=status, redirect_hops=len(hops), final_url=final)
    if err:
        result.update(outcome="NETWORK_ERROR", evidence=err[:400])
        return result
    if status >= 500:
        result.update(outcome="HTTP_5XX", evidence="Current HTTP " + str(status))
        return result
    if status in (403, 429):
        result.update(outcome="ACCESS_RESTRICTION", evidence="Current HTTP " + str(status) +
                      "; the audit agent is NOT Googlebot")
        return result
    if status in (404, 410):
        result.update(outcome="HTTP_404_410", evidence="Current HTTP " + str(status))
        return result
    if status != 200:
        result.update(outcome="OTHER_HTTP_STATUS", evidence="Current HTTP " + str(status))
        return result
    raw = body.decode("utf-8", errors="replace")
    if "Just a moment..." in raw and ("cf_chl" in raw or "/cdn-cgi/challenge-platform" in raw):
        result.update(outcome="BOT_CHALLENGE", evidence="Challenge received by non-verified audit user-agent")
        return result
    parser = SEOParser()
    try:
        parser.feed(raw)
    except Exception as e:
        result.update(outcome="HTML_PARSE_ERROR", evidence=repr(e))
        return result
    xrobots = " ".join(value for key, value in headers.items() if key.lower() == "x-robots-tag")
    directives = " ".join(parser.robots + [xrobots]).lower()
    result.update(title=parser.title.strip(), meta_description=parser.desc.strip(),
                  meta_robots=directives, canonical=" | ".join(parser.canonical),
                  h1_count=parser.h1, jsonld_count=parser.jsonld,
                  hreflang_count=parser.hreflang, html_lang=parser.lang)
    if len(hops) > 1:
        result.update(outcome="REDIRECT_CHAIN", evidence="Multiple HTTP redirect hops")
    elif hops:
        result.update(outcome="REDIRECTED", evidence="HTTP " + str(hops[0][0]) +
                      " to " + final + "; review if intentional")
    elif "noindex" in directives:
        result.update(outcome="NOINDEX", evidence="HTML or HTTP robots directive")
    elif len(parser.canonical) != 1:
        result.update(outcome="CANONICAL_REVIEW", evidence="Expected one canonical; found " +
                      str(len(parser.canonical)))
    elif parser.canonical[0].rstrip("/") != url.rstrip("/"):
        result.update(outcome="CANONICAL_DIFFERENCE", evidence="Canonical target differs; may be valid")
    elif not parser.title or not parser.desc or not parser.h1:
        result.update(outcome="METADATA_REVIEW", evidence="Missing title, meta description or H1")
    else:
        result.update(outcome="TECHNICALLY_ELIGIBLE",
                      evidence="HTTP 200, robots allowed, self-canonical and no noindex observed; GSC NOT VERIFIED")
    return result

FIELDS = ["url", "historic_gsc_reasons", "http_status", "redirect_hops",
          "final_url", "robots_allowed_for_googlebot", "meta_robots", "canonical",
          "title", "meta_description", "h1_count", "jsonld_count", "hreflang_count",
          "html_lang", "outcome", "evidence", "google_index_status"]

def run(args):
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    baseline, baseline_rows = read_baseline(args.baseline)
    scheduled = read_scheduled(args.scheduled)
    status, _, _, body, _, error = fetch(ROOT + "/robots.txt", max_bytes=250000)
    if status != 200 or error:
        print(json.dumps({"fatal": "robots.txt unavailable", "http_status": status, "error": error}))
        return 2
    robots = parse_robots(body.decode("utf-8", errors="replace"))
    sitemap_urls, sitemap_errors, sitemap_count = sitemap_inventory()
    urls = sorted(set(baseline) | sitemap_urls)
    if args.full:
        selected = urls
    else:
        chunks = max(math.ceil(len(urls) / args.batch_size), 1)
        slot = int(time.time() // 21600) % chunks
        selected = urls[slot * args.batch_size:(slot + 1) * args.batch_size]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 3))) as pool:
        jobs = {pool.submit(inspect, url, baseline.get(url, {"IN_SITEMAP"}),
                            robots, scheduled): url for url in selected}
        for future in as_completed(jobs):
            try:
                results.append(future.result())
            except Exception as e:
                results.append({"url": jobs[future], "outcome": "EXCEPTION",
                                "evidence": repr(e), "google_index_status": "NOT_VERIFIED"})
    results.sort(key=lambda r: r["url"])
    with (target / "audit.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    summary = {
        "target": ROOT, "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "historical_gsc_url_reason_records": baseline_rows,
        "unique_known_urls": len(urls), "url_count_checked": len(results),
        "in_current_sitemap": len(sitemap_urls), "sitemap_files": sitemap_count,
        "sitemap_errors": sitemap_errors, "outcomes": dict(Counter(x["outcome"] for x in results)),
        "google_index_status": "NOT VERIFIED - this audit is not Search Console"}
    (target / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Best Web Developer | SEO Integrity", "",
             "UTC: " + summary["utc"], "",
             "Historical records: " + str(baseline_rows),
             "Unique inventory: " + str(len(urls)),
             "Checked in this run: " + str(len(results)), "",
             "| Outcome | Count |", "|---|---:|"]
    lines += ["| " + key + " | " + str(num) + " |"
              for key, num in sorted(summary["outcomes"].items())]
    lines += ["", "Google indexing is NOT confirmed by this diagnostic.",
              "Never mass-publish replacements for future posts or intentional exclusions."]
    (target / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if sitemap_errors or any(x["outcome"] in ("HTTP_5XX", "HTTP_404_410", "BOT_CHALLENGE")
                             for x in results if x["url"] in sitemap_urls):
        return 1
    return 0

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", default="bwd-seo/data/gsc-baseline.csv")
    p.add_argument("--scheduled", default="bwd-seo/data/scheduled-future-posts.csv")
    p.add_argument("--output", default="bwd-seo/reports")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--batch-size", type=int, default=275)
    p.add_argument("--full", action="store_true")
    raise SystemExit(run(p.parse_args()))
