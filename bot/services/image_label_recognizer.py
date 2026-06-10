from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from os import getenv
import os
from pathlib import Path
import re
import shutil
import tempfile

from PIL import Image, ImageFilter, ImageOps

from bot.config import ASSETS_DIR


@dataclass(frozen=True)
class ImageLabelData:
    art: str
    color: str
    size: str
    code: str
    certilogo_code: str
    certilogo_url: str

    def as_parts(self) -> list[str]:
        return [
            self.art,
            self.color,
            self.size,
            self.code,
            self.certilogo_code,
            self.certilogo_url,
        ]

    def as_line(self) -> str:
        return ", ".join(self.as_parts())


class ImageLabelRecognitionError(RuntimeError):
    def __init__(
        self,
        message: str,
        partial_data: ImageLabelData | None = None,
        missing_fields: list[str] | None = None,
    ):
        super().__init__(message)
        self.partial_data = partial_data
        self.missing_fields = missing_fields or []


WECHAT_QR_DIR = ASSETS_DIR / "wechat_qr"
WECHAT_QR_FILES = {
    "detect_prototxt": WECHAT_QR_DIR / "detect.prototxt",
    "detect_caffemodel": WECHAT_QR_DIR / "detect.caffemodel",
    "sr_prototxt": WECHAT_QR_DIR / "sr.prototxt",
    "sr_caffemodel": WECHAT_QR_DIR / "sr.caffemodel",
}
WECHAT_QR_ASCII_DIR = Path(tempfile.gettempdir()) / "stone_label_wechat_qr"
_RAPIDOCR_ENGINE = None


def _find_tesseract() -> str:
    configured_path = getenv("TESSERACT_CMD")
    candidates = [
        configured_path,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return ""


def _wechat_qr_model_paths() -> dict[str, Path] | None:
    if not all(path.exists() for path in WECHAT_QR_FILES.values()):
        return None

    WECHAT_QR_ASCII_DIR.mkdir(parents=True, exist_ok=True)
    ascii_paths: dict[str, Path] = {}
    for key, source_path in WECHAT_QR_FILES.items():
        target_path = WECHAT_QR_ASCII_DIR / source_path.name
        if not target_path.exists() or target_path.stat().st_size != source_path.stat().st_size:
            shutil.copy2(source_path, target_path)
        ascii_paths[key] = target_path
    return ascii_paths


def _rotate_cv_candidates(image):
    try:
        import cv2
    except ImportError:
        return [image]

    return [
        image,
        cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(image, cv2.ROTATE_180),
        cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE),
    ]


def _scaled_cv_candidates(image):
    try:
        import cv2
    except ImportError:
        return [image]

    return [
        image,
        cv2.resize(image, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC),
    ]


def _read_qr_with_wechat(image) -> str:
    try:
        import cv2
    except ImportError:
        return ""

    if not hasattr(cv2, "wechat_qrcode_WeChatQRCode"):
        return ""
    model_paths = _wechat_qr_model_paths()
    if model_paths is None:
        return ""

    try:
        detector = cv2.wechat_qrcode_WeChatQRCode(
            str(model_paths["detect_prototxt"]),
            str(model_paths["detect_caffemodel"]),
            str(model_paths["sr_prototxt"]),
            str(model_paths["sr_caffemodel"]),
        )
    except (cv2.error, SystemError):
        return ""

    for rotated in _rotate_cv_candidates(image):
        try:
            results, _ = detector.detectAndDecode(rotated)
        except (cv2.error, SystemError):
            continue
        for result in results:
            if result.strip():
                return result.strip()
    return ""


def _read_qr_with_opencv(image) -> str:
    try:
        import cv2
    except ImportError:
        return ""

    detector = cv2.QRCodeDetector()
    for candidate in _scaled_cv_candidates(image):
        data, _, _ = detector.detectAndDecode(candidate)
        if data.strip():
            return data.strip()
    return ""


def _read_qr(image_bytes: bytes) -> str:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return ""

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        return ""

    return _read_qr_with_wechat(image) or _read_qr_with_opencv(image)


def _prepare_for_tesseract(image_bytes: bytes) -> list[Image.Image]:
    image = Image.open(BytesIO(image_bytes)).convert("L")
    image = ImageOps.autocontrast(image)
    width, height = image.size
    if max(width, height) < 1800:
        scale = 1800 / max(width, height)
        image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    sharp = image.filter(ImageFilter.SHARPEN)
    binary = sharp.point(lambda value: 255 if value > 155 else 0)

    candidates: list[Image.Image] = []
    seen_sizes: set[tuple[int, int, int]] = set()
    variants = (
        (sharp, (0, -45, 45, 90, 270)),
        (binary, (0,)),
    )
    for source, angles in variants:
        for angle in angles:
            candidate = source.rotate(angle, expand=True, fillcolor=255)
            key = (candidate.width, candidate.height, angle)
            if key not in seen_sizes:
                seen_sizes.add(key)
                candidates.append(candidate)
    return candidates


