"""ECG image digitiser: paper ECGs as PDF (vector or scanned) and as images (scans, photographs).

What it reads
  layouts      3 x 4 + lead II rhythm strip (the common printout), 6 x 2, and 12 x 1
  vector PDF   the traces are drawn as paths (most cart and ECG-management exports): read exactly
  images       PNG / JPEG / TIFF, or a PDF that only holds a scanned picture: the grid is found by colour
               and its period (1 mm), the page is straightened, and each trace is followed column by column
Scale        25 mm/s and 10 mm/mV unless the printout says otherwise ("50 mm/s", "5 mm/mV")

The result is a ParsedEcg whose `layout` says which part of 10 s each lead covers (a 3 x 4 printout shows each
lead for 2.5 s; lead II for 10 s). The engine analyses printouts with the model trained on that layout.
"""

from __future__ import annotations

import io
import re

import numpy as np

from .common import IngestError, LEADS, finish

FS = 500.0
PT_PER_MM = 72 / 25.4
LAYOUT_3x4 = [["I", "AVR", "V1", "V4"], ["II", "AVL", "V2", "V5"], ["III", "AVF", "V3", "V6"]]
LAYOUT_6x2 = [["I", "V1"], ["II", "V2"], ["III", "V3"], ["AVR", "V4"], ["AVL", "V5"], ["AVF", "V6"]]
LAYOUT_12x1 = [[lead] for lead in LEADS]


# ------------------------------------------------------------------ shared: rows of (time, mV) samples -> leads
def _rows_to_leads(rows: list[tuple[np.ndarray, np.ndarray]], speed: float, gain: float, notes: list[str]):
    """rows: per printed row, x and y in millimetres (y up), sorted by x, top row first.
    Returns (leads, layout name). Each lead is 10 s at FS Hz, zero outside the part the printout shows."""
    n_rows = len(rows)
    if n_rows == 4:
        grid, rhythm, name = LAYOUT_3x4, "II", "print-3x4"
    elif n_rows == 6:
        grid, rhythm, name = LAYOUT_6x2, None, "print-6x2"
    elif n_rows == 12:
        grid, rhythm, name = LAYOUT_12x1, None, "print-12x1"
    elif n_rows == 3:
        grid, rhythm, name = LAYOUT_3x4, None, "print-3x4"
        notes.append("no rhythm strip found: lead II is only in its own column")
    else:
        raise IngestError(f"digitiser: found {n_rows} trace rows; expected a 3 x 4 (+ rhythm), 6 x 2 or 12 x 1 layout")
    n = int(10 * FS)
    t_axis = np.arange(n) / FS
    leads = {k: np.zeros(n) for k in LEADS}
    windows = {}
    for r, (x, y) in enumerate(rows[: len(grid)]):
        t = (x - x[0]) / speed
        cols = len(grid[r])
        span = t[-1] if t[-1] > 0 else 10.0
        scale = 10.0 / span if abs(span - 10.0) > 0.25 else 1.0  # a printout whose row is not exactly 10 s at this speed
        t = t * scale
        for c, lead in enumerate(grid[r]):
            a, b = c * 10.0 / cols, (c + 1) * 10.0 / cols
            sel = (t >= a) & (t <= b)
            if sel.sum() < 10:
                continue
            base = np.median(y[sel])
            ia, ib = int(round(a * FS)), int(round(b * FS))
            leads[lead][ia:ib] = np.interp(t_axis[ia:ib], t[sel], (y[sel] - base) / gain)
            windows[lead] = (ia, ib)
    if rhythm is not None and len(rows) > len(grid):
        x, y = rows[len(grid)]
        t = (x - x[0]) / speed
        span = t[-1] if t[-1] > 0 else 10.0
        t = t * (10.0 / span if abs(span - 10.0) > 0.25 else 1.0)
        base = np.median(y)
        leads[rhythm] = np.interp(t_axis, t, (y - base) / gain)
        windows[rhythm] = (0, n)
    missing = [k for k in LEADS if k not in windows]
    if missing:
        raise IngestError(f"digitiser: no trace found for {', '.join(missing)}")
    return leads, name, windows


def _scale_from_text(text: str, notes: list[str]) -> tuple[float, float]:
    speed, gain = 25.0, 10.0
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*mm\s*/\s*s(?!\w)", text)
    if m:
        speed = float(m.group(1).replace(",", "."))
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*mm\s*/\s*mV", text, flags=re.I)
    if m:
        gain = float(m.group(1).replace(",", "."))
    if not text:
        notes.append("paper speed and gain not printed: 25 mm/s and 10 mm/mV assumed")
    return speed, gain


