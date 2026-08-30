"""
OCR ingestion for the Benford's Law Fraud Detector.

Takes a photo/scan of a document (CV, invoice, expense report, bank
statement, whatever), runs it through Tesseract OCR (Tesseract 4+ uses an
LSTM neural network under the hood, so this genuinely is "AI reads the
document", not simple template matching), pulls every number out of the
raw text, and hands that list straight to app.benford.analyze().

Two ways to run this file:

    python -m app.ocr path/to/photo.jpg              # OCR -> Benford analysis
    python -m app.ocr path/to/photo.jpg --text-only   # just show extracted text

Setup (one-time, per machine):

    pip install pytesseract Pillow

    Tesseract itself is a separate system binary pytesseract calls out to:
      macOS   : brew install tesseract
      Ubuntu  : sudo apt install tesseract-ocr
      Windows : install from https://github.com/UB-Mannheim/tesseract/wiki
                then set pytesseract.pytesseract.tesseract_cmd to the .exe path
"""

import re
import sys
from dataclasses import dataclass
from typing import NotRequired, TypedDict

try:
    import pytesseract
    from PIL import Image, ImageFilter, ImageOps
except ImportError as exc:  # pragma: no cover - guidance for the user
    raise SystemExit(
        "Missing OCR dependencies. Install them with:\n"
        "    pip install pytesseract Pillow\n"
        "and make sure the Tesseract binary itself is installed on your OS "
        "(see the docstring at the top of app/ocr.py).\n"
        f"Original error: {exc}"
    )

from app.benford import BenfordResult, analyze
from app.engines.card import luhn_valid as _luhn_valid_raw, card_network as _card_network_raw


@dataclass
class OcrCardCandidate:
    """Metadata for an OCR-extracted card number candidate."""
    digits: str
    luhn_valid: bool
    network: str | None
    variant_agreement: int   # how many unique OCR texts contained this candidate
    total_variants: int      # total unique OCR texts examined

# Matches numbers like 1,234.56 / -42 / 0.99 / 3400 while ignoring stray
# letters/punctuation OCR tends to pick up around them.
NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")

# Same, but only numbers immediately preceded by a currency symbol — this is
# what actually distinguishes a dollar value from an "Item 3:" style label,
# line number, date, or page number that OCR would otherwise sweep in.
CURRENCY_NUMBER_PATTERN = re.compile(r"[\$£€₹]\s?-?\d[\d,]*\.?\d*")


class OCRAnalysisResult(BenfordResult, total=False):
    ocr_text: str
    extracted_numbers: list[float]


def preprocess_image(image_path: str) -> Image.Image:
    """
    Light cleanup that measurably improves OCR accuracy on phone photos:
    convert to grayscale and auto-contrast. No external ML model needed
    for this step, it's just classic image preprocessing.
    """
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)  # respect phone camera orientation
    img = img.convert("L")  # grayscale
    img = ImageOps.autocontrast(img)
    return img


def extract_text(image_path: str) -> str:
    """Run Tesseract OCR on an image and return the raw extracted text."""
    img = preprocess_image(image_path)
    return pytesseract.image_to_string(img)


def _parse_matches(matches: list[str]) -> list[float]:
    numbers: list[float] = []
    for match in matches:
        cleaned = match.lstrip("$£€₹").strip().replace(",", "")
        if cleaned in ("", "-", "."):
            continue
        try:
            numbers.append(float(cleaned))
        except ValueError:
            continue
    return numbers


def extract_numbers(text: str) -> list[float]:
    """
    Pull the meaningful numbers out of OCR'd text.

    Prefers numbers with a currency symbol directly in front of them ($120,
    £45.50, etc) since those are almost always the real data points in a
    financial document — as opposed to item indices ("Item 3:"), page
    numbers, or dates, which Benford's Law was never meant to test and
    which would just add noise to the chi-square score.

    If no currency-tagged numbers are found at all (e.g. a plain table of
    figures with no $ signs), falls back to grabbing every number in the
    text, since something is better than nothing.
    """
    currency_matches = CURRENCY_NUMBER_PATTERN.findall(text)
    if currency_matches:
        return _parse_matches(currency_matches)
    return _parse_matches(NUMBER_PATTERN.findall(text))


