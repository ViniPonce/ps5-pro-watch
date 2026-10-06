import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TOPIC = os.environ.get("NTFY_TOPIC", "")
DRY = os.environ.get("DRY") == "1"
MAX_PRICE = 980.0
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
STATE = "state.json"
END = datetime(2026, 11, 16, 20, 0, tzinfo=ZoneInfo("America/New_York"))
BR = ZoneInfo("America/Sao_Paulo")
SOURCE_LABELS = {
    "sony": "Sony",
    "bestbuy": "Best Buy",
    "costco": "Costco",
    "target-ship": "Target entrega",
    "target-store": "Target loja",
    "walmart": "Walmart",
}
TARGET = "https://www.target.com/p/playstation-5-pro-console/-/A-93620188"
TARGET_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"


def fetch(url, timeout=15, headers=None):
    req_headers = {"User-Agent": UA}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except Exception:
        return 0, ""


def source_of(item_id):
    if item_id == "sony-direct":
        return "sony"
    if item_id == "target-ship":
        return "target-ship"
    if item_id.startswith("target-"):
        return "target-store"
    if item_id == "walmart":
        return "walmart"
    if item_id.startswith("costco-"):
        return "costco"
    if item_id == "bestbuy-online":
        return "bestbuy"
    if item_id.startswith("bestbuy-"):
        return "bestbuy-store"
    return "other"


def open_status(value):
    if not value:
        return False
    if re.search(r"OUT_OF_STOCK|UNAVAILABLE|DISCONTINUED|NOT_SOLD", value):
        return False
    return re.search(r"IN_STOCK|LIMITED|AVAILABLE", value) is not None


def empty_stats(day):
    return {
        "seen": [],
        "day": day,
        "checks": 0,
        "first": "",
        "last": "",
        "hours": {},
        "sources": {},
        "windows": {},
        "available": [],
    }


def load_state():
    if not os.path.exists(STATE):
        return empty_stats(None)
    try:
        with open(STATE, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return empty_stats(None)
    if isinstance(data, list):
        state = empty_stats(None)
        state["seen"] = data
        return state
    if not isinstance(data, dict):
        return empty_stats(None)
    state = empty_stats(data.get("day"))
    for key in state:
        if key in data:
            state[key] = data[key]
    return state


def save_state(state):
    with open(STATE, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False)


def notify(body, click, title="PS5 Pro disponivel", priority="urgent", tags="rotating_light"):
    if DRY or not TOPIC:
        print(body)
        return
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Content-Type": "text/plain; charset=utf-8",
    }
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as exc:
        print(f"notify-failed {type(exc).__name__}")


def in_miami(*parts):
    text = " ".join(parts)
    if re.search(
        r"Fort Lauderdale|Hollywood|Davie|Pembroke|Miramar|Pompano|Coral Springs|Boca|Plantation|Sunrise|Weston",
        text,
        re.I,
    ):
        return False
    return (
        re.search(
            r"Miami|Kendall|Doral|Hialeah|Aventura|Coral Gables|Cutler|Pinecrest|Sweetwater|South Beach|Coconut Grove|Key Biscayne",
            text,
            re.I,
        )
        is not None
    )


def add_store(hits, seen, loc):
    store_id = str(loc.get("location_id") or "")
    if not store_id or store_id in seen:
        return
    seen.add(store_id)
    qty = float(loc.get("location_available_to_promise_quantity") or 0)
    pickup = ((loc.get("order_pickup") or {}).get("availability_status")) or ""
    floor = ((loc.get("in_store_only") or {}).get("availability_status")) or ""
    ship_store = ((loc.get("ship_to_store") or {}).get("availability_status")) or ""
    if not (qty > 0 or open_status(pickup) or open_status(floor) or open_status(ship_store)):
        return
    store = loc.get("store") or {}
    nested = store.get("store") or {}
    name = store.get("location_name") or nested.get("location_name") or "Target"
    address = store.get("mailing_address") or nested.get("mailing_address") or {}
    city = address.get("city") or ""
    street = address.get("address_line1") or ""
    if not in_miami(name, city, street):
        return
    hits.append(
        {
            "id": f"target-{store_id}",
            "click": TARGET,
            "where": f"Target {name}, {city}, retirada",
            "text": (
                f"Target {name}, {city} ({street}). Da para retirar. "
                f"Preco de tabela, cerca de US$ 899,99. {TARGET}"
            ),
        }
    )