def _rapidocr_text(image_bytes: bytes) -> str:
    global _RAPIDOCR_ENGINE

    if getenv("OCR_ENGINE", "").strip().lower() == "tesseract":
        return ""

    try:
        from rapidocr import RapidOCR
    except ImportError:
        return ""

    if _RAPIDOCR_ENGINE is None:
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        _RAPIDOCR_ENGINE = RapidOCR(
            params={
                "Global.max_side_len": 1280,
                "EngineConfig.onnxruntime.intra_op_num_threads": 1,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
            }
        )

    try:
        result = _RAPIDOCR_ENGINE(image_bytes)
    except Exception:
        return ""

    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    if not txts:
        return ""

    chunks: list[str] = []
    for index, text in enumerate(txts):
        score = scores[index] if scores and index < len(scores) else 1.0
        if text and score >= 0.35:
            chunks.append(str(text))
    return "\n".join(chunks)


def _tesseract_text(image_bytes: bytes) -> str:
    tesseract_path = _find_tesseract()
    if not tesseract_path:
        return ""

    try:
        import pytesseract
    except ImportError:
        return ""

    pytesseract.pytesseract.tesseract_cmd = tesseract_path
    chunks: list[str] = []
    for index, image in enumerate(_prepare_for_tesseract(image_bytes)):
        configs = ["--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789./:"]
        if index == 0:
            configs.append("--psm 11")
        for config in configs:
            try:
                text = pytesseract.image_to_string(image, config=config, timeout=1)
            except RuntimeError:
                continue
            if text.strip():
                chunks.append(text)
    return "\n".join(chunks)


def _ocr_text(image_bytes: bytes) -> str:
    rapid_text = _rapidocr_text(image_bytes)
    tesseract_text = _tesseract_text(image_bytes)

    if rapid_text and tesseract_text:
        return rapid_text + "\n" + tesseract_text
    return rapid_text or tesseract_text


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text.upper())


def _find_first(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1 if match.lastindex else 0)
    return ""


def _debug_snippet(label: str, text: str, limit: int = 500) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "..."
    return f"{label}: {cleaned or '-'}"


def _extract_first_photo(text: str) -> tuple[str, str, str, str]:
    compact = _compact(text)
    art = _find_first([
        r"(K\d[A-Z]\d{8,10}[A-Z]\d{3,5})",
        r"ART\.?([A-Z0-9]{8,24}?)(?=V\d{4}|[A-Z]\d{4}|TG|T9|SIZE|$)",
        r"(\d{8,10})",
    ], compact)
    color = _find_first([r"(V\d{4})", r"([A-Z]\d{4})"], compact)
    size = _find_first([
        r"TG\.?(XXXL|XXL|XL|XS|XXS|S|M|L|\d{1,3})",
        r"T9\.?(XXXL|XXL|XL|XS|XXS|S|M|L|\d{1,3})",
        r"SIZE\.?(XXXL|XXL|XL|XS|XXS|S|M|L|\d{1,3})",
        r"[^A-Z](XXXL|XXL|XL|XS|XXS|S|M|L)[^A-Z]",
    ], compact)
    code = _find_first([
        r"(\d{2}PRO[CM]\d{8,12})",
        r"(PRO[CM]\d{8,12})",
        r"(TOM\d{5,12})",
        r"([A-Z]{2,5}\d{5,12})",
    ], compact)

    if code in {art, color}:
        code = ""

    return art, color, size, code


def _extract_second_photo(text: str, qr_data: str) -> tuple[str, str]:
    compact = _compact(text)
    certilogo_code = _find_first([r"(CLG\d{9,15})", r"CLG[^0-9]*(\d{9,15})", r"(\d{12,15})"], compact + _compact(qr_data))
    if certilogo_code.startswith("CLG"):
        certilogo_code = certilogo_code[3:]

    certilogo_url = qr_data
    if not certilogo_code and qr_data:
        certilogo_code = _find_first([r"/QR/([A-Z0-9]+)", r"QR/([A-Z0-9]+)", r"/([A-Z0-9]{8,20})$"], _compact(qr_data))
    if not certilogo_url and certilogo_code:
        certilogo_url = f"https://certilogo.com/{certilogo_code}"

    return certilogo_code, certilogo_url


def _recognize_label_photos_sync(
    *,
    first_photo: bytes,
    second_photo: bytes,
) -> ImageLabelData:
    first_text = _ocr_text(first_photo)
    qr_data = _read_qr(second_photo)
    second_text = _ocr_text(second_photo)

    art, color, size, code = _extract_first_photo(first_text)
    certilogo_code, certilogo_url = _extract_second_photo(second_text, qr_data)

    data = ImageLabelData(
        art=art,
        color=color,
        size=size,
        code=code,
        certilogo_code=certilogo_code,
        certilogo_url=certilogo_url,
    )

    missing = [
        name
        for name, value in {
            "art": data.art,
            "color": data.color,
            "size": data.size,
            "code": data.code,
            "certilogo_code": data.certilogo_code,
            "certilogo_url": data.certilogo_url,
        }.items()
        if not value
    ]
    if missing:
        raise ImageLabelRecognitionError(
            "не удалось найти поля: "
            + ", ".join(missing)
            + ". Попробуйте фото ближе, ровнее и без бликов.\n\n"
            + _debug_snippet("OCR 1", first_text)
            + "\n"
            + _debug_snippet("OCR 2", second_text)
            + "\nQR: "
            + (qr_data or "-"),
            partial_data=data,
            missing_fields=missing,
        )

    return data


async def recognize_label_photos(
    *,
    api_key: str | None = None,
    model: str | None = None,
    first_photo: bytes,
    second_photo: bytes,
) -> ImageLabelData:
    return await asyncio.to_thread(
        _recognize_label_photos_sync,
        first_photo=first_photo,
        second_photo=second_photo,
    )
