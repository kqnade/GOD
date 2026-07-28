from __future__ import annotations

import io
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


class AmedasError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AmedasImage:
    caption: str
    filename: str
    data: bytes


_JMA_BASE = "https://www.jma.go.jp/bosai/amedas"
_GSI_TILE = "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"
_ELEMENTS = {
    "気温": ("temp", "気温", "℃"),
    "降水": ("precipitation1h", "1時間降水量", "mm"),
    "降水量": ("precipitation1h", "1時間降水量", "mm"),
    "雨": ("precipitation1h", "1時間降水量", "mm"),
    "風": ("wind", "風速", "m/s"),
    "風速": ("wind", "風速", "m/s"),
    "日照": ("sun1h", "日照時間", "h"),
    "日照時間": ("sun1h", "日照時間", "h"),
    "湿度": ("humidity", "湿度", "%"),
}
_REGION_BOUNDS = {
    "全国": (20.0, 46.5, 122.0, 154.0),
    "北海道": (41.2, 45.8, 139.0, 146.2),
    "東北": (36.8, 41.7, 138.5, 142.3),
    "関東": (34.5, 37.2, 138.2, 141.2),
    "甲信": (34.7, 37.2, 136.8, 139.2),
    "北陸": (35.5, 38.7, 136.0, 139.5),
    "東海": (33.9, 36.3, 135.4, 139.0),
    "近畿": (33.3, 36.2, 134.0, 136.9),
    "関西": (33.3, 36.2, 134.0, 136.9),
    "中国": (33.4, 35.7, 130.5, 134.9),
    "四国": (32.7, 34.7, 132.0, 134.9),
    "九州": (30.8, 34.2, 128.8, 132.3),
    "沖縄": (23.5, 28.8, 122.5, 131.5),
}
_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-zぁ-んァ-ヶ一-龠々ー-]+")
_FONT_PATHS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def _request(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Kami-sama-Discord-Bot/0.1"})
    with urlopen(request, timeout=10) as response:
        data = response.read(3_000_001)
    if len(data) > 3_000_000:
        raise AmedasError("アメダスのデータが大きすぎたよ。")
    return data


def _fetch_text(url: str) -> str:
    return _request(url).decode("utf-8").strip()


def _fetch_json(url: str) -> dict[str, object]:
    value = json.loads(_request(url))
    if not isinstance(value, dict):
        raise AmedasError("アメダスのデータ形式を読み取れなかったよ。")
    return value


def _fetch_tile(z: int, x: int, y: int) -> Image.Image:
    raw = _request(_GSI_TILE.format(z=z, x=x, y=y))
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert("RGB")


def _normalize_query(query: str) -> tuple[str, str, str, str]:
    query = unicodedata.normalize("NFKC", query).strip()
    if not query:
        raise AmedasError(
            "例: `アメダス 静岡県` または `アメダス 東海 降水`"
        )
    parts = query.split()
    element_name = "気温"
    if parts[-1] in _ELEMENTS:
        element_name = parts.pop()
    region = " ".join(parts).strip()
    if not region:
        raise AmedasError("地域名を指定してね。例: `アメダス 静岡県 気温`")
    key, label, unit = _ELEMENTS[element_name]
    return region, key, label, unit


def _resolve_bounds(
    region: str,
) -> tuple[
    str,
    tuple[float, float, float, float],
    dict[str, object] | None,
]:
    fixed = _REGION_BOUNDS.get(region)
    if fixed is not None:
        return region, fixed, None

    url = "https://nominatim.openstreetmap.org/search?" + urlencode(
        {
            "q": f"{region}, 日本",
            "format": "jsonv2",
            "limit": 1,
            "accept-language": "ja",
            "countrycodes": "jp",
            "polygon_geojson": 1,
            "polygon_threshold": 0.01,
        }
    )
    try:
        value = json.loads(_request(url))
        if not isinstance(value, list) or not value:
            raise AmedasError(f"「{region}」の地域を見つけられなかったよ。")
        result = value[0]
        bounds = result.get("boundingbox")
        if not isinstance(bounds, list) or len(bounds) != 4:
            raise AmedasError(f"「{region}」の範囲を読み取れなかったよ。")
        south, north, west, east = (float(item) for item in bounds)
        if not (
            20 <= south <= 46.5
            and 20 <= north <= 46.5
            and 122 <= west <= 154
            and 122 <= east <= 154
        ):
            raise AmedasError("日本国内の都道府県・地域を指定してね。")
        # Very small municipalities still need enough surrounding stations.
        lat_pad = max(0.18, (north - south) * 0.12)
        lon_pad = max(0.22, (east - west) * 0.12)
        shown_name = str(result.get("name") or region)
        geometry = result.get("geojson")
        if not isinstance(geometry, dict):
            geometry = None
        return (
            shown_name,
            (
                south - lat_pad,
                north + lat_pad,
                west - lon_pad,
                east + lon_pad,
            ),
            geometry,
        )
    except AmedasError:
        raise
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise AmedasError("地域検索サービスにつながらないみたい。") from error


def _world_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    scale = 256 * (2**zoom)
    latitude = min(85.05112878, max(-85.05112878, lat))
    x = (lon + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(latitude))
    y = (
        0.5
        - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)
    ) * scale
    return x, y


