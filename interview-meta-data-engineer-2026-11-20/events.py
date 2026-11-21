"""Clickstream event schema, validation and a realistic generator.

One event is one thing a user did in the product: viewed a page,
clicked a button, started checkout, completed a purchase. Every event
carries the same envelope (event_id, event_type, user_id, session_id,
product, page, ts) plus a small properties bag for type specific data.

The schema is the contract between the apps that produce events and
the pipeline that consumes them. Validation at ingestion is what keeps
one bad client release from poisoning the analytics.
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

EVENT_TYPES = ["page_view", "click", "add_to_cart", "checkout_start", "purchase"]
PRODUCTS = ["web", "ios", "android"]
PAGES = ["/home", "/pricing", "/features", "/blog", "/docs",
         "/product/shoes", "/product/jacket", "/cart", "/checkout", "/account"]

# field name -> (python type, required)
SCHEMA = {
    "event_id": (str, True),
    "event_type": (str, True),
    "user_id": (str, True),
    "session_id": (str, True),
    "product": (str, True),
    "page": (str, True),
    "ts": (str, True),          # ISO 8601 UTC, for example 2026-11-20T14:03:11Z
    "properties": (dict, False),
}


def validate_event(event: dict) -> list[str]:
    """Return a list of problems with the event. Empty means valid."""
    problems: list[str] = []
    if not isinstance(event, dict):
        return ["event is not an object"]
    for name, (typ, required) in SCHEMA.items():
        if name not in event:
            if required:
                problems.append(f"missing field: {name}")
            continue
        if not isinstance(event[name], typ):
            problems.append(f"field {name} must be {typ.__name__}")
    if event.get("event_type") not in EVENT_TYPES:
        problems.append(f"unknown event_type: {event.get('event_type')}")
    if event.get("product") not in PRODUCTS:
        problems.append(f"unknown product: {event.get('product')}")
    ts = event.get("ts")
    if isinstance(ts, str):
        try:
            datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            problems.append("ts is not ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ)")
    return problems


def make_event(rng: random.Random, when: datetime, user_pool: int = 5000) -> dict:
    """Generate one plausible event. A simple funnel model makes the
    demo data behave like a real product: many views, fewer clicks,
    fewer carts, very few purchases."""
    user_num = rng.randrange(user_pool)
    roll = rng.random()
    if roll < 0.55:
        event_type = "page_view"
    elif roll < 0.80:
        event_type = "click"
    elif roll < 0.90:
        event_type = "add_to_cart"
    elif roll < 0.97:
        event_type = "checkout_start"
    else:
        event_type = "purchase"
    props: dict = {}
    if event_type == "purchase":
        props = {"revenue_usd": round(rng.uniform(19.0, 240.0), 2),
                 "currency": "USD"}
    elif event_type == "click":
        props = {"element": rng.choice(["cta_buy", "nav_pricing", "hero_video",
                                        "docs_link", "signup_button"])}
    return {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "user_id": f"user-{user_num}",
        "session_id": f"sess-{user_num}-{when.strftime('%Y%m%d%H')}",
        "product": rng.choice(PRODUCTS),
        "page": rng.choice(PAGES),
        "ts": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "properties": props,
    }


def generate(count: int, start: datetime, span_minutes: int = 60,
             seed: int = 42) -> list[dict]:
    """Generate count events spread over span_minutes from start."""
    rng = random.Random(seed)
    events = []
    for _ in range(count):
        when = start + timedelta(seconds=rng.randrange(span_minutes * 60))
        events.append(make_event(rng, when))
    events.sort(key=lambda e: e["ts"])
    return events