def analyze_document(image_path: str) -> OCRAnalysisResult:
    """
    Full pipeline: image -> OCR text -> extracted numbers -> Benford analysis.
    """
    text = extract_text(image_path)
    numbers = extract_numbers(text)
    result = analyze(numbers)
    return OCRAnalysisResult(
        total_count=result["total_count"],
        invalid_count=result["invalid_count"],
        observed_counts=result["observed_counts"],
        observed_frequencies=result["observed_frequencies"],
        expected_frequencies=result["expected_frequencies"],
        chi_square=result["chi_square"],
        ocr_text=text,
        extracted_numbers=numbers,
    )


def _print_document_results(image_path: str) -> None:
    text = extract_text(image_path)
    numbers = extract_numbers(text)

    print()
    print("=" * 62)
    print(f" OCR: {image_path}")
    print("=" * 62)
    print(" Raw extracted text:")
    print("-" * 62)
    print(text.strip() or "(no text detected)")
    print("-" * 62)
    print(f" Numbers found ({len(numbers)}): {numbers}")

    if len(numbers) < 10:
        print()
        print(" Note: Fewer numbers found — results are less precise")
        print(" but the AI verdict will account for this.")

    if numbers:
        result = analyze(numbers)
        print()
        print(f" Total analysed : {result['total_count']}  (rejected: {result['invalid_count']})")
        print(f" Chi-square     : {result['chi_square']:.4f}")
        print(f"  (lower = closer to Benford's Law; ~16.9+ at 8 dof suggests")
        print(f"   the data does NOT follow Benford's Law)")
    print()


# ---------------------------------------------------------------------------
# Card-specific OCR extraction (Phase 20)
# ---------------------------------------------------------------------------

_CARD_CANDIDATE_RE = re.compile(
    r"(?:\d[\s\-]?){13,19}"
)

_OCR_DIGIT_FIXES: dict[str, str] = {
    "O": "0", "o": "0", "Q": "0",
    "I": "1", "l": "1",
    "Z": "2", "z": "2",
    "S": "5", "s": "5",
    "B": "8",
    "G": "6",
}


def _to_grayscale(img: Image.Image) -> Image.Image:
    if img.mode == "L":
        return img
    return img.convert("L")


def _sharpen(img: Image.Image) -> Image.Image:
    return img.filter(ImageFilter.SHARPEN)


def _upscale(img: Image.Image, factor: int = 2) -> Image.Image:
    new_w = img.width * factor
    new_h = img.height * factor
    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


# Tesseract's models are trained on text at roughly 300 DPI. A full page held
# below that loses its *smallest* type first — which on an invoice is precisely
# the totals block, while the large "TOTAL" survives. Scaling by a fixed factor
# cannot express that requirement: what matters is the resulting resolution, not
# the multiple. A 465x659 invoice needs 3x; a 4000px phone photo needs none.
_TARGET_LONG_EDGE = 2000

# Past roughly 4x, LANCZOS is inventing detail rather than recovering it, and
# accuracy starts falling again while every Tesseract pass gets slower.
_MAX_UPSCALE = 4.0

# Below this, resampling costs time and softens edges for no real gain.
_MIN_WORTHWHILE_UPSCALE = 1.15


def _scale_for_ocr(img: Image.Image) -> Image.Image:
    """Scale an image up toward the resolution Tesseract expects.

    Only ever enlarges: a photo that is already big enough is returned
    untouched, so this costs nothing on the inputs that never needed it.
    """
    long_edge = max(img.width, img.height)
    if long_edge <= 0:
        return img

    factor = min(_TARGET_LONG_EDGE / long_edge, _MAX_UPSCALE)
    if factor < _MIN_WORTHWHILE_UPSCALE:
        return img

    return img.resize(
        (round(img.width * factor), round(img.height * factor)),
        Image.Resampling.LANCZOS,
    )


