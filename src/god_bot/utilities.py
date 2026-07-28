from __future__ import annotations

import ast
import hashlib
import ipaddress
import json
import math
import operator
import os
import random
import re
import secrets
import shlex
import shutil
import socket
import ssl
import string
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class CalculationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class UtilityCommand:
    name: str
    argument: str


_COMMAND_RE = re.compile(
    r"^(help|status|pc|unit|hash|lisp|tls|password|地震|アメダス|天気|calc|ping|whois|ip|"
    r"roll|choice|dns|qr|文字数|名言|裁判|おみくじ|連想|要約)"
    r"(?:\s+(.*))?$",
    re.IGNORECASE,
)
_FORECAST_DAY_RE = re.compile(r"^(.*?)\s+(今日|明日|明後日|今週|来週)$")
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$",
    re.IGNORECASE,
)
_DICE_RE = re.compile(
    r"^(?:(\d{1,3})[dD])(\d{1,7})(?:\s*([+-])\s*(\d{1,7}))?$"
)

HELP_TEXT = """**神様 コマンド**

**基本**
`help` — この一覧
`status` — 神様の稼働状態
`pc` — ホストPCの状態
`ping` — 応答確認と遅延
`calc (12 + 3) * 4` — 計算
`unit 10 km mile` — 単位変換
`hash sha256 文字列` — ハッシュ計算
`文字数 文章` — 文字数・行数・バイト数
`qr 文字列` — QRコード画像
`password` / `password 32` — パスワード生成
`lisp (+ 1 (* 2 3))` — 安全なミニLisp
`roll` / `roll 20` / `roll 2d6` — サイコロ（省略時は1d100）
`choice ラーメン 寿司 カレー` — ランダム選択

**情報**
`地震` — 気象庁の最新地震情報
`アメダス 静岡県 気温` — 地域別の観測画像
　要素: 気温／降水／風／日照／湿度
`天気 浜松` — 現在の天気
`天気 浜松 明日` — 今日／明日／明後日の予報
`天気 浜松 今週` — 今週／来週の予報
`dns example.com` — A・AAAA・MX
`tls example.com` — TLS証明書と期限
`whois example.com` — ドメイン登録情報
`ip 8.8.8.8` — 公開IP割り当て情報

**学習系**
`名言` — 記憶から怪しい名言
`裁判 猫 犬` — 学習語で雑に判決
`おみくじ` — 学習単語のおみくじ
`連想 猫` — 近い学習単語
`要約 今日` — 今日の記憶を雑に要約

**記憶管理（スラッシュコマンド）**
`/memory status` — 学習件数
`/memory forget-me` — 自分の発言を忘却
`/memory purge` — 全消去（管理者）"""

_UNIT_FACTORS: dict[str, tuple[str, float]] = {
    "mm": ("length", 0.001),
    "cm": ("length", 0.01),
    "m": ("length", 1.0),
    "km": ("length", 1_000.0),
    "in": ("length", 0.0254),
    "inch": ("length", 0.0254),
    "ft": ("length", 0.3048),
    "feet": ("length", 0.3048),
    "yd": ("length", 0.9144),
    "mile": ("length", 1_609.344),
    "mi": ("length", 1_609.344),
    "mg": ("mass", 0.000001),
    "g": ("mass", 0.001),
    "kg": ("mass", 1.0),
    "oz": ("mass", 0.028349523125),
    "lb": ("mass", 0.45359237),
    "s": ("time", 1.0),
    "sec": ("time", 1.0),
    "min": ("time", 60.0),
    "h": ("time", 3_600.0),
    "hour": ("time", 3_600.0),
    "day": ("time", 86_400.0),
    "b": ("data", 1.0),
    "kb": ("data", 1_000.0),
    "mb": ("data", 1_000_000.0),
    "gb": ("data", 1_000_000_000.0),
    "tb": ("data", 1_000_000_000_000.0),
    "kib": ("data", 1_024.0),
    "mib": ("data", 1_048_576.0),
    "gib": ("data", 1_073_741_824.0),
}
_TEMPERATURE_UNITS = {"c", "f", "k"}
_HASH_ALGORITHMS = {"sha256", "sha512", "sha1", "md5"}
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_WEATHER_LABELS = {
    0: "快晴",
    1: "ほぼ晴れ",
    2: "一部くもり",
    3: "くもり",
    45: "霧",
    48: "着氷性の霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    56: "弱い着氷性の霧雨",
    57: "強い着氷性の霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    66: "弱い着氷性の雨",
    67: "強い着氷性の雨",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    77: "霧雪",
    80: "弱いにわか雨",
    81: "にわか雨",
    82: "激しいにわか雨",
    85: "弱いにわか雪",
    86: "強いにわか雪",
    95: "雷雨",
    96: "ひょうを伴う雷雨",
    99: "激しいひょうを伴う雷雨",
}


