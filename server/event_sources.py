"""Refresh complete event calendars published by operator-approved organizers."""

import base64
import datetime as dt
import hashlib
import http.client
import ipaddress
import json
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import closing
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urljoin, urlsplit

from .store import audit, db, ident, now

HK_URL = "https://www.1823.gov.hk/common/ical/sc.json"
APPLE_NEWS = "https://developer.apple.com/cn/news/rss/news.rss"
CATEGORIES = ("本地活动", "节假日", "公开热点")


def init_sources(c):
    c.execute("""CREATE TABLE IF NOT EXISTS event_feed(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT UNIQUE NOT NULL,
        city TEXT NOT NULL, category TEXT NOT NULL, keywords TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, checked TEXT, due TEXT NOT NULL DEFAULT '',
        lease TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '')""")
    c.execute(
        """INSERT OR IGNORE INTO event_feed(id,name,url,city,category,keywords)
        VALUES('hong-kong-1823','香港 1823 公众假期',?,'香港','节假日','')""",
        (HK_URL,),
    )

    c.execute(
        """INSERT OR IGNORE INTO event_feed(id,name,url,city,category,keywords)
        VALUES('apple-developer','Apple 开发者动态',?,'全部地区','公开热点','软件开发,应用开发,编程培训,iOS,App Store')""",
        (APPLE_NEWS,),
    )


def public_url(url):
    p = urlsplit(url)
    return bool(
        p.scheme == "https"
        and p.hostname
        and not p.username
        and not p.password
        and not p.fragment
    )


def add_source(c, actor, data):
    def field(key, size):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > size:
            raise ValueError("来源字段格式有误。")
        return value.strip()

    name, url = field("name", 100), field("url", 1000)
    city, category, keywords = (
        field("city", 80),
        field("category", 20),
        field("keywords", 160),
    )
    if (
        not name
        or not city
        or not public_url(url)
        or category not in CATEGORIES
        or data.get("verified") is not True
    ):
        raise ValueError("请确认发布方、地区、事件类型与官方 HTTPS 订阅地址。")
    if category == "公开热点" and not keywords:
        raise ValueError("请填写相关行业或经营关键词，以便筛选适合的商家。")
    if c.execute("SELECT 1 FROM event_feed WHERE url=?", (url,)).fetchone():
        raise ValueError("此来源已经加入。")
    identifier = ident()
    c.execute(
        """INSERT INTO event_feed(id,name,url,city,category,keywords)
                 VALUES(?,?,?,?,?,?)""",
        (identifier, name, url, city, category, keywords),
    )
    audit(c, actor, "登记官方营销日历", identifier)
    return identifier


def read_hk_via_resolved_proxy(proxy):
    """Some proxies close the handshake on a hostname CONNECT. Preserve the origin for TLS and HTTP."""
    origin = urlsplit(HK_URL)
    dns_query = f"https://dns.google/resolve?name={origin.hostname}&type=A&edns_client_subnet=0.0.0.0/0"
    with urllib.request.urlopen(dns_query, timeout=8) as response:
        reply = json.loads(response.read(65_537))
    addresses = []
    if reply.get("Status") == 0 and not reply.get("TC"):
        for record in reply.get("Answer", []):
            if record.get("type") == 1:
                ip = ipaddress.IPv4Address(record["data"])
                if ip.is_global and not ip.is_multicast and str(ip) not in addresses:
                    addresses.append(str(ip))
    if not addresses:
        raise ValueError("域名解析未返回 1823 的公网地址。")

    tunnel_headers = {}
    if proxy.username is not None:
        credentials = unquote(proxy.username) + ":" + unquote(proxy.password or "")
        tunnel_headers["Proxy-Authorization"] = (
            "Basic " + base64.b64encode(credentials.encode()).decode()
        )
    context = ssl.create_default_context()
    for address in addresses[:2]:
        try:
            with closing(
                http.client.HTTPConnection(proxy.hostname, proxy.port or 80, timeout=8)
            ) as conn:
                conn.set_tunnel(address, 443, headers=tunnel_headers)
                conn.connect()
                conn.sock = context.wrap_socket(
                    conn.sock, server_hostname=origin.hostname
                )
                conn.request(
                    "GET",
                    origin.path,
                    headers={"Host": origin.hostname, "Accept": "application/json"},
                )
                with conn.getresponse() as response:
                    if response.status != 200:
                        raise ValueError(
                            f"1823 官方假期源返回 HTTP {response.status}。"
                        )
                    return response.read(2_000_001)
        except ssl.SSLCertVerificationError:
            raise
        except (ssl.SSLEOFError, ConnectionError, TimeoutError) as exc:
            last_error = exc
    raise last_error