def _fit_layout(rows: list[tuple[np.ndarray, np.ndarray]]) -> list[tuple[np.ndarray, np.ndarray]]:
    """Large waves can split one printed row into two bands: merge rows whose baselines are < 12 mm apart, then
    keep the layout-sized set of the longest rows."""
    if len(rows) in (3, 4, 6, 12):
        return rows
    merged: list[tuple[np.ndarray, np.ndarray]] = []
    for x, y in rows:
        if merged and abs(np.median(merged[-1][1]) - np.median(y)) < 12:
            mx, my = merged[-1]
            xs, ys = np.concatenate([mx, x]), np.concatenate([my, y])
            o = np.argsort(xs, kind="stable")
            xs, ys = xs[o], ys[o]
            keep = np.r_[True, np.diff(xs) > 1e-6]
            merged[-1] = (xs[keep], ys[keep])
        else:
            merged.append((x, y))
    if len(merged) in (3, 4, 6, 12):
        return merged
    for target in (12, 6, 4):
        if len(merged) > target:
            longest = sorted(range(len(merged)), key=lambda i: -(merged[i][0][-1] - merged[i][0][0]))[:target]
            return [merged[i] for i in sorted(longest)]
    return merged


# ------------------------------------------------------------------ vector PDF
def _pdf_paths(page):
    """Stroked paths in page coordinates: [(points (k, 2), stroke grey level 0..1, width)]."""
    from pypdf.generic import ContentStream

    ops = ContentStream(page.get_contents(), page.pdf).operations
    ctm = np.eye(3)
    stack, width, colour = [], 1.0, 0.0
    paths, cur, sub = [], [], []

    def tx(xx, yy):
        p = np.array([xx, yy, 1.0]) @ ctm
        return p[0], p[1]

    for operands, op in ops:
        op = op.decode() if isinstance(op, bytes) else op
        v = [float(o) for o in operands] if op in ("cm", "m", "l", "c", "v", "y", "re", "w", "RG", "G", "K") else None
        if op == "q":
            stack.append((ctm.copy(), width, colour))
        elif op == "Q" and stack:
            ctm, width, colour = stack.pop()
        elif op == "cm":
            a, b, c, d, e, f = v
            ctm = np.array([[a, b, 0], [c, d, 0], [e, f, 1]]) @ ctm
        elif op == "w":
            width = v[0]
        elif op == "RG":
            colour = (0.3 * v[0] + 0.59 * v[1] + 0.11 * v[2], v[0] - v[1])
        elif op == "G":
            colour = (v[0], 0.0)
        elif op == "K":
            colour = (1 - v[3] - 0.3 * v[0] - 0.59 * v[1] - 0.11 * v[2], v[1] - v[0])
        elif op == "m":
            if len(sub) > 1:
                cur.append(sub)
            sub = [tx(*v)]
        elif op == "l":
            sub.append(tx(*v))
        elif op in ("c", "v", "y"):
            sub.append(tx(*v[-2:]))  # curve end point: carts draw traces with lines; curves only round corners
        elif op == "re":
            x0, y0, w_, h_ = v
            cur.append([tx(x0, y0), tx(x0 + w_, y0), tx(x0 + w_, y0 + h_), tx(x0, y0 + h_), tx(x0, y0)])
        elif op in ("S", "s", "B", "b", "B*", "b*"):
            if len(sub) > 1:
                cur.append(sub)
            for s in cur:
                paths.append((np.asarray(s, dtype=float), colour if isinstance(colour, tuple) else (colour, 0.0), width))
            cur, sub = [], []
        elif op in ("n", "f", "F", "f*"):
            cur, sub = [], []
    return paths


