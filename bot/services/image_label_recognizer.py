from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
import logging
from os import getenv
import os
from pathlib import Path
import re
import shutil
import tempfile

from PIL import Image, ImageFilter, ImageOps

from bot.config import ASSETS_DIR


logger = logging.getLogger(__name__)


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
MAIN_LABEL_TYPE = "main"
CLG2026_LABEL_TYPE = "clg2026"
CERTILOGO_URL_PATTERN = r"http://certilogo\.com/qr/[A-Z0-9]{10}"


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


def _pil_from_cv_gray(image) -> Image.Image:
    return Image.fromarray(image).convert("L")


def _order_points(points):
    import numpy as np

    rect = np.zeros((4, 2), dtype="float32")
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1)
    rect[0] = points[np.argmin(sums)]
    rect[2] = points[np.argmax(sums)]
    rect[1] = points[np.argmin(diffs)]
    rect[3] = points[np.argmax(diffs)]
    return rect


def _label_region_candidates(image_bytes: bytes) -> list[Image.Image]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return []

    height, width = image.shape[:2]
    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    _, mask = cv2.threshold(blurred, 145, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[Image.Image] = []
    min_area = width * height * 0.015
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:4]:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        pad = int(max(w, h) * 0.08)
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(width, x + w + pad)
        y2 = min(height, y + h + pad)
        crop = image[y1:y2, x1:x2]
        if crop.size:
            candidates.append(_pil_from_cv_gray(crop))

        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect)
        ordered = _order_points(box)
        rect_width = int(max(np.linalg.norm(ordered[2] - ordered[3]), np.linalg.norm(ordered[1] - ordered[0])))
        rect_height = int(max(np.linalg.norm(ordered[1] - ordered[2]), np.linalg.norm(ordered[0] - ordered[3])))
        if rect_width < 80 or rect_height < 80:
            continue
        target = np.array(
            [[0, 0], [rect_width - 1, 0], [rect_width - 1, rect_height - 1], [0, rect_height - 1]],
            dtype="float32",
        )
        matrix = cv2.getPerspectiveTransform(ordered, target)
        warped = cv2.warpPerspective(image, matrix, (rect_width, rect_height), borderValue=255)
        if warped.shape[0] > warped.shape[1]:
            candidates.append(_pil_from_cv_gray(warped))
        else:
            candidates.append(_pil_from_cv_gray(cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)))

    return candidates


def _prepare_for_tesseract(image_bytes: bytes) -> list[Image.Image]:
    candidates: list[Image.Image] = []
    seen_sizes: set[tuple[int, int, int]] = set()
    source_images = _label_region_candidates(image_bytes)
    source_images.append(Image.open(BytesIO(image_bytes)).convert("L"))

    for source_index, raw_image in enumerate(source_images[:3]):
        image = ImageOps.autocontrast(raw_image)
        width, height = image.size
        if max(width, height) < 1800:
            scale = 1800 / max(width, height)
            image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

        sharp = image.filter(ImageFilter.SHARPEN)
        angles = (0,) if source_index < 2 else (0, -45, 45)
        variants = ((sharp, angles),)
        for source, angles in variants:
            for angle in angles:
                candidate = source.rotate(angle, expand=True, fillcolor=255)
                key = (candidate.width, candidate.height, angle)
                if key not in seen_sizes:
                    seen_sizes.add(key)
                    candidates.append(candidate)
                    if len(candidates) >= 8:
                        return candidates

    binary = ImageOps.autocontrast(source_images[0]).point(lambda value: 255 if value > 155 else 0) if source_images else None
    if binary is not None:
        candidate = binary.rotate(0, expand=True, fillcolor=255)
        key = (candidate.width, candidate.height, 0)
        if key not in seen_sizes:
            candidates.append(candidate)
    return candidates


def _image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _resize_for_ocr(image: Image.Image, max_side: int) -> Image.Image:
    width, height = image.size
    if max(width, height) <= max_side:
        return image
    scale = max_side / max(width, height)
    return image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)


def _rapidocr_candidate_bytes(image_bytes: bytes) -> list[bytes]:
    max_side = int(getenv("RAPIDOCR_IMAGE_MAX_SIDE", "1100"))
    candidates: list[bytes] = []
    seen_sizes: set[tuple[int, int]] = set()

    for image in _label_region_candidates(image_bytes)[:2]:
        resized = _resize_for_ocr(image.convert("RGB"), max_side)
        seen_sizes.add(resized.size)
        candidates.append(_image_to_png_bytes(resized))

    original = Image.open(BytesIO(image_bytes)).convert("RGB")
    width, height = original.size

    # На фото длинной бирки контур часто сливается с пальцами или светлым
    # фоном. Перекрывающиеся вертикальные фрагменты дают OCR более крупный
    # текст и позволяют прочитать нижние строки с размером и номером партии.
    if height >= width:
        crop_boxes = [
            (0, 0, max(1, round(width * 0.78)), height),
            (max(0, round(width * 0.22)), 0, width, height),
        ]
        for box in crop_boxes:
            crop = original.crop(box)
            resized_crop = _resize_for_ocr(crop, max_side)
            candidates.append(_image_to_png_bytes(resized_crop))

    resized_original = _resize_for_ocr(original, max_side)
    if resized_original.size not in seen_sizes:
        candidates.append(_image_to_png_bytes(resized_original))

    return candidates[:5]