def parse_utility_command(text: str) -> UtilityCommand | None:
    normalized = unicodedata.normalize("NFKC", text).strip()
    match = _COMMAND_RE.fullmatch(normalized)
    if match is None:
        return None
    name = match.group(1).lower()
    argument = (match.group(2) or "").strip()
    return UtilityCommand(name=name, argument=argument)


def text_stats(text: str) -> str:
    if not text:
        return "例: `文字数 ここに数えたい文章`"
    characters = len(text)
    without_whitespace = sum(not char.isspace() for char in text)
    lines = len(text.splitlines()) or 1
    utf8_bytes = len(text.encode("utf-8"))
    return (
        f"文字数: {characters}\n"
        f"空白除外: {without_whitespace}\n"
        f"行数: {lines}\n"
        f"UTF-8: {utf8_bytes}バイト"
    )


def generate_password(expression: str) -> str:
    expression = unicodedata.normalize("NFKC", expression).strip()
    if not expression:
        length = 20
    else:
        try:
            length = int(expression)
        except ValueError:
            return "例: `password` または `password 32`"
    if not 8 <= length <= 128:
        return "長さは8〜128文字にしてね。"

    groups = (
        string.ascii_lowercase,
        string.ascii_uppercase,
        string.digits,
        "!@#$%^&*()-_=+",
    )
    password = [secrets.choice(group) for group in groups]
    alphabet = "".join(groups)
    password.extend(
        secrets.choice(alphabet) for _ in range(length - len(password))
    )
    secrets.SystemRandom().shuffle(password)
    return (
        f"🔐 `{''.join(password)}`\n"
        f"{length}文字（英大文字・英小文字・数字・記号）"
    )


def _certificate_name(
    values: object,
    *wanted_keys: str,
) -> str | None:
    if not isinstance(values, tuple):
        return None
    found: dict[str, str] = {}
    for rdn in values:
        if not isinstance(rdn, tuple):
            continue
        for item in rdn:
            if (
                isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], str)
            ):
                found[item[0]] = item[1]
    return next((found[key] for key in wanted_keys if key in found), None)