def _choose_zoom(bounds: tuple[float, float, float, float]) -> int:
    south, north, west, east = bounds
    for zoom in range(10, 3, -1):
        left, bottom = _world_pixel(south, west, zoom)
        right, top = _world_pixel(north, east, zoom)
        if abs(right - left) <= 900 and abs(bottom - top) <= 590:
            return zoom
    return 4


def _font(size: int, *, index: int = 0) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=size, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


def _value_color(key: str, value: float) -> tuple[int, int, int]:
    if key == "temp":
        stops = (
            (-10, (50, 90, 210)),
            (0, (60, 180, 230)),
            (15, (80, 190, 100)),
            (25, (245, 205, 45)),
            (35, (235, 65, 40)),
        )
    elif key == "precipitation1h":
        stops = (
            (0, (110, 170, 220)),
            (1, (45, 155, 235)),
            (10, (40, 190, 100)),
            (30, (245, 180, 30)),
            (60, (220, 50, 70)),
        )
    elif key == "wind":
        stops = (
            (0, (90, 170, 230)),
            (3, (60, 190, 120)),
            (8, (245, 190, 40)),
            (15, (225, 60, 50)),
        )
    elif key == "humidity":
        stops = (
            (20, (235, 190, 65)),
            (50, (100, 190, 130)),
            (80, (55, 140, 225)),
            (100, (75, 65, 180)),
        )
    else:
        stops = (
            (0, (110, 150, 190)),
            (0.2, (80, 180, 120)),
            (0.6, (245, 185, 40)),
            (1.0, (235, 85, 45)),
        )
    if value <= stops[0][0]:
        return stops[0][1]
    for (low, low_color), (high, high_color) in zip(stops, stops[1:]):
        if value <= high:
            ratio = (value - low) / (high - low)
            return tuple(
                round(a + (b - a) * ratio)
                for a, b in zip(low_color, high_color)
            )
    return stops[-1][1]


def _station_lat_lon(station: dict[str, object]) -> tuple[float, float]:
    lat = station["lat"]
    lon = station["lon"]
    if not (
        isinstance(lat, list)
        and isinstance(lon, list)
        and len(lat) == 2
        and len(lon) == 2
    ):
        raise ValueError
    return (
        float(lat[0]) + float(lat[1]) / 60,
        float(lon[0]) + float(lon[1]) / 60,
    )