def read_calendar(url):
    class SameOrigin(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if (
                not public_url(newurl)
                or urlsplit(url).netloc != urlsplit(newurl).netloc
            ):
                raise ValueError("日历重定向到了其他来源，请核对发布方。")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/ld+json, application/json, application/rss+xml, application/atom+xml"
        },
    )
    try:
        with urllib.request.build_opener(SameOrigin()).open(
            request, timeout=12
        ) as response:
            raw = response.read(2_000_001)
    except (
        urllib.error.URLError,
        ConnectionError,
        TimeoutError,
        ssl.SSLEOFError,
    ) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        if url != HK_URL or not isinstance(
            reason, (ssl.SSLEOFError, ConnectionError, TimeoutError)
        ):
            raise
        proxy = urlsplit(urllib.request.getproxies().get("https", ""))
        if (
            proxy.scheme != "http"
            or not proxy.hostname
            or urllib.request.proxy_bypass(urlsplit(HK_URL).hostname)
        ):
            raise
        raw = read_hk_via_resolved_proxy(proxy)
    if len(raw) > 2_000_000:
        raise ValueError("日历文件超过 2 MB。")
    content = raw.decode("utf-8-sig").lstrip()
    if content.startswith("<"):
        if "<!DOCTYPE" in content.upper():
            raise ValueError("订阅格式不支持 DTD。")
        try:
            return ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError("无法解析官方订阅。") from exc
    return json.loads(content)


def event_date(value):
    if len(value) == 10:
        return dt.date.fromisoformat(value)
    return dt.datetime.fromisoformat(value).date()


def parse_calendar(feed, data):
    """Accept confirmed date ranges. JSON-LD dates use the organizer's local time."""
    events = {}
    url = feed["url"]

    def add(uid, title, start, end, page, news=False):
        if not isinstance(title, str) or not title.strip() or not uid or start > end:
            raise ValueError("日历的事件名称、标识或日期无效。")
        page = urljoin(url, page)
        if not public_url(page) or urlsplit(page).netloc != urlsplit(url).netloc:
            raise ValueError("事件详情须来自日历发布方。")
        key = hashlib.sha256((feed["id"] + "\n" + uid).encode()).hexdigest()
        if key in events:
            raise ValueError("日历包含重复事件标识。")
        events[key] = (
            key,
            title.strip()[:120],
            feed["city"],
            start.isoformat(),
            end.isoformat(),
            page,
            feed["category"],
            feed["id"],
            feed["keywords"],
            news,
        )

    if url == HK_URL:
        rows = data["vcalendar"][0]["vevent"]
        if not isinstance(rows, list):
            raise ValueError("公众假期日历结构有误。")
        for row in rows:
            start = dt.date.fromisoformat(row["dtstart"][0])
            end = dt.date.fromisoformat(row["dtend"][0]) - dt.timedelta(days=1)
            add(row["uid"], row["summary"], start, end, url)
    elif ET.iselement(data):
        if feed["category"] != "公开热点":
            raise ValueError("RSS / Atom 记录的是公告发布日期，请将其登记为公开热点。")
        if data.tag == "rss" and data.find("channel") is not None:
            rows = data.findall("./channel/item")
        elif data.tag == "{http://www.w3.org/2005/Atom}feed":
            rows = data.findall("{*}entry")
        else:
            raise ValueError("未识别的官方订阅格式。")
        for row in rows:
            title = row.findtext("{*}title")
            link = next(
                (
                    n
                    for n in row.findall("{*}link")
                    if n.get("rel", "alternate") == "alternate"
                ),
                None,
            )
            if link is None:
                continue
            page = link.get("href") or link.text
            published = row.findtext("{*}published") or row.findtext("{*}pubDate")
            if not page or not title or not published:
                continue
            if not public_url(page) or urlsplit(page).netloc != urlsplit(url).netloc:
                continue
            try:
                date = dt.datetime.fromisoformat(published).date()
            except ValueError:
                date = parsedate_to_datetime(published).date()
            if date <= dt.date.today():
                add(page, title, date, date, page, news=True)
    else:
        rows = data if isinstance(data, list) else data.get("@graph")
        if rows is None and data.get("@type") == "ItemList":
            rows = [entry.get("item", entry) for entry in data["itemListElement"]]
        if rows is None and data.get("@type") == "Event":
            rows = [data]
        if not isinstance(rows, list):
            raise ValueError("请提供完整的 Schema.org Event JSON 列表。")
        for row in rows:
            if row.get("@type") != "Event":
                if isinstance(data, dict) and "@graph" in data:
                    continue
                raise ValueError("请核对 JSON 日历中的 Event 类型。")
            status = row.get("eventStatus", "EventScheduled").rsplit("/", 1)[-1]
            if status not in ("EventScheduled", "EventRescheduled"):
                continue
            place = row.get("location") or {}
            address = place.get("address") if isinstance(place, dict) else None
            city = address.get("addressLocality") if isinstance(address, dict) else None
            if city != feed["city"]:
                continue
            start = event_date(row["startDate"])
            end = event_date(row.get("endDate") or row["startDate"])
            page = row.get("url") or url
            uid = row.get("@id") or row.get("url") or (row["name"] + start.isoformat())
            add(uid, row["name"], start, end, page)
    return list(events.values())