def tls_certificate_info(raw_domain: str) -> str:
    domain = unicodedata.normalize("NFKC", raw_domain).strip().rstrip(".")
    if not domain or "/" in domain or ":" in domain:
        return "例: `tls example.com`"
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return "ドメイン名を読み取れなかったよ。"
    if not _DOMAIN_RE.fullmatch(ascii_domain):
        return "例: `tls example.com`"

    try:
        address_info = socket.getaddrinfo(
            ascii_domain,
            443,
            type=socket.SOCK_STREAM,
        )
        addresses = sorted({item[4][0] for item in address_info})
        parsed_addresses = [ipaddress.ip_address(value) for value in addresses]
        if not parsed_addresses or any(
            not address.is_global for address in parsed_addresses
        ):
            return "公開IPへ接続するドメインだけ指定してね。"

        context = ssl.create_default_context()
        with socket.create_connection(
            (addresses[0], 443),
            timeout=8,
        ) as connection:
            with context.wrap_socket(
                connection,
                server_hostname=ascii_domain,
            ) as tls_connection:
                certificate = tls_connection.getpeercert()
                tls_version = tls_connection.version() or "不明"
                cipher_info = tls_connection.cipher()
                cipher = cipher_info[0] if cipher_info else "不明"

        expires_text = certificate.get("notAfter")
        if not isinstance(expires_text, str):
            return "証明書の有効期限を読み取れなかったよ。"
        expires_at = datetime.fromtimestamp(
            ssl.cert_time_to_seconds(expires_text),
            tz=timezone.utc,
        )
        remaining_seconds = (
            expires_at - datetime.now(timezone.utc)
        ).total_seconds()
        if remaining_seconds < 0:
            remaining = f"期限切れ（{abs(math.floor(remaining_seconds / 86_400))}日前）"
        else:
            remaining = f"残り{math.ceil(remaining_seconds / 86_400)}日"
        issuer = _certificate_name(
            certificate.get("issuer"),
            "organizationName",
            "commonName",
        ) or "不明"
        subject = _certificate_name(
            certificate.get("subject"),
            "commonName",
            "organizationName",
        ) or ascii_domain
        alternative_names = certificate.get("subjectAltName")
        san_count = (
            sum(
                1
                for item in alternative_names
                if isinstance(item, tuple) and item[0] == "DNS"
            )
            if isinstance(alternative_names, tuple)
            else 0
        )
        return (
            f"**TLS: {domain}**\n"
            f"対象: {subject}\n"
            f"発行者: {issuer}\n"
            f"期限: {expires_at:%Y-%m-%d %H:%M} UTC（{remaining}）\n"
            f"DNS名: {san_count}件\n"
            f"接続: {tls_version} / {cipher}"
        )
    except ssl.SSLCertVerificationError:
        return "証明書の検証に失敗したよ。期限切れや名前の不一致かもしれない。"
    except (OSError, ValueError):
        return "TLS接続または証明書の取得に失敗したよ。"


def _evaluate_node(node: ast.AST, *, depth: int = 0) -> int | float:
    if depth > 16:
        raise CalculationError("式が複雑すぎるよ")
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(
            node.value, (int, float)
        ):
            raise CalculationError("数字と演算子だけ使ってね")
        value = node.value
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left, depth=depth + 1)
        right = _evaluate_node(node.right, depth=depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise CalculationError("指数が大きすぎるよ")
        try:
            value = _BINARY_OPERATORS[type(node.op)](left, right)
        except ZeroDivisionError as error:
            raise CalculationError("0では割れないよ") from error
        except (OverflowError, ValueError) as error:
            raise CalculationError("その計算は大きすぎるよ") from error
    elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        value = _UNARY_OPERATORS[type(node.op)](
            _evaluate_node(node.operand, depth=depth + 1)
        )
    else:
        raise CalculationError("使えるのは + - * / // % ** と括弧だよ")

    if isinstance(value, complex) or not math.isfinite(float(value)):
        raise CalculationError("その計算結果は扱えないよ")
    if abs(value) > 1e100:
        raise CalculationError("計算結果が大きすぎるよ")
    return value


def calculate(expression: str) -> str:
    normalized = unicodedata.normalize("NFKC", expression).strip()
    normalized = normalized.replace("×", "*").replace("÷", "/")
    normalized = normalized.replace("^", "**")
    if not normalized:
        raise CalculationError("例: `calc (12 + 3) * 4`")
    if len(normalized) > 120:
        raise CalculationError("式が長すぎるよ")
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as error:
        raise CalculationError("式を読み取れなかったよ") from error
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise CalculationError("式が複雑すぎるよ")
    value = _evaluate_node(tree.body)
    if isinstance(value, int):
        return str(value)
    if value.is_integer():
        return str(int(value))
    return format(value, ".12g")


def _get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> object:
    request_headers = {"User-Agent": "God-Discord-Bot/0.1"}
    request_headers.update(headers or {})
    request = Request(
        url,
        headers=request_headers,
    )
    with urlopen(request, timeout=8) as response:
        return json.load(response)


def _find_place(city: str) -> dict[str, object] | None:
    geocoding_url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
        {
            "name": city,
            "count": 1,
            "language": "ja",
            "format": "json",
        }
    )
    place_data = _get_json(geocoding_url)
    results = (
        place_data.get("results")
        if isinstance(place_data, dict)
        else None
    )
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]

    # Open-Meteo's place search often misses names written in Japanese.
    osm_url = "https://nominatim.openstreetmap.org/search?" + urlencode(
        {
            "q": city,
            "format": "jsonv2",
            "limit": 1,
            "accept-language": "ja",
            "addressdetails": 1,
        }
    )
    osm_data = _get_json(osm_url)
    osm_results = osm_data
    if not isinstance(osm_results, list) or not osm_results:
        return None
    result = osm_results[0]
    if not isinstance(result, dict):
        return None
    address = result.get("address")
    if not isinstance(address, dict):
        address = {}
    resolved_name = next(
        (
            address.get(key)
            for key in (
                "city",
                "town",
                "village",
                "municipality",
                "county",
            )
            if address.get(key)
        ),
        None,
    )
    if not resolved_name and result.get("display_name"):
        resolved_name = str(result["display_name"]).split(",", 1)[0].strip()
    return {
        "latitude": result.get("lat"),
        "longitude": result.get("lon"),
        "name": resolved_name,
        "admin1": address.get("state") or address.get("province"),
        "country": address.get("country"),
    }


