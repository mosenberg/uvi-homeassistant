#!/usr/bin/env python3

import argparse
import base64
import csv
import gzip
import http.cookiejar
import json
import logging
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
FOURJS_CLIENT = "GBC/1.00.60.sample-202402060817"
DEFAULT_LANGUAGE = "en-US,en;q=0.9,de;q=0.8"

VALUE_RE = re.compile(r'\{un (\d+) \{\{value "((?:[^"\\]|\\.)*)"\}\}\}')
COLOR_RE = re.compile(r'\{un (\d+) \{\{color "([^"]+)"\}\}\}')
OM_RE = re.compile(r"^om (\d+)")
MONTH_ITEM_RE = re.compile(r'\{Item \d+ \{\{name "([^"]+)"\} \{text "[^"]+"\}\} \{\}\}')

UN_LABELS = {
    3: "month",
    65: "warmwater_kwh",
    85: "heating_kwh",
    605: "coldwater_m3",
}
EXPORTED_UN_KEYS = {3, 65, 85, 605}
OUTPUT_COLUMNS = [
    "month",
    "coldwater_m3",
    "heating_kwh",
    "warmwater_kwh",
    "warmwater_m3",
]
CORE_OUTPUT_COLUMNS = [
    "month",
    "coldwater_m3",
    "heating_kwh",
    "warmwater_kwh",
]
WARMWATER_KWH_PER_M3 = Decimal("1.163") * Decimal("50")
GERMAN_MONTHS = {
    "Januar": 1,
    "Februar": 2,
    "März": 3,
    "April": 4,
    "Mai": 5,
    "Juni": 6,
    "Juli": 7,
    "August": 8,
    "September": 9,
    "Oktober": 10,
    "November": 11,
    "Dezember": 12,
}


class UVIError(RuntimeError):
    pass


LOGGER = logging.getLogger("uvi_downloader")


@dataclass
class ResponseData:
    status: int
    headers: Dict[str, str]
    body: str