def from_pdf(data: bytes, fs: float | None = None, units: str | None = None):
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        page = reader.pages[0]
    except Exception as e:  # damaged PDF
        raise IngestError(f"digitiser: cannot read the PDF ({type(e).__name__})") from None
    notes = ["digitised from a PDF printout"]
    try:
        text = page.extract_text() or ""
    except Exception:
        text = ""
    paths = _pdf_paths(page)
    traces = [(p, w) for p, (grey, red), w in paths if len(p) >= 20 and grey < 0.45 and red < 0.3]
    if not traces:
        images = page.images if hasattr(page, "images") else []
        if images:  # a scanned printout saved as PDF
            notes = ["digitised from a scanned PDF"]
            return from_image(images[0].data, fs, notes=notes, text=text)
        raise IngestError("digitiser: this PDF has no ECG traces (no drawn paths and no scanned image)")
    # millimetre scale from the grid: thin, pink/red, axis-aligned two-point lines
    grid_x = np.unique(np.round([p[0, 0] for p, (grey, red), w in paths if len(p) == 2 and abs(p[0, 0] - p[1, 0]) < 0.01 and (red > 0.1 or grey > 0.5)], 3))
    mm = PT_PER_MM
    if len(grid_x) > 20:
        d = np.diff(grid_x)
        d = d[d > 0.5]
        if len(d):
            step = float(np.median(d))
            # refine over the whole grid: rounding of single positions would stretch 10 s by a few milliseconds
            k = round((grid_x[-1] - grid_x[0]) / step)
            step = float((grid_x[-1] - grid_x[0]) / k) if k > 0 else step
            mm = step if 0.6 * PT_PER_MM < step < 1.6 * PT_PER_MM else step / 5 if 0.6 * PT_PER_MM < step / 5 < 1.6 * PT_PER_MM else PT_PER_MM
    else:
        notes.append("no millimetre grid in the PDF: the page is assumed printed at true scale")
    speed, gain = _scale_from_text(text, notes)
    # group trace pieces into printed rows by their vertical position
    pts = [(p / mm, float(np.median(p[:, 1])) / mm) for p, _ in traces]
    pts.sort(key=lambda t: -t[1])
    rows: list[list[np.ndarray]] = []
    centres: list[float] = []
    for p, yc in pts:
        if centres and abs(centres[-1] - yc) < 8:  # within 8 mm of the row's centre: the same row
            rows[-1].append(p)
        else:
            rows.append([p])
            centres.append(yc)
    merged = []
    for parts in rows:
        allp = np.concatenate(parts)
        order = np.argsort(allp[:, 0], kind="stable")
        allp = allp[order]
        keep = np.r_[True, np.diff(allp[:, 0]) > 1e-6]
        merged.append((allp[keep, 0], allp[keep, 1]))
    merged = [r for r in merged if r[0][-1] - r[0][0] > 30]  # full rows are tens of millimetres long
    leads, layout, windows = _rows_to_leads(merged, speed, gain, notes)
    ecg = finish(FS, leads, "pdf-printout", notes=notes)
    ecg.layout, ecg.windows = layout, windows
    return ecg


# ------------------------------------------------------------------ images (scans, photographs)
def _load_image(data: bytes):
    from PIL import Image, ImageOps

    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as e:
        raise IngestError(f"digitiser: cannot read the image ({type(e).__name__})") from None
    if im.width < 600:
        raise IngestError("digitiser: the image is too small; scan at 150 dpi or more")
    if im.width > 4000:
        im = im.resize((4000, int(im.height * 4000 / im.width)))
    if im.height > im.width * 1.15:  # portrait photo of a landscape printout
        im = im.rotate(90, expand=True)
    return im


def _masks(rgb: np.ndarray):
    r, g, b = rgb[..., 0].astype(np.int16), rgb[..., 1].astype(np.int16), rgb[..., 2].astype(np.int16)
    lum = (0.3 * r + 0.59 * g + 0.11 * b)
    bg = np.percentile(lum, 90)  # paper brightness (photos are darker than scans)
    trace = (lum < bg * 0.55) & ((r - g) < 60)
    grid = ((r - g) > 25) & (lum > bg * 0.45)
    return trace, grid


def _deskew(im):
    """Rotate so the grid lines are straight (search ±4°)."""
    small = im.resize((800, int(im.height * 800 / im.width)))
    _, grid = _masks(np.asarray(small))
    from PIL import Image
    best, best_a = -1.0, 0.0
    g = Image.fromarray((grid * 255).astype(np.uint8))
    for a in np.arange(-4, 4.01, 0.25):
        prof = np.asarray(g.rotate(a, resample=Image.BILINEAR)).sum(1).astype(float)
        score = prof.var()
        if score > best:
            best, best_a = score, a
    return (im.rotate(best_a, resample=Image.BICUBIC, fillcolor=(255, 255, 255)) if abs(best_a) > 0.1 else im), best_a


def _grid_period(grid: np.ndarray) -> float | None:
    """Pixels per millimetre from the grid's repeat (1 mm minor lines, or 5 mm major lines only)."""
    prof = grid.sum(0).astype(float)
    if prof.max() <= 0:
        return None
    prof = prof - prof.mean()
    spec = np.abs(np.fft.rfft(prof * np.hanning(len(prof))))
    freqs = np.fft.rfftfreq(len(prof))
    ok = (freqs > 1 / 80) & (freqs < 1 / 2.5)
    if not ok.any():
        return None
    f = freqs[ok][np.argmax(spec[ok])]
    period = 1 / f
    # a strong component at period/5 means `period` is the 5 mm major grid
    major = period
    fm = 5 / major
    near = np.argmin(abs(freqs - fm))
    mm = major / 5 if (fm < 0.5 and spec[near] > 0.15 * spec[ok].max()) or period >= 12 else major
    # refine: the autocorrelation peak near 40 periods pins the period to a fraction of a percent
    ac = np.correlate(prof, prof, mode="full")[len(prof) - 1:]
    k = 40
    centre = k * mm
    if centre * 1.03 < len(ac) - 1:
        lo, hi = int(centre * 0.97), int(np.ceil(centre * 1.03))
        best = lo + int(np.argmax(ac[lo:hi + 1]))
        if 0 < best < len(ac) - 1:  # parabolic interpolation around the peak
            y0, y1, y2 = ac[best - 1], ac[best], ac[best + 1]
            den = y0 - 2 * y1 + y2
            best = best + (0.5 * (y0 - y2) / den if den != 0 else 0.0)
        mm = best / k
    return mm