def _point_in_ring(
    lat: float,
    lon: float,
    ring: object,
) -> bool:
    if not isinstance(ring, list) or len(ring) < 3:
        return False
    inside = False
    previous = ring[-1]
    if not isinstance(previous, list) or len(previous) < 2:
        return False
    previous_lon, previous_lat = float(previous[0]), float(previous[1])
    for current in ring:
        if not isinstance(current, list) or len(current) < 2:
            continue
        current_lon, current_lat = float(current[0]), float(current[1])
        crosses = (current_lat > lat) != (previous_lat > lat)
        if crosses:
            boundary_lon = (
                (previous_lon - current_lon)
                * (lat - current_lat)
                / (previous_lat - current_lat)
                + current_lon
            )
            if lon < boundary_lon:
                inside = not inside
        previous_lon, previous_lat = current_lon, current_lat
    return inside


def _point_in_geometry(
    lat: float,
    lon: float,
    geometry: dict[str, object] | None,
) -> bool:
    if geometry is None:
        return True
    coordinates = geometry.get("coordinates")
    geometry_type = geometry.get("type")
    if not isinstance(coordinates, list):
        return True
    polygons = (
        [coordinates]
        if geometry_type == "Polygon"
        else coordinates
        if geometry_type == "MultiPolygon"
        else []
    )
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            continue
        if not _point_in_ring(lat, lon, polygon[0]):
            continue
        if any(_point_in_ring(lat, lon, hole) for hole in polygon[1:]):
            continue
        return True
    return False


def _make_basemap(
    bounds: tuple[float, float, float, float],
) -> tuple[Image.Image, int, float, float, float, float]:
    width, height = 1000, 650
    zoom = min(10, _choose_zoom(bounds) + 1)
    south, north, west, east = bounds
    west_x, south_y = _world_pixel(south, west, zoom)
    east_x, north_y = _world_pixel(north, east, zoom)
    center_x = (west_x + east_x) / 2
    center_y = (south_y + north_y) / 2
    source_width = max(320.0, abs(east_x - west_x) * 1.08)
    source_height = max(220.0, abs(south_y - north_y) * 1.08)
    target_ratio = width / height
    if source_width / source_height < target_ratio:
        source_width = source_height * target_ratio
    else:
        source_height = source_width / target_ratio
    source_width_px = math.ceil(source_width)
    source_height_px = math.ceil(source_height)
    left = center_x - source_width / 2
    top = center_y - source_height / 2
    canvas = Image.new(
        "RGB",
        (source_width_px, source_height_px),
        "#e9eef2",
    )
    min_x = math.floor(left / 256)
    max_x = math.floor((left + source_width - 1) / 256)
    min_y = math.floor(top / 256)
    max_y = math.floor((top + source_height - 1) / 256)
    tile_limit = 2**zoom
    for tile_x in range(min_x, max_x + 1):
        for tile_y in range(min_y, max_y + 1):
            if not 0 <= tile_y < tile_limit:
                continue
            try:
                tile = _fetch_tile(zoom, tile_x % tile_limit, tile_y)
            except (OSError, AmedasError):
                continue
            canvas.paste(
                tile,
                (round(tile_x * 256 - left), round(tile_y * 256 - top)),
            )
    canvas = canvas.resize((width, height), Image.Resampling.LANCZOS)
    return (
        canvas,
        zoom,
        left,
        top,
        width / source_width,
        height / source_height,
    )