def collect():
    hits = []
    checked = set()
    seen = set()

    status, body = fetch(
        "https://api.direct.playstation.com/commercewebservices/ps-direct-us/products/1000050928?fields=BASIC"
    )
    if status == 200 and body:
        checked.add("sony")
        try:
            data = json.loads(body)
            stock = (data.get("stock") or {}).get("stockLevelStatus")
            price = float((data.get("price") or {}).get("value") or 0)
            if stock in ("inStock", "lowStock") and 0 < price <= MAX_PRICE:
                link = "https://direct.playstation.com/en-us/buy-consoles/playstation5-pro-console-2-tb"
                hits.append(
                    {
                        "id": "sony-direct",
                        "click": link,
                        "where": f"PlayStation Direct, US$ {price:.0f}, entrega",
                        "text": f"PlayStation Direct em estoque por US$ {price:.0f}. Entrega em endereco nos EUA. {link}",
                    }
                )
        except Exception:
            pass

    ship_url = (
        "https://redsky.target.com/redsky_aggregations/v1/web/product_fulfillment_v1"
        f"?key={TARGET_KEY}&tcin=93620188&store_id=3269&zip=33139&state=FL"
        "&pricing_store_id=3269&has_pricing_store_id=true"
    )
    status, body = fetch(
        ship_url,
        headers={
            "Accept": "application/json",
            "Referer": "https://www.target.com/",
        },
    )
    if status == 200 and body:
        checked.add("target-ship")
        try:
            fulfillment = json.loads(body)["data"]["product"]["fulfillment"]
            shipping = fulfillment.get("shipping_options") or {}
            ship_state = shipping.get("availability_status") or ""
            ship_qty = float(shipping.get("available_to_promise_quantity") or 0)
            if open_status(ship_state) or ship_qty > 0:
                hits.append(
                    {
                        "id": "target-ship",
                        "click": TARGET,
                        "where": "Target, entrega, cerca de US$ 899",
                        "text": f"Target com entrega para endereco nos EUA. Preco de tabela, cerca de US$ 899,99. {TARGET}",
                    }
                )
            for loc in fulfillment.get("store_options") or []:
                add_store(hits, seen, loc)
            if fulfillment.get("store_options"):
                checked.add("target-store")
        except Exception:
            pass

    for zip_code in ("33186", "33172", "33133", "33181"):
        url = (
            "https://redsky.target.com/redsky_aggregations/v1/web/fiats_v1"
            f"?key={TARGET_KEY}&tcin=93620188&store_id=3269&zip={zip_code}&state=FL"
            "&latitude=25.7617&longitude=-80.1918&pricing_store_id=3269&has_pricing_store_id=true"
            "&visitor_id=0183B8C4D5E6F708192A3B4C5D6E7F80&channel=WEB&page=%2Fp%2FA-93620188"
            f"&nearby={zip_code}"
        )
        status, body = fetch(
            url,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.target.com/",
            },
        )
        if status != 200 or not body:
            continue
        checked.add("target-store")
        try:
            locations = json.loads(body)["data"]["fulfillment_fiats"]["locations"]
            for loc in locations or []:
                add_store(hits, seen, loc)
        except Exception:
            pass

    status, body = fetch(
        "https://www.walmart.com/ip/Sony-PlayStation-5-Pro-Console-PS5-Pro/18235967161",
        timeout=12,
    )
    if status == 200 and "sellerDisplayName" in body:
        checked.add("walmart")
        seller = ""
        match = re.search(r'sellerDisplayName":"([^"]+)"', body)
        if match:
            seller = match.group(1)
        price = 0.0
        index = body.find('sellerDisplayName":"Walmart')
        if index >= 0:
            window = body[max(0, index - 900) : index + 900]
            price_match = re.search(r'"price":(8\d\d(?:\.\d+)?|9[0-7]\d(?:\.\d+)?|980(?:\.0+)?)', window)
            if price_match:
                price = float(price_match.group(1))
        if seller.startswith("Walmart") and 0 < price <= MAX_PRICE:
            link = "https://www.walmart.com/ip/Sony-PlayStation-5-Pro-Console-PS5-Pro/18235967161"
            hits.append(
                {
                    "id": "walmart",
                    "click": link,
                    "where": f"Walmart, US$ {price:.2f}, entrega",
                    "text": (
                        f"Walmart vendida pela propria Walmart por US$ {price:.2f}. "
                        f"Pede entrega no checkout. {link}"
                    ),
                }
            )

    status, body = fetch("https://www.costco-stock.com/item/1793150/fl", timeout=15)
    if status == 200 and body:
        checked.add("costco")
        for row in re.finditer(
            r'<tr><td>(?P<wh>[^<]+)</td><td class="hide-sm">(?P<city>[^<]+)</td><td><span class="pill pill-(?:in|low)">',
            body,
        ):
            warehouse = row.group("wh")
            city = row.group("city")
            if not in_miami(warehouse, city):
                continue
            link = "https://www.costco.com/p/-/sony-playstation-5-pro-console-bundle/4000352765"
            slug = re.sub(r"[^a-z0-9]+", "-", warehouse.lower()).strip("-")
            hits.append(
                {
                    "id": f"costco-{slug}",
                    "click": link,
                    "where": f"Costco {warehouse} ({city}), cerca de US$ 950",
                    "text": (
                        f"Costco {warehouse} ({city}) com o pacote do PS5 Pro, cerca de US$ 950. "
                        f"Precisa de cadastro. Da para entregar ou retirar. {link}"
                    ),
                }
            )

    status, body = fetch("https://stockmaid.com/skus/6601524", timeout=15)
    if status == 200 and body:
        checked.add("bestbuy")
        if re.search(r"Current status:\s*In Stock", body):
            price_match = re.search(r"Current price:\s*\$([0-9.]+)", body)
            price = float(price_match.group(1)) if price_match else 0
            if 0 < price <= MAX_PRICE:
                link = "https://www.bestbuy.com/product/playstation-5-pro-console/JXHQ37TR86/sku/6601524"
                hits.append(
                    {
                        "id": "bestbuy-online",
                        "click": link,
                        "where": f"Best Buy online, US$ {price:.2f}, entrega",
                        "text": f"Best Buy online em estoque por US$ {price:.2f}. Pede entrega para o endereco deles. {link}",
                    }
                )

    return hits, checked