def from_image(data: bytes, fs: float | None = None, notes: list[str] | None = None, text: str = "", units: str | None = None):
    notes = list(notes or ["digitised from an image"])
    im = _load_image(data)
    im, angle = _deskew(im)
    if abs(angle) > 0.1:
        notes.append(f"image straightened by {angle:.1f}°")
    rgb = np.asarray(im)
    trace, grid = _masks(rgb)
    ppm = _grid_period(grid)
    if ppm is None or not 2 <= ppm <= 40:
        ppm = im.width / 297.0  # an A4 landscape page
        notes.append("no ECG grid found: an A4 landscape page width is assumed for the scale")
    speed, gain = _scale_from_text(text, notes)
    if not text:
        notes[-1:] = ["paper speed and gain read as 25 mm/s and 10 mm/mV (standard)"]
    # trace rows from the horizontal profile of dark pixels
    prof = np.convolve(trace.sum(1).astype(float), np.ones(int(3 * ppm)) / (3 * ppm), mode="same")
    thr = 0.15 * prof.max()
    bands, inside, start = [], False, 0
    for i, v in enumerate(prof):
        if v > thr and not inside:
            inside, start = True, i
        elif v <= thr and inside:
            inside = False
            if i - start > 2 * ppm:
                bands.append((start, i))
    if inside:
        bands.append((start, len(prof)))
    # bands carrying a full-width trace (text lines are short)
    rows = []
    for a, b in bands:
        pad = int(6 * ppm)
        a2, b2 = max(0, a - pad), min(trace.shape[0], b + pad)
        cols = trace[a2:b2].any(0)
        # longest run of columns with trace, allowing 2 mm gaps (lead change markers)
        runs, s, gap = [], None, 0
        for xi, on in enumerate(cols):
            if on:
                if s is None:
                    s = xi
                gap = 0
            elif s is not None:
                gap += 1
                if gap > 2 * ppm:
                    runs.append((s, xi - gap))
                    s, gap = None, 0
        if s is not None:
            runs.append((s, len(cols) - 1))
        if not runs:
            continue
        x0, x1 = max(runs, key=lambda r: r[1] - r[0])
        if (x1 - x0) / ppm < 60:  # shorter than 60 mm: a label or text, not an ECG row
            continue
        if cols[x0:x1 + 1].mean() < 0.85:  # a trace fills (almost) every column; a line of text has gaps between letters
            continue
        if grid[a:b, x0:x1].mean() < 0.02 and grid.mean() > 0.01:  # outside the printed grid (header / footer text)
            continue
        # follow the stroke: in each pixel column take the run of dark pixels that continues the previous point
        # (a neighbouring row's QRS or a printed lead label in the same column is a separate run and is skipped)
        band = trace[a2:b2]
        prof_band = band[:, x0:x1 + 1].sum(1)
        prev = float(a2 + np.argmax(prof_band))
        xs, ys = [], []
        for xi in range(x0, x1 + 1):
            rr = np.flatnonzero(band[:, xi]) + a2
            if len(rr) == 0:
                continue
            cuts = np.flatnonzero(np.diff(rr) > 1)
            runs_y = np.split(rr, cuts + 1)
            dist = [0.0 if r_[0] <= prev <= r_[-1] else min(abs(r_[0] - prev), abs(r_[-1] - prev)) for r_ in runs_y]
            run = runs_y[int(np.argmin(dist))]
            if min(dist) > 8 * ppm:  # nothing near the trace in this column (a gap in the print)
                continue
            lo, hi = float(run[0]), float(run[-1])
            yv = (lo if abs(lo - prev) > abs(hi - prev) else hi) if hi - lo > 3 else float(run.mean())
            xs.append(xi)
            ys.append(yv)
            prev = yv
        if len(xs) < 50:
            continue
        xs, ys = np.asarray(xs, float), np.asarray(ys, float)
        rows.append((xs / ppm, -ys / ppm))  # millimetres, y up
    if not rows:
        raise IngestError("digitiser: no ECG traces found in the image")
    rows = _fit_layout(rows)
    leads, layout, windows = _rows_to_leads(rows, speed, gain, notes)
    ecg = finish(FS, leads, "image-printout", notes=notes)
    ecg.layout, ecg.windows = layout, windows
    return ecg