def current_weather(query: str) -> str:
    query = unicodedata.normalize("NFKC", query).strip()
    if not query:
        return "例: `天気 東京` または `天気 浜松 明日`"
    day_match = _FORECAST_DAY_RE.fullmatch(query)
    day_label = "現在"
    day_offset = 0
    city = query
    if day_match is not None:
        city = day_match.group(1).strip()
        day_label = day_match.group(2)
        day_offset = {"今日": 0, "明日": 1, "明後日": 2}.get(
            day_label, 0
        )
    if not city:
        return "都市名も入れてね。例: `天気 浜松 明日`"
    if len(city) > 80:
        return "都市名が長すぎるよ。"

    try:
        place = _find_place(city)
        if place is None:
            return f"「{city}」は見つからなかったよ。"

        latitude = float(place["latitude"])
        longitude = float(place["longitude"])
        forecast_parameters: dict[str, object] = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
            "forecast_days": (
                14 if day_label in {"今週", "来週"} else day_offset + 1
            ),
        }
        if day_label == "現在":
            forecast_parameters["current"] = (
                "temperature_2m,apparent_temperature,"
                "relative_humidity_2m,precipitation,"
                "weather_code,wind_speed_10m"
            )
        else:
            forecast_parameters["daily"] = (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,precipitation_sum,"
                "wind_speed_10m_max"
            )
        forecast_url = "https://api.open-meteo.com/v1/forecast?" + urlencode(
            forecast_parameters
        )
        weather_data = _get_json(forecast_url)
        name = str(
            place.get("name")
            or f"緯度{latitude:g}・経度{longitude:g}"
        )
        region = place.get("admin1")
        country = place.get("country")
        location_parts = [name]
        if region and region != name:
            location_parts.append(str(region))
        if country:
            location_parts.append(str(country))
        location = " / ".join(location_parts)
        location_header = (
            f"📍 観測地点: {location}"
            f"（{latitude:.4f}, {longitude:.4f}）"
        )

        if not isinstance(weather_data, dict):
            return "天気情報を読み取れなかったよ。"
        if day_label != "現在":
            daily = weather_data.get("daily")
            if not isinstance(daily, dict):
                return "天気予報を読み取れなかったよ。"
            if day_label in {"今週", "来週"}:
                raw_dates = daily["time"]
                if not isinstance(raw_dates, list) or not raw_dates:
                    return "週間予報を読み取れなかったよ。"
                first_date = date.fromisoformat(str(raw_dates[0]))
                next_monday = 7 - first_date.weekday()
                if day_label == "今週":
                    start = 0
                    end = next_monday
                else:
                    start = next_monday
                    end = start + 7
                end = min(end, len(raw_dates))
                weekdays = "月火水木金土日"
                lines = [location_header, f"{day_label}の予報:"]
                for index in range(start, end):
                    forecast_date = date.fromisoformat(
                        str(raw_dates[index])
                    )
                    code = int(daily["weather_code"][index])
                    condition = _WEATHER_LABELS.get(
                        code, f"天気コード{code}"
                    )
                    maximum = float(
                        daily["temperature_2m_max"][index]
                    )
                    minimum = float(
                        daily["temperature_2m_min"][index]
                    )
                    rain_probability = int(
                        daily["precipitation_probability_max"][index]
                    )
                    weekday = weekdays[forecast_date.weekday()]
                    lines.append(
                        f"{forecast_date.month}/{forecast_date.day}"
                        f"（{weekday}） {condition} "
                        f"{minimum:g}〜{maximum:g}℃ "
                        f"降水{rain_probability}%"
                    )
                return "\n".join(lines)

            index = day_offset
            forecast_date_text = str(daily["time"][index])
            code = int(daily["weather_code"][index])
            condition = _WEATHER_LABELS.get(code, f"天気コード{code}")
            maximum = float(daily["temperature_2m_max"][index])
            minimum = float(daily["temperature_2m_min"][index])
            rain_probability = int(
                daily["precipitation_probability_max"][index]
            )
            precipitation = float(daily["precipitation_sum"][index])
            wind = float(daily["wind_speed_10m_max"][index])
            return (
                f"{location_header}\n"
                f"{day_label}（{forecast_date_text}）: {condition}\n"
                f"最高{maximum:g}℃・最低{minimum:g}℃・"
                f"降水確率{rain_probability}%\n"
                f"予想降水量{precipitation:g}mm・最大風速{wind:g}km/h"
            )

        current = weather_data.get("current")
        if not isinstance(current, dict):
            return "天気情報を読み取れなかったよ。"
        code = int(current["weather_code"])
        condition = _WEATHER_LABELS.get(code, f"天気コード{code}")
        temperature = float(current["temperature_2m"])
        apparent = float(current["apparent_temperature"])
        humidity = int(current["relative_humidity_2m"])
        precipitation = float(current["precipitation"])
        wind = float(current["wind_speed_10m"])
        return (
            f"{location_header}\n"
            f"現在: {condition}、{temperature:g}℃"
            f"（体感{apparent:g}℃）\n"
            f"湿度{humidity}%・降水{precipitation:g}mm・風{wind:g}km/h"
        )
    except (HTTPError, URLError, TimeoutError):
        return "いま天気サービスにつながらないみたい。少し後で試してね。"
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "天気情報を読み取れなかったよ。"


