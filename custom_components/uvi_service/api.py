"""Async Genero client. Never log bodies, URLs, headers or credentials."""

import asyncio
import base64
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.parse import urlencode

import aiohttp

from .const import FIELDS, MONTHS

BASE = "https://uvi-service.de/gas/ua"
CLIENT = "GBC/1.00.60.sample-202402060817"


class CannotConnect(Exception):
    """The service could not be reached or its protocol changed."""


class InvalidAuth(Exception):
    """The service did not open the consumption screen."""


def nodes(body):
    """Parse nested protocol lists, respecting braces inside quoted strings."""
    root = []
    stack = [root]
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+', body):
        token = match.group()
        if token == "{":
            child = []
            stack[-1].append(child)
            stack.append(child)
        elif token == "}":
            if len(stack) == 1:
                raise CannotConnect("Invalid protocol structure")
            stack.pop()
        elif token.startswith('"'):
            # Genero uses JSON-compatible escaping in the captured protocol.
            stack[-1].append(json.loads(token))
        else:
            stack[-1].append(token)
    if len(stack) != 1:
        raise CannotConnect("Incomplete protocol structure")
    return root


def walk(tree):
    yield tree
    for child in tree:
        if isinstance(child, list):
            yield from walk(child)


def attributes(node):
    if len(node) < 3 or not isinstance(node[2], list):
        return {}
    return {item[0]: item[1] for item in node[2]
            if isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)}


def apply_response(body, state):
    """Merge the full initial form and subsequent deltas into one UI state."""
    labels = []
    for node in walk(nodes(body)):
        if not node or not isinstance(node[0], str):
            continue
        attrs = attributes(node)
        if node[0] in ("FormField", "un") and len(node) > 1:
            key = FIELDS.get(int(node[1]))
            if key and "value" in attrs:
                state[key] = attrs["value"]
        if node[0] == "Item" and attrs.get("name"):
            label = attrs["name"]
            if re.fullmatch(r"(?:" + "|".join(MONTHS) + r") \d{4}", label):
                labels.append(label)
    return list(dict.fromkeys(labels))


def record(state):
    label = state.get("month", "")
    try:
        name, year = label.split()
        result = {"month": date(int(year), MONTHS.index(name) + 1, 1).isoformat()}
        for key in FIELDS.values():
            if key == "month":
                continue
            raw = state.get(key, "").strip()
            result[key] = str(Decimal(raw.replace(".", "").replace(",", "."))) if raw else None
        warm = result["warmwater_kwh"]
        result["warmwater_m3"] = str((Decimal(warm) / Decimal("58.15")).quantize(Decimal("0.001"))) if warm is not None else None
        return result
    except (ValueError, InvalidOperation) as exc:
        raise CannotConnect("Invalid consumption data") from exc


def quote(value):
    return json.dumps(value, ensure_ascii=False)


class UviApi:
    """One isolated cookie session per refresh; requests stay sequential."""

    def __init__(self, credentials):
        self.credentials = credentials

    async def fetch(self):
        args = [("Arg", base64.b64encode(self.credentials[key].encode()).decode())
                for key in ("property_id", "email")]
        if token := self.credentials.get("launch_token"):
            args.append(("djxkaiemglvvihukvsobuyiyby", token))
        launch = f"{BASE}/r/vds-witter?{urlencode(args)}"
        headers = {"X-FourJs-Client": CLIENT, "X-FourJs-Client-Features": "prompt",
                   "Referer": launch, "Origin": "https://uvi-service.de"}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45), headers=headers) as session:
                async def request(url, body=None):
                    async with session.request("GET" if body is None else "POST", url, data=body,
                                               headers={"Content-Type": "text/plain;charset=UTF-8"}) as response:
                        if response.status in (401, 403):
                            raise InvalidAuth("Access denied")
                        if response.status != 200:
                            raise CannotConnect("Unexpected HTTP status")
                        text = await response.text()
                        return text, response.headers.get("X-FourJs-Id")

                await request(launch)
                _, session_id = await request(launch + "&Bootstrap=done")
                if not session_id or not re.fullmatch(r"[a-fA-F0-9]+", session_id):
                    raise CannotConnect("Missing session identifier")
                page = 0
                om = None

                async def post(body):
                    nonlocal page, om
                    page += 1
                    text, _ = await request(f"{BASE}/sua/{session_id}?appId=0&pageId={page}", body + "\n")
                    match = re.match(r"\s*om (\d+)", text)
                    if not match:
                        raise CannotConnect("Missing response counter")
                    om = int(match[1])
                    return text

                await post('meta Client{{name "GBC"}{version "1.00.60.sample"}{encoding "UTF-8"}{encapsulation "0"}{filetransfer "0"}{mobileUI "0"}}')
                await post('event _om %d{}{{FunctionCallEvent 0{{result "0"}}{{FunctionCallReturn 0{{dataType "STRING"}{isNull "0"}{value "OSX"}}{}}}}}' % om)
                await post('event _om %d{}{{FunctionCallEvent 0{{result "0"}}{}}}' % om)
                await post('event _om %d{}{{ConfigureEvent 0{{idRef "40"}{cursor "0"}{cursor2 "-1"}}}}' % om)
                password = self.credentials["password"]
                login = await post('event _om %d{}{{ConfigureEvent 0{{idRef "40"}{cursor "%d"}{cursor2 "%d"}}}{ConfigureEvent 0{{idRef "40"}{value %s}}}{ActionEvent 0{{idRef "37"}}}}' % (om, len(password), len(password), quote(password)))
                state = {}
                months = apply_response(login, state)
                if not months or "month" not in state:
                    raise InvalidAuth("Login did not return consumption data")
                records = {state["month"]: record(state)}
                for month in months:
                    if month in records:
                        continue
                    body = await post('event _om %d{}{{ConfigureEvent 0{{idRef "3"}{value %s}}}}' % (om, quote(month)))
                    apply_response(body, state)
                    if state.get("month") != month:
                        raise CannotConnect("Month change was not confirmed")
                    records[month] = record(state)
                return sorted(records.values(), key=lambda row: row["month"])
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise CannotConnect("Service request failed") from None