def create_ocr_variants(img: Image.Image) -> list[tuple[str, Image.Image]]:
    """Create a small set of preprocessing variants for robust OCR.

    Kept deliberately short: each variant costs a full Tesseract pass (or several,
    with multiple PSM modes), so more variants directly means more latency. These
    two cover the cases that actually matter for phone photos of cards/documents —
    plain contrast-boosted grayscale, and a hard black/white threshold for
    low-contrast or glare-heavy shots.

    Scaling to a workable resolution happens once, on the shared base, so every
    variant sees legible type. It used to be a third variant at a fixed 2x, which
    meant the contrast and threshold passes still ran against under-resolution
    pixels and only one pass in three had a chance on small print.
    """
    variants: list[tuple[str, Image.Image]] = []

    gray = _scale_for_ocr(_to_grayscale(img))
    contrast = ImageOps.autocontrast(gray, cutoff=2)
    variants.append(("contrast", contrast))

    try:
        threshold_lut = [0] * 128 + [255] * 128
        bw = contrast.point(threshold_lut, "1")
        variants.append(("threshold", bw))
    except Exception:
        pass

    return variants


def _ocr_with_psm(img: Image.Image, psm_modes: list[int]) -> str:
    """Run Tesseract with a small set of PSM modes, return combined text."""
    texts: list[str] = []
    for mode in psm_modes:
        config = f"--psm {mode}"
        try:
            text = pytesseract.image_to_string(img, config=config)
            if text.strip():
                texts.append(text)
        except Exception:
            continue
    return "\n".join(texts)


# Two modes cover the vast majority of real documents: 6 (a single uniform block
# of text — the common case for a card/ID crop) and 11 (sparse text, no
# particular layout — good fallback for noisy scans). The previous 4-mode set
# (3, 6, 11, 4) roughly doubled OCR time for marginal extra recall.
_PSM_MODES = [6, 11]


def _extract_unique_texts(
    image_path: str, *, stop_early: bool = True, dedupe: bool = True
) -> list[str]:
    """Run OCR across a small set of preprocessing variants and return the texts.

    When stop_early is True (the default for card-candidate extraction), OCR stops
    as soon as a variant yields a candidate that both matches a known card network
    and passes Luhn — that combination is strong enough evidence that trying more
    variants just costs time for no benefit.

    `dedupe` collapses passes that read the page identically. That is right for
    card extraction, which wants distinct candidates to score against each other,
    and wrong for anything measuring agreement between passes: two variants
    returning the same text is the strongest corroboration available, and
    discarding one of them reports it as the weakest.
    """
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)

    variants = create_ocr_variants(img)

    seen: set[str] = set()
    texts: list[str] = []
    for _name, variant_img in variants:
        text = _ocr_with_psm(variant_img, _PSM_MODES)
        stripped = text.strip()
        if not stripped:
            continue
        if dedupe and stripped in seen:
            continue
        seen.add(stripped)
        texts.append(text)
        if stop_early and _has_confident_card_candidate(text):
            break
    return texts


def _has_confident_card_candidate(text: str) -> bool:
    """True if text contains a digit run that matches a known network AND passes Luhn."""
    for digits in extract_card_candidates_from_text(text):
        if _detect_card_network(digits) and _luhn_check(digits):
            return True
    return False


def extract_text_multivariant(image_path: str) -> str:
    """Run OCR with multiple preprocessing variants and PSM modes.

    stop_early=False: this path is used for general document text (invoices,
    statements, etc.), not just card extraction, so a card-shaped match in one
    variant shouldn't cut off OCR before the rest of the document is captured.
    """
    return "\n".join(_extract_unique_texts(image_path, stop_early=False))