def _rdap_entity_name(
    entity: object,
    *,
    accepted_roles: set[str] | None = None,
) -> str | None:
    if not isinstance(entity, dict):
        return None
    roles = entity.get("roles")
    accepted = accepted_roles or {"registrar"}
    if (
        not isinstance(roles, list)
        or not accepted.intersection(str(role) for role in roles)
    ):
        return None
    vcard = entity.get("vcardArray")
    if (
        not isinstance(vcard, list)
        or len(vcard) < 2
        or not isinstance(vcard[1], list)
    ):
        return None
    for field in vcard[1]:
        if (
            isinstance(field, list)
            and len(field) >= 4
            and field[0] == "fn"
        ):
            return str(field[3])
    return None


def domain_whois(raw_domain: str) -> str:
    domain = unicodedata.normalize("NFKC", raw_domain).strip()
    if not domain:
        return "例: `whois example.com`"
    domain = domain.removeprefix("https://").removeprefix("http://")
    domain = domain.split("/", 1)[0].rstrip(".")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return "ドメイン名を読み取れなかったよ。"
    if not _DOMAIN_RE.fullmatch(ascii_domain):
        return "ドメイン名だけ指定してね。例: `whois example.com`"

    try:
        data = _get_json(
            "https://rdap.org/domain/" + quote(ascii_domain, safe=".-")
        )
        if not isinstance(data, dict):
            return "WHOIS情報を読み取れなかったよ。"

        registered_name = str(
            data.get("unicodeName")
            or data.get("ldhName")
            or ascii_domain
        )
        events = data.get("events")
        event_dates: dict[str, str] = {}
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                action = event.get("eventAction")
                event_date = event.get("eventDate")
                if action and event_date and action not in event_dates:
                    event_dates[str(action)] = str(event_date)[:10]

        registrar = None
        entities = data.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                registrar = _rdap_entity_name(entity)
                if registrar:
                    break

        statuses = data.get("status")
        status_text = (
            ", ".join(str(status) for status in statuses[:5])
            if isinstance(statuses, list) and statuses
            else "不明"
        )
        nameservers = data.get("nameservers")
        server_names: list[str] = []
        if isinstance(nameservers, list):
            for nameserver in nameservers:
                if not isinstance(nameserver, dict):
                    continue
                name = nameserver.get("unicodeName") or nameserver.get(
                    "ldhName"
                )
                if name:
                    server_names.append(str(name))

        lines = [
            f"ドメイン: {registered_name}",
            f"レジストラ: {registrar or '不明'}",
            f"登録日: {event_dates.get('registration', '不明')}",
            f"有効期限: {event_dates.get('expiration', '不明')}",
            f"状態: {status_text}",
        ]
        if server_names:
            lines.append("NS: " + ", ".join(server_names[:4]))
        return "\n".join(lines)
    except HTTPError as error:
        if error.code == 404:
            return f"「{domain}」のWHOIS情報は見つからなかったよ。"
        return "いまWHOISサービスにつながらないみたい。"
    except (URLError, TimeoutError):
        return "いまWHOISサービスにつながらないみたい。"
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "WHOIS情報を読み取れなかったよ。"