class UVIClient:
    def __init__(self, launch_url: str, timeout: int = 30) -> None:
        self.launch_url = launch_url
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.sua_id: Optional[str] = None
        self.referer_url = launch_url

    def _request(
        self,
        url: str,
        *,
        method: str,
        body: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> ResponseData:
        headers = {
            "Accept-Language": DEFAULT_LANGUAGE,
            "User-Agent": USER_AGENT,
        }
        if extra_headers:
            headers.update(extra_headers)

        data = body.encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw_body = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
                if encoding == "gzip":
                    raw_body = gzip.decompress(raw_body)
                elif encoding == "deflate":
                    raw_body = zlib.decompress(raw_body)
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw_body.decode(charset, errors="replace")
                return ResponseData(
                    status=response.getcode(),
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=text,
                )
        except urllib.error.HTTPError as exc:
            exc.close()
            raise UVIError(f"Portal request failed with HTTP {exc.code}.") from None
        except urllib.error.URLError:
            raise UVIError("Could not reach the portal.") from None

    def initial_load(self) -> str:
        LOGGER.info("Initial load started")
        response = self._request(
            self.launch_url,
            method="GET",
            extra_headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8,"
                    "application/signed-exchange;v=b3;q=0.7"
                ),
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
        )
        LOGGER.info("Initial load completed, body_length=%d", len(response.body))
        return response.body

    def bootstrap(self) -> str:
        LOGGER.info("Bootstrap started")
        parts = urllib.parse.urlsplit(self.launch_url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query.append(("Bootstrap", "done"))
        bootstrap_url = urllib.parse.urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urllib.parse.urlencode(query),
                parts.fragment,
            )
        )
        response = self._request(
            bootstrap_url,
            method="GET",
            extra_headers={
                "Accept": "application/octet-stream",
                "Referer": self.launch_url,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "X-FourJs-Client": FOURJS_CLIENT,
                "X-FourJs-Client-Features": "prompt",
                "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
        )
        self.sua_id = response.headers.get("x-fourjs-id")
        if not self.sua_id:
            raise UVIError("Bootstrap response did not contain X-FourJs-Id.")
        LOGGER.info(
            "Bootstrap completed, session_initialized=%s, body_length=%d",
            bool(self.sua_id),
            len(response.body),
        )
        return response.body

    def post_sua(self, page_id: int, body: str) -> str:
        if not self.sua_id:
            raise UVIError("sua session is not initialized yet.")
        url = f"https://uvi-service.de/gas/ua/sua/{self.sua_id}?appId=0&pageId={page_id}"
        LOGGER.info(
            "POST sua request, page_id=%d, body_summary=%s",
            page_id,
            summarize_request_body(body),
        )
        response = self._request(
            url,
            method="POST",
            body=body,
            extra_headers={
                "Accept": "*/*",
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": "https://uvi-service.de",
                "Referer": self.launch_url,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "X-FourJs-Client": FOURJS_CLIENT,
                "X-FourJs-Client-Features": "prompt",
                "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
        )
        LOGGER.info(
            "POST sua response, page_id=%d, body_length=%d, om=%s",
            page_id,
            len(response.body),
            safe_parse_om(response.body),
        )
        return response.body

    def open_login_dialog(self) -> str:
        LOGGER.info("Opening login dialog")
        self.post_sua(
            1,
            'meta Client{{name "GBC"}{version "1.00.60.sample"}{encoding "UTF-8"}'
            '{encapsulation "0"}{filetransfer "0"}{mobileUI "0"}}\n',
        )
        self.post_sua(
            2,
            'event _om 0{}{{FunctionCallEvent 0{{result "0"}}'
            '{{FunctionCallReturn 0{{dataType "STRING"}{isNull "0"}{value "OSX"}}{}}}}}\n',
        )
        return self.post_sua(3, 'event _om 1{}{{FunctionCallEvent 0{{result "0"}}{}}}\n')

    def login(
        self,
        password: str,
        *,
        liegenschaft_id: Optional[str] = None,
        login_email: Optional[str] = None,
    ) -> str:
        # The original captured login request only sends the password field plus
        # the login button action. Liegenschaft and email are already encoded in
        # the launch URL and appear to be pre-filled/known to the backend.
        # We keep the intermediate focus step because it produced `om 3` in an
        # earlier trace and likely mirrors the browser moving into the password
        # field before submit.
        focus_body = 'event _om 2{}{{ConfigureEvent 0{{idRef "40"}{cursor "0"}{cursor2 "-1"}}}}\n'
        focus_response = self.post_sua(4, focus_body)
        if focus_response.strip():
            parse_om(focus_response)
        LOGGER.info("Login pre-focus step completed")

        body = (
            'event _om 3{}{{ConfigureEvent 0{{idRef "40"}{cursor "%d"}{cursor2 "%d"}}}'
            '{ConfigureEvent 0{{idRef "40"}{value "%s"}}}{ActionEvent 0{{idRef "37"}}}}\n'
            % (len(password), len(password), escape_genero_string(password))
        )
        LOGGER.info(
            "Submitting login, liegenschaft_supplied=%s, email_supplied=%s",
            bool(liegenschaft_id),
            bool(login_email),
        )
        return self.post_sua(5, body)

    def fetch_month(self, month_label: str, current_om: int) -> str:
        page_id = current_om + 2
        LOGGER.info("Fetching month=%s with current_om=%d page_id=%d", month_label, current_om, page_id)
        body = (
            'event _om %d{}{{ConfigureEvent 0{{idRef "3"}{value "%s"}}}}\n'
            % (current_om, escape_genero_string(month_label))
        )
        return self.post_sua(page_id, body)


def escape_genero_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def parse_om(body: str) -> int:
    normalized = body.lstrip("\ufeff\r\n\t ")
    match = OM_RE.search(normalized)
    if not match:
        raise UVIError("Could not find leading om counter in portal response.")
    return int(match.group(1))


def safe_parse_om(body: str) -> Optional[int]:
    try:
        return parse_om(body)
    except UVIError:
        return None


def parse_available_months(body: str) -> List[str]:
    seen = []
    for month in MONTH_ITEM_RE.findall(body):
        if month not in seen:
            seen.append(month)
    LOGGER.info("Parsed available months, count=%d", len(seen))
    return seen


def parse_decimal(value: str) -> Decimal:
    normalized = value.replace(".", "").replace(",", ".")
    return Decimal(normalized)


def parse_month_payload(body: str) -> Dict[str, object]:
    data: Dict[str, object] = {}

    for un_id, raw in VALUE_RE.findall(body):
        un_key = int(un_id)
        if un_key not in EXPORTED_UN_KEYS:
            continue
        value = raw.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        key = UN_LABELS.get(un_key, f"un_{un_key}")
        if un_key in {65, 85, 605}:
            data[key] = str(parse_decimal(value))
        else:
            data[key] = value

    LOGGER.info(
        "Parsed month payload, month=%s, keys=%d, has_heating=%s, has_warmwater=%s, has_coldwater=%s",
        data.get("month"),
        len(data),
        "heating_kwh" in data,
        "warmwater_kwh" in data,
        "coldwater_m3" in data,
    )
    return normalize_record(data)


def decimal_to_string(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.001"))
    return format(normalized, "f")


def month_label_to_iso_date(label: str) -> str:
    parts = label.split()
    if len(parts) != 2 or parts[0] not in GERMAN_MONTHS:
        raise UVIError(f"Could not convert month label to ISO date: {label!r}")
    year = int(parts[1])
    month = GERMAN_MONTHS[parts[0]]
    return f"{year:04d}-{month:02d}-01"


def normalize_record(data: Dict[str, object]) -> Dict[str, object]:
    result: Dict[str, object] = {}

    month = data.get("month")
    coldwater_m3 = data.get("coldwater_m3")
    heating_kwh = data.get("heating_kwh")
    warmwater_kwh = data.get("warmwater_kwh")

    if month is not None:
        result["month"] = month_label_to_iso_date(str(month))
    if coldwater_m3 is not None:
        result["coldwater_m3"] = coldwater_m3
    if heating_kwh is not None:
        result["heating_kwh"] = heating_kwh
    if warmwater_kwh is not None:
        result["warmwater_kwh"] = warmwater_kwh
        result["warmwater_m3"] = decimal_to_string(
            Decimal(str(warmwater_kwh)) / WARMWATER_KWH_PER_M3
        )

    return result


def has_complete_core_values(record: Dict[str, object]) -> bool:
    return all(record.get(column) not in (None, "") for column in CORE_OUTPUT_COLUMNS)


def planned_fetch_order(months: List[str], available_months: List[str]) -> List[str]:
    if len(months) < 2:
        return months

    current_selected = available_months[0] if available_months else None
    if months[0] == current_selected:
        return months[1:] + [months[0]]

    return months


def encode_arg(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def build_launch_url(
    *,
    liegenschaft_id: str,
    login_email: str,
    launch_token: str,
) -> str:
    query = urllib.parse.urlencode(
        [
            ("Arg", encode_arg(liegenschaft_id)),
            ("Arg", encode_arg(login_email)),
            ("djxkaiemglvvihukvsobuyiyby", launch_token),
        ]
    )
    return f"https://uvi-service.de/gas/ua/r/vds-witter?{query}"


def summarize_request_body(body: str) -> str:
    """Summarize event counts without including any raw request content."""
    return (
        f"configure_events={body.count('{ConfigureEvent ')} "
        f"action_events={body.count('{ActionEvent ')} "
        f"function_events={body.count('{FunctionCallEvent ')}"
    )


def configure_logging(debug: bool, debug_log: Optional[str]) -> None:
    level = logging.INFO if debug else logging.WARNING
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)] if debug else []

    if debug_log:
        handlers.append(logging.FileHandler(debug_log, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def write_csv(path: str, rows: List[Dict[str, object]]) -> None:
    columns = [column for column in OUTPUT_COLUMNS if any(column in row for row in rows)]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download monthly heating and water usage data from uvi-service.de"
    )
    source_group = parser.add_argument_group("launch source")
    source_group.add_argument(
        "--launch-url",
        help="Full vds-witter launch URL including Arg parameters and token.",
    )
    source_group.add_argument(
        "--liegenschaft-id",
        help="Plain property id. Will be base64-encoded into the first Arg parameter.",
    )
    source_group.add_argument(
        "--login-email",
        help="Portal login email. Will be base64-encoded into the second Arg parameter.",
    )
    source_group.add_argument(
        "--launch-token",
        help="Value of the long token parameter djxkaiemglvvihukvsobuyiyby.",
    )
    parser.add_argument(
        "--password",
        required=True,
        help="Portal password.",
    )
    parser.add_argument(
        "--month",
        action="append",
        dest="months",
        help='Month label exactly as shown by the portal, e.g. "Januar 2026". Can be repeated.',
    )
    parser.add_argument(
        "--all-months",
        action="store_true",
        help="Download all available months from the post-login dropdown.",
    )
    parser.add_argument(
        "--out",
        help="Optional output file. Defaults to stdout as JSON.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable redacted debug logging to stderr.",
    )
    parser.add_argument(
        "--debug-log",
        help="Optional path for a redacted debug log file.",
    )
    return parser.parse_args()


def resolve_launch_url(args: argparse.Namespace) -> str:
    if args.launch_url:
        return args.launch_url

    required = {
        "--liegenschaft-id": args.liegenschaft_id,
        "--login-email": args.login_email,
        "--launch-token": args.launch_token,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise UVIError(
            "Either --launch-url or all of %s must be provided."
            % ", ".join(required.keys())
        )

    return build_launch_url(
        liegenschaft_id=args.liegenschaft_id,
        login_email=args.login_email,
        launch_token=args.launch_token,
    )


def main() -> int:
    args = parse_args()
    configure_logging(args.debug, args.debug_log)

    if not args.all_months and not args.months:
        print("Either --month or --all-months is required.", file=sys.stderr)
        return 2

    try:
        launch_url = resolve_launch_url(args)
        LOGGER.info(
            "Starting run, launch_mode=%s, all_months=%s, explicit_month_count=%d, output_format=%s",
            "launch-url" if args.launch_url else "component-args",
            args.all_months,
            len(args.months or []),
            args.format,
        )
        client = UVIClient(launch_url)
        client.initial_load()
        client.bootstrap()
        client.open_login_dialog()
        login_body = client.login(
            args.password,
            liegenschaft_id=args.liegenschaft_id,
            login_email=args.login_email,
        )
        current_om = parse_om(login_body)
        available_months = parse_available_months(login_body)
        LOGGER.info(
            "Login finished, current_om=%d, available_month_count=%d, first_months=%s",
            current_om,
            len(available_months),
            available_months[:5],
        )
        if args.all_months and not available_months:
            raise UVIError(
                "Login returned no month list. "
                "Run again with --debug and inspect the login response handling."
            )

        months = available_months if args.all_months else args.months
        assert months is not None

        missing_months = [month for month in months if month not in available_months]
        if missing_months:
            raise UVIError(
                "Unknown month label(s): %s" % ", ".join(missing_months)
            )

        login_record = parse_month_payload(login_body)
        login_month = login_record.get("month")
        use_login_record = has_complete_core_values(login_record)
        LOGGER.info(
            "Login payload completeness, month=%s, complete=%s, keys=%s",
            login_month,
            use_login_record,
            sorted(login_record.keys()),
        )

        fetch_order = planned_fetch_order(list(months), available_months)
        LOGGER.info("Planned fetch order starts with=%s", fetch_order[:5])

        rows_by_month: Dict[str, Dict[str, object]] = {}
        for month in fetch_order:
            if month == login_month and use_login_record:
                LOGGER.info("Using login response payload for month=%s", month)
                row = login_record
            else:
                response = client.fetch_month(month, current_om)
                current_om = parse_om(response)
                row = parse_month_payload(response)
            rows_by_month[month] = row

        rows = [rows_by_month.get(month, {"month": month}) for month in months]
        LOGGER.info("Finished download, rows=%d", len(rows))
    except UVIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.format == "csv":
        if args.out:
            write_csv(args.out, rows)
        else:
            columns = [column for column in OUTPUT_COLUMNS if any(column in row for row in rows)]
            writer = csv.DictWriter(sys.stdout, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    else:
        payload = json.dumps(rows, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
        else:
            print(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