def extract_text_readings(image_path: str) -> list[str]:
    """Return each preprocessing variant's reading of the document separately.

    The concatenation above is right for "what does this document say"; keeping
    the readings apart is what lets arithmetic verification ask the different
    question of "did the passes agree on this number" — the only signal that
    separates a tampered document from a badly photographed one.

    Deliberately not deduplicated: passes that agree exactly are the whole point
    of asking, so collapsing them would erase the answer.
    """
    return _extract_unique_texts(image_path, stop_early=False, dedupe=False)


def normalize_ocr_text(text: str) -> str:
    """Normalize OCR output: fix common digit misreads, clean noise."""
    fixed = text
    for wrong, right in _OCR_DIGIT_FIXES.items():
        # Only fix a misread letter when it's directly touching a digit (e.g.
        # "1O83" or "83O0") — i.e. it's plausibly part of the same number. A
        # fully isolated letter-token (whitespace on both sides, like a stray
        # "o" from unrelated nearby text/logo noise) is left alone; correcting
        # it would fabricate an extra digit that then gets absorbed into an
        # adjacent real number by the card-candidate regex.
        escaped = re.escape(wrong)
        fixed = re.sub(rf"(?<=\d){escaped}(?!\w)", right, fixed)
        fixed = re.sub(rf"(?<!\w){escaped}(?=\d)", right, fixed)

    fixed = re.sub(r"[^\w\s\-/.,$€£₹]", " ", fixed)
    fixed = re.sub(r"[ \t]+", " ", fixed)
    fixed = re.sub(r" *\n *", "\n", fixed)
    return fixed.strip()


def _luhn_check(digits: str) -> bool:
    """Thin wrapper around the canonical Luhn check in app.engines.card."""
    return _luhn_valid_raw(digits)


def _detect_card_network(digits: str) -> str | None:
    """Thin wrapper around the canonical network detection in app.engines.card."""
    return _card_network_raw(digits)


def extract_card_candidates_from_text(text: str) -> list[str]:
    """Extract 13-19 digit card candidates from OCR text.

    Handles:
    - "4532 0151 1283 0366" (spaces between groups)
    - "4532-0151-1283-0366" (hyphens between groups)
    - "4532015112830366" (raw digits)
    - Multi-line splits (digits continuing across lines)
    """
    normalized = normalize_ocr_text(text)

    candidates: list[str] = []
    seen: set[str] = set()

    for match in _CARD_CANDIDATE_RE.finditer(normalized):
        raw = match.group()
        digits = re.sub(r"[^0-9]", "", raw)
        if 13 <= len(digits) <= 19 and digits not in seen:
            seen.add(digits)
            candidates.append(digits)

    lines = [l.strip() for l in normalized.split("\n") if l.strip()]
    for i in range(len(lines) - 1):
        if (re.search(r"\d$", lines[i]) and re.match(r"^\d", lines[i + 1])):
            merged = lines[i] + " " + lines[i + 1]
            for match in _CARD_CANDIDATE_RE.finditer(merged):
                raw = match.group()
                digits = re.sub(r"[^0-9]", "", raw)
                if 13 <= len(digits) <= 19 and digits not in seen:
                    seen.add(digits)
                    candidates.append(digits)

    for line in lines:
        digits = re.sub(r"[^0-9]", "", line)
        if 13 <= len(digits) <= 19 and digits not in seen:
            seen.add(digits)
            candidates.append(digits)

    return candidates


# Characters Tesseract most often returns in place of a digit when reading the
# stylised, embossed type used for card numbers. Used only to decide whether a
# line is *plausibly* the card-number line and therefore worth a targeted
# re-read — never to rewrite the digits themselves.
_DIGIT_CONFUSABLES = "OolIZzSsBGbgqQDUucCEeAaTtJjhkKxXnNMmVvWwRrPpFfYy"