def ip_lookup(raw_address: str) -> str:
    raw_address = unicodedata.normalize("NFKC", raw_address).strip()
    if not raw_address:
        return "例: `ip 8.8.8.8`"
    try:
        address = ipaddress.ip_address(raw_address)
    except ValueError:
        return "IPアドレスを読み取れなかったよ。例: `ip 8.8.8.8`"
    if not address.is_global:
        return "公開IPアドレスを指定してね。"

    try:
        data = _get_json(
            "https://rdap.org/ip/" + quote(address.compressed, safe=".:")
        )
        if not isinstance(data, dict):
            return "IP情報を読み取れなかったよ。"

        organization = None
        entities = data.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                organization = _rdap_entity_name(
                    entity,
                    accepted_roles={
                        "registrant",
                        "administrative",
                        "technical",
                    },
                )
                if organization:
                    break

        network_name = data.get("name") or data.get("handle") or "不明"
        start = data.get("startAddress") or "不明"
        end = data.get("endAddress") or "不明"
        country = data.get("country") or "不明"
        network_type = data.get("type")
        lines = [
            f"IP: {address.compressed}（IPv{address.version}）",
            f"ネットワーク: {network_name}",
            f"割り当て範囲: {start} - {end}",
            f"国: {country}",
            f"管理組織: {organization or '不明'}",
        ]
        if network_type:
            lines.append(f"種別: {network_type}")
        return "\n".join(lines)
    except HTTPError as error:
        if error.code == 404:
            return f"「{address.compressed}」のIP情報は見つからなかったよ。"
        return "いまIP検索サービスにつながらないみたい。"
    except (URLError, TimeoutError):
        return "いまIP検索サービスにつながらないみたい。"
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "IP情報を読み取れなかったよ。"