def flush_windows(state):
    for window in state["windows"].values():
        state["available"].append(window)
    state["windows"] = {}


def report_body(state):
    hours = state.get("hours") or {}
    if not hours or not state.get("checks"):
        return ""
    keys = sorted(int(hour) for hour in hours)
    slots = [f"{hour:02d}h {hours.get(f'{hour:02d}', 0)}" for hour in range(keys[0], keys[-1] + 1)]
    day = datetime.strptime(state["day"], "%Y-%m-%d")
    lines = [
        f"Relatorio {day.strftime('%d/%m')}, horario de Brasilia",
        f"{state['checks']} checagens, {state.get('first') or '?'} ate {state.get('last') or '?'}.",
        " ".join(slots),
    ]
    sources = state.get("sources") or {}
    source_bits = [
        f"{label} {sources.get(key, 0)}"
        for key, label in SOURCE_LABELS.items()
    ]
    lines.append("Consultas: " + ", ".join(source_bits) + ".")
    found = sorted(state.get("available") or [], key=lambda item: item.get("start") or "")
    if not found:
        lines.append("Disponivel: nenhum.")
    else:
        lines.append("Disponivel:")
        for window in found:
            start = window.get("start") or "?"
            end = window.get("end") or start
            when = start if start == end else f"{start}-{end}"
            lines.append(f"{when} {window.get('where') or 'loja'}")
    return "\n".join(lines)


