from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EarthquakeError(ValueError):
    pass


_FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/eqvol_l.xml"
_ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}
_MAX_XML_BYTES = 2_000_000


def _fetch_xml(url: str) -> bytes:
    request = Request(
        url,
        headers={"User-Agent": "God-Discord-Bot/0.1"},
    )
    with urlopen(request, timeout=10) as response:
        payload = response.read(_MAX_XML_BYTES + 1)
    if len(payload) > _MAX_XML_BYTES:
        raise EarthquakeError("気象庁XMLが大きすぎるよ")
    return payload


def _text(element: ET.Element, path: str) -> str | None:
    found = element.find(path)
    if found is None or not found.text:
        return None
    return found.text.strip()


def _format_datetime(value: str | None) -> str:
    if not value:
        return "不明"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y/%m/%d %H:%M")


def _latest_earthquake_url(feed: ET.Element) -> str:
    for entry in feed.findall("atom:entry", _ATOM_NAMESPACE):
        title = entry.findtext(
            "atom:title",
            default="",
            namespaces=_ATOM_NAMESPACE,
        ).strip()
        if title != "震源・震度に関する情報":
            continue
        link = entry.find("atom:link", _ATOM_NAMESPACE)
        if link is not None and link.get("href"):
            return str(link.get("href"))
    raise EarthquakeError("最近の震源・震度情報が見つからなかったよ")


def _parse_earthquake(report: ET.Element) -> str:
    origin_time = _text(report, ".//{*}OriginTime")
    report_time = _text(report, ".//{*}ReportDateTime")
    hypocenter = report.find(".//{*}Hypocenter")
    place = (
        _text(hypocenter, ".//{*}Name")
        if hypocenter is not None
        else None
    )
    coordinate_element = (
        hypocenter.find(".//{*}Coordinate")
        if hypocenter is not None
        else None
    )
    coordinate = (
        coordinate_element.get("description")
        if coordinate_element is not None
        else None
    )
    magnitude_element = report.find(".//{*}Magnitude")
    magnitude = (
        magnitude_element.get("description")
        or (magnitude_element.text or "").strip()
        if magnitude_element is not None
        else None
    )
    max_intensity = _text(report, ".//{*}MaxInt")

    affected: list[str] = []
    for prefecture in report.findall(".//{*}Observation/{*}Pref"):
        name = _text(prefecture, "./{*}Name")
        intensity = _text(prefecture, "./{*}MaxInt")
        if name and intensity == max_intensity and name not in affected:
            affected.append(name)

    tsunami_text = None
    for text_element in report.findall(".//{*}Text"):
        text = (text_element.text or "").strip()
        if "津波" in text:
            tsunami_text = text
            break

    intensity_labels = {
        "5-": "5弱",
        "5+": "5強",
        "6-": "6弱",
        "6+": "6強",
        "over": "7",
        "不明": "不明",
    }
    shown_intensity = intensity_labels.get(
        max_intensity or "",
        max_intensity or "不明",
    )
    lines = [
        "**気象庁・最新の地震情報**",
        f"発生: {_format_datetime(origin_time)}",
        f"震源: {place or '不明'}",
        f"規模: {magnitude or '不明'}",
        f"最大震度: {shown_intensity}",
    ]
    if coordinate:
        lines.append(f"位置・深さ: {coordinate}")
    if affected:
        lines.append("最大震度の地域: " + "、".join(affected[:8]))
    lines.append(f"津波: {tsunami_text or '情報なし'}")
    lines.append(f"気象庁発表: {_format_datetime(report_time)}")
    lines.append("出典: 気象庁防災情報XML")
    return "\n".join(lines)


def latest_earthquake() -> str:
    try:
        feed = ET.fromstring(_fetch_xml(_FEED_URL))
        detail_url = _latest_earthquake_url(feed)
        report = ET.fromstring(_fetch_xml(detail_url))
        return _parse_earthquake(report)
    except EarthquakeError:
        raise
    except (HTTPError, URLError, TimeoutError) as error:
        raise EarthquakeError(
            "いま気象庁の地震情報につながらないみたい"
        ) from error
    except ET.ParseError as error:
        raise EarthquakeError("気象庁の地震XMLを読み取れなかったよ") from error