def _rapidocr_text(image_bytes: bytes) -> str:
    global _RAPIDOCR_ENGINE

    if getenv("OCR_ENGINE", "").strip().lower() == "tesseract_only":
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

    chunks: list[str] = []
    seen: set[str] = set()
    for candidate in _rapidocr_candidate_bytes(image_bytes):
        try:
            result = _RAPIDOCR_ENGINE(candidate)
        except Exception:
            continue

        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if not txts:
            continue

        for index, text in enumerate(txts):
            score = scores[index] if scores and index < len(scores) else 1.0
            clean_text = str(text).strip()
            if clean_text and score >= 0.35 and clean_text not in seen:
                seen.add(clean_text)
                chunks.append(clean_text)

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
    if rapid_text:
        return rapid_text

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


def _normalize_label_size(value: str) -> str:
    return {
        "3XI": "3XL",
        "XXI": "XXL",
        "XI": "XL",
    }.get(value, value)


def _extract_first_photo(text: str, label_type: str = MAIN_LABEL_TYPE) -> tuple[str, str, str, str]:
    compact = _compact(text)
    if label_type == CLG2026_LABEL_TYPE:
        art = _find_first([
            r"ART(?:ICLE|ICOLO|ICOL)?\.?([A-Z0-9]{17})(?=COLOR|COLOUR|COL|TG|T9|SIZE|$)",
            r"(K[A-Z0-9]{16})",
        ], compact)
        code = _find_first([
            r"(?:LOT|BATCH|CODE|COD)\.?([A-Z0-9]{17})",
            r"(?:T[GQ9]|SIZE)\.?(?:3X[L1I]|XX[L1I]|X[L1I]|S|M|L)([A-Z0-9]{17})",
            r"(\d{2}PRO[A-Z][A-Z0-9]{11})",
            r"(PRO[A-Z][A-Z0-9]{13})",
        ], compact)
    else:
        art = _find_first([
            r"ART(?:ICLE|ICOLO|ICOL)?\.?(\d{9})(?!\d)",
            r"(?<!\d)(\d{9})(?!\d)",
        ], compact)
        code = _find_first([r"(TOM\d{6})(?!\d)"], compact)

    color = _find_first([
        r"(?:COLOR|COLOUR|COL)\.?([A-Z0-9]{5})",
        r"(V[A-Z0-9]{4})",
        r"([A-Z]\d{4})",
    ], compact)
    size = _find_first([
        r"T[GQ9]\.?(3X[L1I]|XX[L1I]|X[L1I]|S|M|L)",
        r"SIZE\.?(3XL|XXL|XL|S|M|L)",
    ], compact)
    size = _normalize_label_size(size.replace("1", "I"))

    if code in {art, color}:
        code = ""

    return art, color, size, code


def _extract_second_photo(text: str, qr_data: str) -> tuple[str, str]:
    combined = _compact(text) + "\n" + _compact(qr_data)
    certilogo_code = _find_first([
        r"(CLG\d{12})(?!\d)",
        r"CLG[^0-9]*(\d{12})(?!\d)",
        r"(?<!\d)(\d{12})(?!\d)",
    ], combined)
    if certilogo_code.startswith("CLG"):
        certilogo_code = certilogo_code[3:]

    certilogo_url = _find_first([f"({CERTILOGO_URL_PATTERN})"], combined)
    if certilogo_url:
        certilogo_url = "http://certilogo.com/qr/" + certilogo_url.rsplit("/", maxsplit=1)[-1].upper()

    return certilogo_code, certilogo_url


def _recognize_label_photos_sync(
    *,
    first_photo: bytes,
    second_photo: bytes,
    label_type: str = MAIN_LABEL_TYPE,
) -> ImageLabelData:
    first_text = _ocr_text(first_photo)
    qr_data = _read_qr(second_photo)
    second_text = _ocr_text(second_photo)

    art, color, size, code = _extract_first_photo(first_text, label_type)
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
        logger.info(
            "Photo OCR missing fields %s; first=%s; second=%s; qr=%s",
            ",".join(missing),
            _debug_snippet("OCR 1", first_text, limit=250),
            _debug_snippet("OCR 2", second_text, limit=250),
            qr_data or "-",
        )
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
    label_type: str = MAIN_LABEL_TYPE,
) -> ImageLabelData:
    return await asyncio.to_thread(
        _recognize_label_photos_sync,
        first_photo=first_photo,
        second_photo=second_photo,
        label_type=label_type,
    )