def send_report(state):
    flush_windows(state)
    body = report_body(state)
    if not body:
        return
    print(body)
    notify(body, "", title="PS5 Pro relatorio", priority="min", tags="clipboard")


def roll_day(state, now_br):
    today = now_br.strftime("%Y-%m-%d")
    if state.get("day") == today:
        return
    if state.get("day") and state.get("checks"):
        send_report(state)
    seen = list(state.get("seen") or [])
    state.clear()
    state.update(empty_stats(today))
    state["seen"] = seen


def note_stock(state, hits, checked, stamp):
    current = {hit["id"]: hit for hit in hits}
    windows = state["windows"]
    for item_id, hit in current.items():
        where = hit.get("where") or hit["id"]
        if item_id in windows:
            windows[item_id]["end"] = stamp
            windows[item_id]["where"] = where
        else:
            windows[item_id] = {"where": where, "start": stamp, "end": stamp}
    for item_id in [item_id for item_id in windows if item_id not in current]:
        if source_of(item_id) not in checked:
            continue
        state["available"].append(windows.pop(item_id))


def record_check(state, now_br, checked):
    stamp = now_br.strftime("%H:%M")
    hour = now_br.strftime("%H")
    state["checks"] = int(state.get("checks") or 0) + 1
    if not state.get("first"):
        state["first"] = stamp
    state["last"] = stamp
    hours = state["hours"]
    hours[hour] = int(hours.get(hour) or 0) + 1
    sources = state["sources"]
    for source in checked:
        sources[source] = int(sources.get(source) or 0) + 1


def stop_forever():
    state = load_state()
    if state.get("checks"):
        send_report(state)
        state["checks"] = 0
        save_state(state)
    with open("ended.flag", "w", encoding="utf-8") as handle:
        handle.write("ended\n")
    notify(
        "O aviso do PS5 Pro parou em 16/11, 20h no horario de Miami.",
        "",
        title="PS5 Pro aviso",
        priority="default",
        tags="octagonal_sign",
    )
    if os.environ.get("GITHUB_ACTIONS") == "true":
        subprocess.run(["gh", "workflow", "disable", "check.yml"], check=False)
        subprocess.run(["gh", "workflow", "disable", "kick.yml"], check=False)
    print("ended")


def one_check():
    now_br = datetime.now(BR)
    state = load_state()
    roll_day(state, now_br)
    save_state(state)
    hits, checked = collect()
    previous = set(state.get("seen") or [])
    present = {hit["id"] for hit in hits}
    kept = {item_id for item_id in previous if source_of(item_id) not in checked}
    fresh = [hit for hit in hits if hit["id"] not in previous]
    state["seen"] = sorted(kept | present)
    record_check(state, now_br, checked)
    note_stock(state, hits, checked, now_br.strftime("%H:%M"))
    save_state(state)
    print(
        f"checked={','.join(sorted(checked))} hits={len(hits)} fresh={len(fresh)} "
        f"day={state['day']} checks={state['checks']} at={now_br.strftime('%H:%M:%S')}"
    )
    if fresh:
        body = "Compra agora, some em minutos.\n" + "\n".join(hit["text"] for hit in fresh)
        notify(body, fresh[0]["click"])


def main():
    run_for = int(os.environ.get("RUN_FOR", "0"))
    print(f"run_for={run_for}")
    deadline = time.time() + run_for
    while True:
        if datetime.now(ZoneInfo("America/New_York")) >= END:
            stop_forever()
            return 0
        if run_for > 0 and time.time() >= deadline:
            print("handoff")
            return 0
        started = time.time()
        one_check()
        if run_for <= 0:
            return 0
        remain = deadline - time.time()
        if remain < 5:
            print("handoff")
            return 0
        pause = 30 - (time.time() - started)
        if pause > remain:
            pause = remain
        if pause > 1:
            time.sleep(pause)


if __name__ == "__main__":
    raise SystemExit(main())