# A card number line carries 13-19 digits. Requiring most of them to have
# survived the first pass as literal digits keeps expiry dates, CVVs and
# "VALID THRU" from being mistaken for the number line.
_MIN_LINE_DIGITS = 8
_MIN_LINE_DIGITISH = 12


def _digit_line_crops(img: Image.Image) -> list[Image.Image]:
    """Crop the lines of an image that look like a card-number line.

    Tesseract reads a whole card face at once with the layout analysis tuned for
    prose, which is what turns "1234 5678 9876 5432" into "234 5786 947k LSu3c".
    Isolating the number line lets it be re-read on its own terms — one line, one
    alphabet, no competing text — which is where the accuracy actually comes from.
    """
    try:
        data = pytesseract.image_to_data(
            img, config="--psm 6", output_type=pytesseract.Output.DICT
        )
    except Exception:
        return []

    lines: dict[tuple[int, int, int], list[int]] = {}
    for j in range(len(data["text"])):
        if not str(data["text"][j]).strip():
            continue
        key = (data["block_num"][j], data["par_num"][j], data["line_num"][j])
        lines.setdefault(key, []).append(j)

    crops: list[Image.Image] = []
    for idxs in lines.values():
        joined = "".join(str(data["text"][j]) for j in idxs)
        digits = sum(1 for c in joined if c.isdigit())
        digitish = sum(1 for c in joined if c.isdigit() or c in _DIGIT_CONFUSABLES)
        if digits < _MIN_LINE_DIGITS or digitish < _MIN_LINE_DIGITISH:
            continue

        x0 = min(data["left"][j] for j in idxs)
        y0 = min(data["top"][j] for j in idxs)
        x1 = max(data["left"][j] + data["width"][j] for j in idxs)
        y1 = max(data["top"][j] + data["height"][j] for j in idxs)
        pad = int((y1 - y0) * 0.4)
        crops.append(
            img.crop((
                max(0, x0 - pad),
                max(0, y0 - pad),
                min(img.width, x1 + pad),
                min(img.height, y1 + pad),
            ))
        )
    return crops


# PSM 13 treats the crop as a single raw line with no layout assumptions, which
# is what a cropped number line actually is; 7 is the slightly more structured
# fallback for crops that still carry a little surrounding noise.
_DIGIT_LINE_PSM = [13, 7]


