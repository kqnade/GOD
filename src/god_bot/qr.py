from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass

import qrcode
from qrcode.exceptions import DataOverflowError


class QrError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QrImage:
    caption: str
    filename: str
    data: bytes


def make_qr_image(raw_text: str) -> QrImage:
    text = unicodedata.normalize("NFKC", raw_text).strip()
    if not text:
        raise QrError("例: `qr https://example.com`")
    encoded = text.encode("utf-8")
    if len(encoded) > 1_000:
        raise QrError("QRにする文字列はUTF-8で1,000バイト以内にしてね。")

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    try:
        qr.add_data(encoded)
        qr.make(fit=True)
    except DataOverflowError as error:
        raise QrError("その文字列はQRコードに収まらなかったよ。") from error
    image = qr.make_image(fill_color="black", back_color="white")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    preview = text if len(text) <= 80 else text[:77] + "…"
    return QrImage(
        caption=f"**QRコード**\n{preview}",
        filename="qr.png",
        data=output.getvalue(),
    )