def after(**delta):
    return (dt.datetime.now(dt.UTC) + dt.timedelta(**delta)).isoformat(
        timespec="seconds"
    )


def refresh_source(identifier, actor="system", scheduled=False):
    with db(True) as c:
        feed = c.execute(
            "SELECT * FROM event_feed WHERE id=? AND enabled=1", (identifier,)
        ).fetchone()
        if not feed:
            raise ValueError("此日历来源未启用。")
        if feed["due"] > now() and (scheduled or feed["lease"]):
            if scheduled:
                return 0
            raise ValueError("此日历正在同步。")
        lease = ident()
        c.execute(
            "UPDATE event_feed SET lease=?,due=? WHERE id=?",
            (lease, after(minutes=5), identifier),
        )
    try:
        rows = parse_calendar(feed, read_calendar(feed["url"]))
    except (
        OSError,
        http.client.HTTPException,
        ValueError,
        TypeError,
        IndexError,
        KeyError,
        AttributeError,
    ) as exc:
        message = "官方日历同步失败，请检查网络、日期和订阅格式。"
        with db(True) as c:
            c.execute(
                "UPDATE event_feed SET due=?,lease='',error=? WHERE id=? AND lease=?",
                (after(hours=1), message, identifier, lease),
            )
        raise ValueError(message) from exc
    with db(True) as c:
        updated = c.execute(
            """UPDATE event_feed SET checked=?,due=?,lease='',error=''
                               WHERE id=? AND enabled=1 AND lease=?""",
            (now(), after(hours=24), identifier, lease),
        )
        if not updated.rowcount:
            return 0
        # Only a successful complete snapshot may withdraw or reschedule events.
        c.execute("DELETE FROM event WHERE feed_id=?", (identifier,))
        c.executemany(
            """INSERT INTO event(id,title,city,starts,ends,source,category,feed_id,keywords,is_news,created)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            [(*row, now()) for row in rows],
        )
        audit(c, actor, "同步官方营销日历", f"{feed['name']} · {len(rows)} 项")
    return len(rows)


def refresh_due():
    with db() as c:
        ids = [
            r[0]
            for r in c.execute(
                "SELECT id FROM event_feed WHERE enabled=1 AND due<=?", (now(),)
            )
        ]
    for identifier in ids:
        try:
            refresh_source(identifier, scheduled=True)
        except ValueError:
            continue