def extract_digit_line_candidates(image_path: str) -> list[str]:
    """Re-read just the card-number line, with the alphabet restricted to digits.

    Constraining Tesseract to 0-9 removes the failure this whole path exists for:
    with letters available it will happily return "947k" for "9876", and no amount
    of downstream repair can recover the digit it never considered.
    """
    try:
        base = ImageOps.exif_transpose(Image.open(image_path)).convert("L")
    except Exception:
        return []

    found: list[str] = []
    seen: set[str] = set()

    # Light-on-dark is the common case for card art and the one Tesseract handles
    # worst, so both polarities are tried rather than guessing from the image.
    for invert in (False, True):
        img = ImageOps.invert(base) if invert else base
        img = ImageOps.autocontrast(img, cutoff=2)
        img = _scale_for_ocr(img)

        for crop in _digit_line_crops(img):
            enlarged = crop.resize(
                (crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS
            )
            for psm in _DIGIT_LINE_PSM:
                try:
                    text = pytesseract.image_to_string(
                        enlarged,
                        config=f"--psm {psm} -c tessedit_char_whitelist=0123456789 ",
                    )
                except Exception:
                    continue
                digits = re.sub(r"[^0-9]", "", text)
                if 13 <= len(digits) <= 19 and digits not in seen:
                    seen.add(digits)
                    found.append(digits)
    return found


# Sixteen digits is the overwhelmingly common card length, and 15 (Amex) and 14
# (Diners) are the real alternatives. Lengths above 16 are almost always two
# fields glued together by OCR rather than a genuine 19-digit card.
_LENGTH_PLAUSIBILITY: dict[int, int] = {16: 30, 15: 25, 14: 20, 13: 15}


def _score_card_candidates(
    candidates: list[str],
    unique_texts: list[str],
    digit_line_reads: frozenset[str] = frozenset(),
) -> list[tuple[str, int, int]]:
    """Score each card-number candidate by network match, Luhn validity, and
    cross-variant consensus, best first.

    Consensus counts a text as agreeing with a candidate only if that exact
    candidate was itself independently extracted from that text — not merely
    if the candidate's digits appear somewhere in the text's raw digit
    stream. The latter would let a truncated prefix (e.g. one OCR pass that
    only managed to read the first 13 of 16 digits) trivially "agree" with
    every text that actually contains the complete, longer number, since a
    text containing a number always contains that number's own prefix too —
    letting an incomplete read systematically outscore the correct one.
    """
    scored: list[tuple[str, int, int]] = []
    for c in candidates:
        consensus = sum(1 for t in unique_texts if c in extract_card_candidates_from_text(t))
        network = _detect_card_network(c)
        score = 0
        if network is not None:
            score += 200
        if _luhn_check(c):
            score += 50
        score += consensus * 15
        # A digit-restricted re-read of the isolated number line is the most
        # direct evidence available that these are the digits actually printed
        # on the card, so it outweighs a Luhn pass — which a wrong number can
        # satisfy by coincidence roughly one time in ten.
        if c in digit_line_reads:
            score += 100
        # Length used to contribute its own magnitude, which rewarded exactly
        # the failure it should have penalised: an over-long run produced by
        # gluing the number line to the expiry/CVV line beneath it scored
        # *higher* than the correct 16-digit read it was built from.
        score += _LENGTH_PLAUSIBILITY.get(len(c), 0)
        scored.append((c, score, consensus))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def extract_best_card_candidate(
    image_path: str,
    *,
    readings: list[str] | None = None,
    digit_line_rescan: bool = True,
) -> OcrCardCandidate | None:
    """Extract the best card number candidate from an image.

    Uses multi-variant OCR preprocessing to maximize extraction accuracy.
    Tracks variant consensus to measure OCR confidence.
    Returns an OcrCardCandidate with metadata, or None if nothing found.

    `readings` lets a caller that has already swept the page hand its passes in
    rather than paying for a second, near-identical sweep. The orchestrator does
    exactly that: it needs the readings for arithmetic verification anyway, and
    running both sweeps meant every image upload was OCR'd twice end to end.

    `digit_line_rescan` gates the targeted number-line re-read below. It is the
    most expensive step in the whole pipeline, and it is worth its cost only on
    an image that might actually carry a card number line.
    """
    unique_texts = readings if readings is not None else _extract_unique_texts(image_path)

    # A targeted re-read of the number line, which succeeds on exactly the cards
    # the full-page pass reads worst: stylised or embossed type on coloured art.
    # Its results are candidates in their own right, so a card whose number the
    # full-page pass mangled beyond recognition can still be recovered here.
    digit_line_reads = (
        extract_digit_line_candidates(image_path) if digit_line_rescan else []
    )

    combined = "\n".join(unique_texts)
    candidates = extract_card_candidates_from_text(combined)
    for digits in digit_line_reads:
        if digits not in candidates:
            candidates.append(digits)
    if not candidates:
        return None

    scored = _score_card_candidates(
        candidates, unique_texts, frozenset(digit_line_reads)
    )
    best_digits, _, best_consensus = scored[0]

    network = _detect_card_network(best_digits)
    return OcrCardCandidate(
        digits=best_digits,
        luhn_valid=_luhn_check(best_digits),
        network=network,
        variant_agreement=best_consensus,
        total_variants=len(unique_texts),
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python -m app.ocr path/to/image.jpg [--text-only]")
        sys.exit(1)

    path = args[0]
    text_only = "--text-only" in args

    if text_only:
        print(extract_text(path))
    else:
        _print_document_results(path)