def render_amedas_image(
    *,
    region_name: str,
    bounds: tuple[float, float, float, float],
    observed_at: datetime,
    element_key: str,
    element_label: str,
    unit: str,
    stations: dict[str, object],
    observations: dict[str, object],
    geometry: dict[str, object] | None = None,
) -> AmedasImage:
    map_image, zoom, left, top, scale_x, scale_y = _make_basemap(bounds)
    image = Image.new("RGB", (1000, 770), "white")
    image.paste(map_image, (0, 80))
    draw = ImageDraw.Draw(image)
    title_font = _font(30)
    text_font = _font(18)
    small_font = _font(14)
    value_font = _font(17)
    draw.text(
        (24, 16),
        f"アメダス {region_name}・{element_label}",
        fill="#152536",
        font=title_font,
    )
    draw.text(
        (25, 53),
        observed_at.strftime("%Y/%m/%d %H:%M JST"),
        fill="#42566b",
        font=text_font,
    )

    plotted: list[tuple[int, int]] = []
    shown = 0
    south, north, west, east = bounds
    for station_id, station_value in stations.items():
        if not isinstance(station_value, dict):
            continue
        observation = observations.get(station_id)
        if not isinstance(observation, dict):
            continue
        raw_value = observation.get(element_key)
        if not (
            isinstance(raw_value, list)
            and len(raw_value) >= 2
            and isinstance(raw_value[0], (int, float))
            and raw_value[1] in (0, 1)
        ):
            continue
        try:
            lat, lon = _station_lat_lon(station_value)
        except (KeyError, TypeError, ValueError):
            continue
        if not (south <= lat <= north and west <= lon <= east):
            continue
        if not _point_in_geometry(lat, lon, geometry):
            continue
        world_x, world_y = _world_pixel(lat, lon, zoom)
        x = round((world_x - left) * scale_x)
        y = round((world_y - top) * scale_y) + 80
        if not (16 <= x < 984 and 96 <= y < 720):
            continue
        # Avoid making dense areas unreadable while retaining spatial coverage.
        if any((x - old_x) ** 2 + (y - old_y) ** 2 < 42**2 for old_x, old_y in plotted):
            continue
        plotted.append((x, y))
        value = float(raw_value[0])
        color = _value_color(element_key, value)
        draw.ellipse(
            (x - 16, y - 16, x + 16, y + 16),
            fill=color,
            outline="white",
            width=2,
        )
        value_text = f"{value:g}"
        box = draw.textbbox((0, 0), value_text, font=value_font)
        draw.text(
            (x - (box[2] - box[0]) / 2, y - (box[3] - box[1]) / 2 - 2),
            value_text,
            fill="white",
            stroke_width=2,
            stroke_fill="#253443",
            font=value_font,
        )
        station_name = str(station_value.get("kjName") or station_id)
        draw.text(
            (x + 18, y - 10),
            station_name,
            fill="#172634",
            stroke_width=3,
            stroke_fill="white",
            font=small_font,
        )
        shown += 1

    if not shown:
        raise AmedasError(
            f"{region_name}で{element_label}を観測している地点が見つからなかったよ。"
        )
    draw.rectangle((0, 730, 1000, 770), fill=(250, 250, 250))
    draw.text(
        (18, 742),
        f"単位: {unit}　地点数: {shown}　観測: 気象庁　地図: 国土地理院",
        fill="#34495e",
        font=small_font,
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    safe_region = _SAFE_NAME_RE.sub("_", region_name).strip("_") or "region"
    return AmedasImage(
        caption=(
            f"**アメダス {region_name}・{element_label}**\n"
            f"{observed_at:%Y/%m/%d %H:%M} JST・{shown}地点"
        ),
        filename=f"amedas_{safe_region}_{element_key}.png",
        data=output.getvalue(),
    )


def latest_amedas_image(query: str) -> AmedasImage:
    region, key, label, unit = _normalize_query(query)
    region_name, bounds, geometry = _resolve_bounds(region)
    try:
        latest_text = _fetch_text(f"{_JMA_BASE}/data/latest_time.txt")
        observed_at = datetime.fromisoformat(latest_text)
        timestamp = observed_at.strftime("%Y%m%d%H%M00")
        stations = _fetch_json(f"{_JMA_BASE}/const/amedastable.json")
        observations = _fetch_json(f"{_JMA_BASE}/data/map/{timestamp}.json")
        return render_amedas_image(
            region_name=region_name,
            bounds=bounds,
            observed_at=observed_at,
            element_key=key,
            element_label=label,
            unit=unit,
            stations=stations,
            observations=observations,
            geometry=geometry,
        )
    except AmedasError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise AmedasError("いまアメダス情報を取得できないみたい。") from error