def roll_dice(expression: str, *, rng: random.Random | None = None) -> str:
    expression = unicodedata.normalize("NFKC", expression).strip()
    if not expression:
        expression = "1d100"
    elif expression.isdecimal():
        expression = f"1d{expression}"
    match = _DICE_RE.fullmatch(expression)
    if match is None:
        return "例: `roll 20`、`roll 2d6`、`roll 1d20+3`"
    count = int(match.group(1))
    sides = int(match.group(2))
    if not 1 <= count <= 100:
        return "サイコロは1〜100個にしてね。"
    if not 2 <= sides <= 1_000_000:
        return "面数は2〜1,000,000にしてね。"
    modifier = int(match.group(4) or 0)
    if match.group(3) == "-":
        modifier = -modifier
    roller = rng or random.Random()
    rolls = [roller.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    modifier_text = (
        f"{modifier:+d}" if modifier else ""
    )
    shown = ", ".join(str(value) for value in rolls[:30])
    if len(rolls) > 30:
        shown += f", …ほか{len(rolls) - 30}個"
    return (
        f"🎲 {count}d{sides}{modifier_text}: [{shown}]"
        f" → 合計 {total}"
    )


def choose_option(
    expression: str,
    *,
    rng: random.Random | None = None,
) -> str:
    expression = unicodedata.normalize("NFKC", expression).strip()
    if not expression:
        return "例: `choice ラーメン 寿司 カレー`"
    try:
        options = shlex.split(expression)
    except ValueError:
        return "引用符の対応を確認してね。"
    if len(options) == 1:
        options = [
            option.strip()
            for option in re.split(r"[,、，]", options[0])
            if option.strip()
        ]
    if not 2 <= len(options) <= 50:
        return "候補を2〜50個指定してね。"
    if any(len(option) > 100 for option in options):
        return "候補は1つ100文字以内にしてね。"
    chooser = rng or random.Random()
    return f"これにする: **{chooser.choice(options)}**"


def dns_lookup(raw_domain: str) -> str:
    domain = unicodedata.normalize("NFKC", raw_domain).strip().rstrip(".")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return "ドメイン名を読み取れなかったよ。"
    if not _DOMAIN_RE.fullmatch(ascii_domain):
        return "例: `dns example.com`"

    records: dict[str, list[str]] = {}
    try:
        for record_type in ("A", "AAAA", "MX"):
            url = "https://cloudflare-dns.com/dns-query?" + urlencode(
                {"name": ascii_domain, "type": record_type}
            )
            data = _get_json(
                url,
                headers={"Accept": "application/dns-json"},
            )
            if not isinstance(data, dict):
                continue
            answers = data.get("Answer")
            if not isinstance(answers, list):
                continue
            values: list[str] = []
            for answer in answers:
                if not isinstance(answer, dict) or not answer.get("data"):
                    continue
                value = str(answer["data"]).rstrip(".").strip()
                if record_type == "MX" and value == "0":
                    value = "0 (メール受信なし)"
                values.append(value)
            if values:
                records[record_type] = values[:6]
    except (HTTPError, URLError, TimeoutError):
        return "いまDNSサービスにつながらないみたい。"
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return "DNS情報を読み取れなかったよ。"

    if not records:
        return f"「{domain}」のA・AAAA・MXレコードは見つからなかったよ。"
    lines = [f"DNS: {domain}"]
    for record_type in ("A", "AAAA", "MX"):
        if record_type in records:
            lines.append(
                f"{record_type}: " + ", ".join(records[record_type])
            )
    return "\n".join(lines)


def convert_unit(expression: str) -> str:
    expression = unicodedata.normalize("NFKC", expression).strip()
    try:
        parts = shlex.split(expression)
    except ValueError:
        return "例: `unit 10 km mile`"
    if len(parts) != 3:
        return "例: `unit 10 km mile`"
    raw_value, raw_source, raw_target = parts
    try:
        value = float(raw_value.replace(",", ""))
    except ValueError:
        return "数値を読み取れなかったよ。"
    if not math.isfinite(value):
        return "有限の数値を指定してね。"
    source = raw_source.lower().replace("°", "")
    target = raw_target.lower().replace("°", "")

    if source in _TEMPERATURE_UNITS or target in _TEMPERATURE_UNITS:
        if source not in _TEMPERATURE_UNITS or target not in _TEMPERATURE_UNITS:
            return "温度は C・F・K の間で変換してね。"
        if source == "c":
            celsius = value
        elif source == "f":
            celsius = (value - 32) * 5 / 9
        else:
            celsius = value - 273.15
        if target == "c":
            converted = celsius
        elif target == "f":
            converted = celsius * 9 / 5 + 32
        else:
            converted = celsius + 273.15
    else:
        source_unit = _UNIT_FACTORS.get(source)
        target_unit = _UNIT_FACTORS.get(target)
        if source_unit is None or target_unit is None:
            return (
                "未対応の単位だよ。長さ・重さ・温度・容量・時間に対応しているよ。"
            )
        if source_unit[0] != target_unit[0]:
            return "同じ種類の単位同士を指定してね。"
        converted = value * source_unit[1] / target_unit[1]
    return f"{value:g} {raw_source} = {converted:.12g} {raw_target}"


def hash_text(expression: str) -> str:
    expression = unicodedata.normalize("NFKC", expression).strip()
    algorithm, separator, text = expression.partition(" ")
    algorithm = algorithm.lower()
    text = text.strip()
    if not separator or not text:
        return "例: `hash sha256 文字列`"
    if algorithm not in _HASH_ALGORITHMS:
        return "対応形式: sha256 / sha512 / sha1 / md5"
    if len(text) > 1_000:
        return "ハッシュ対象は1,000文字以内にしてね。"
    digest = hashlib.new(algorithm, text.encode("utf-8")).hexdigest()
    warning = (
        "\n※ SHA-1とMD5は安全な署名・パスワード保存には使えないよ。"
        if algorithm in {"sha1", "md5"}
        else ""
    )
    return f"{algorithm.upper()}:\n`{digest}`{warning}"


def format_bytes(size: int | float) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1_024 or unit == "TiB":
            return f"{value:.1f}{unit}"
        value /= 1_024
    return f"{value:.1f}TiB"


def format_duration(seconds: int | float) -> str:
    total = max(0, int(seconds))
    days, remainder = divmod(total, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}日")
    if hours or days:
        parts.append(f"{hours}時間")
    if minutes or hours or days:
        parts.append(f"{minutes}分")
    parts.append(f"{secs}秒")
    return "".join(parts)


def pc_status(
    *,
    proc_root: Path,
    disk_path: Path,
) -> str:
    try:
        load_values = (
            (proc_root / "loadavg").read_text(encoding="utf-8").split()[:3]
        )
        uptime_seconds = float(
            (proc_root / "uptime")
            .read_text(encoding="utf-8")
            .split()[0]
        )
        memory_values: dict[str, int] = {}
        for line in (proc_root / "meminfo").read_text(
            encoding="utf-8"
        ).splitlines():
            name, separator, value = line.partition(":")
            if separator:
                memory_values[name] = int(value.strip().split()[0]) * 1_024
        memory_total = memory_values["MemTotal"]
        memory_available = memory_values.get(
            "MemAvailable",
            memory_values.get("MemFree", 0),
        )
        memory_used = memory_total - memory_available
        disk = shutil.disk_usage(disk_path)
    except (OSError, KeyError, ValueError, IndexError):
        return "PC状態を読み取れなかったよ。"

    memory_percent = (
        memory_used / memory_total * 100 if memory_total else 0
    )
    disk_percent = disk.used / disk.total * 100 if disk.total else 0
    return (
        "**ホストPC状態**\n"
        f"CPU: {os.cpu_count() or '?'}スレッド・"
        f"負荷 {', '.join(load_values)}（1/5/15分）\n"
        f"メモリ: {format_bytes(memory_used)} / "
        f"{format_bytes(memory_total)}（{memory_percent:.1f}%）\n"
        f"ディスク: {format_bytes(disk.used)} / "
        f"{format_bytes(disk.total)}（{disk_percent:.1f}%）\n"
        f"PC稼働時間: {format_duration(uptime_seconds)}"
    )
