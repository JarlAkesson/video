#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


def _slug(s: str) -> str:
    # Normalize and strip diacritics, then keep a conservative filename alphabet.
    s = s.strip().replace(" ", "_")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("å", "a").replace("ä", "a").replace("ö", "o").replace("Å", "A").replace("Ä", "A").replace("Ö", "O")
    s = re.sub(r"[^A-Za-z0-9_\\-]+", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "untitled"


def _normalize_for_match(s: str) -> str:
    s = (s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\\s+", " ", s).strip()


def _title_tokens(title: str) -> list[str]:
    norm = _normalize_for_match(title)
    toks = [t for t in norm.split(" ") if len(t) >= 3 and t not in {"the", "and", "for"}]
    return toks[:10]


def _read_file_prefix(path: Path, n: int = 16) -> bytes:
    with path.open("rb") as f:
        return f.read(n)


def _extract_xml_text_from_mxl(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as zf:
            # Similar heuristic to musicxml tooling: first xml not in META-INF.
            names = [n for n in zf.namelist() if n.lower().endswith(".xml") and not n.startswith("META-INF/")]
            if not names:
                return None
            data = zf.read(names[0])
    except Exception:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="ignore")


def _extract_ascii_strings(blob: bytes, min_len: int = 4) -> list[str]:
    out: list[str] = []
    cur: list[int] = []
    for b in blob:
        if 32 <= b <= 126:
            cur.append(b)
            continue
        if len(cur) >= min_len:
            out.append(bytes(cur).decode("ascii", errors="ignore"))
        cur = []
    if len(cur) >= min_len:
        out.append(bytes(cur).decode("ascii", errors="ignore"))
    return out


def _verify_downloaded_file(path: Path, title: str) -> list[str]:
    """
    Best-effort sanity checks:
    - file header matches expected container type (PDF/MIDI/ZIP/XML)
    - title tokens appear somewhere in embedded text/metadata (very weak, warning-only)
    """
    warns: list[str] = []
    toks = _title_tokens(title)
    if not toks:
        return warns

    suf = path.suffix.lower()
    prefix = _read_file_prefix(path, 8)

    if suf == ".pdf" and not prefix.startswith(b"%PDF"):
        warns.append("Downloaded .pdf does not start with %PDF header.")
        return warns

    if suf in {".mid", ".midi"}:
        if not prefix.startswith(b"MThd"):
            warns.append("Downloaded MIDI does not start with MThd header.")
            return warns
        blob = path.read_bytes()
        hay = _normalize_for_match(" ".join(_extract_ascii_strings(blob)))
        if not any(t in hay for t in toks):
            warns.append("Could not find title tokens in MIDI metadata strings (may still be correct).")
        return warns

    if suf in {".mxl", ".mscz"} or prefix.startswith(b"PK"):
        xml_text = _extract_xml_text_from_mxl(path)
        if xml_text is None:
            warns.append("Could not extract XML payload from zip container (MXL/MSCZ).")
            return warns
        hay = _normalize_for_match(xml_text)
        if not any(t in hay for t in toks):
            warns.append("Could not find title tokens in extracted XML text (may still be correct).")
        return warns

    if suf in {".xml", ".musicxml"}:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            warns.append("Could not read MusicXML as text for verification.")
            return warns
        if "<score-partwise" not in text and "<score-timewise" not in text:
            warns.append("MusicXML file does not look like score-partwise/score-timewise.")
        hay = _normalize_for_match(text)
        if not any(t in hay for t in toks):
            warns.append("Could not find title tokens in MusicXML text (may still be correct).")
        return warns

    # Unknown type: do nothing.
    return warns

@dataclass(frozen=True)
class Row:
    number: str
    title: str
    composer_or_origin: str
    status: str
    source: str
    url: str
    fmt: str


def _read_rows(csv_path: Path) -> list[Row]:
    rows: list[Row] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if not r:
                continue
            number = (r.get("number") or "").strip()
            title = (r.get("title") or "").strip()
            composer_or_origin = (r.get("composer_or_origin") or "").strip()
            status = (r.get("copyright_status") or "").strip()
            source = (r.get("source") or "").strip()
            url = (r.get("url") or "").strip()
            fmt = (r.get("format") or "").strip().upper() or "PDF"
            if not (number and title and status and source and url):
                continue
            rows.append(
                Row(
                    number=number,
                    title=title,
                    composer_or_origin=composer_or_origin,
                    status=status,
                    source=source,
                    url=url,
                    fmt=fmt,
                )
            )
    return rows


def _download(url: str, out_path: Path, timeout_sec: float = 60.0) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CodexCLI/1.0; +https://openai.com/)",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # nosec - expected for controlled URLs
        out_path.write_bytes(resp.read())


def _format_priority(fmt: str) -> int:
    f = (fmt or "").strip().lower()
    if f in {"musicxml", "xml", "musicxml.gz"}:
        return 0
    if f == "mxl":
        return 1
    if f == "mscz":
        return 2
    if f in {"mid", "midi"}:
        return 3
    if f == "pdf":
        return 4
    if f in {"lyrics", "txt"}:
        return 5
    return 9


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _is_direct_score_url(url: str) -> bool:
    u = url.lower()
    return any(u.endswith(ext) for ext in (".musicxml", ".xml", ".mxl", ".mscz", ".mid", ".midi", ".pdf"))


def _guess_format_from_url(url: str) -> str:
    u = url.lower()
    if u.endswith(".musicxml") or u.endswith(".xml"):
        return "MUSICXML"
    if u.endswith(".mxl"):
        return "MXL"
    if u.endswith(".mscz"):
        return "MSCZ"
    if u.endswith(".mid") or u.endswith(".midi"):
        return "MIDI"
    if u.endswith(".pdf"):
        return "PDF"
    if u.endswith(".txt"):
        return "LYRICS"
    return "UNKNOWN"


def _search_duckduckgo_urls(query: str, max_results: int = 10, timeout_sec: float = 30.0) -> list[str]:
    # Best-effort HTML scraping (no API key). May break if DDG changes.
    q = urllib.parse.quote_plus(query)
    url = f"https://duckduckgo.com/html/?q={q}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CodexCLI/1.0; +https://openai.com/)",
            "Accept": "text/html,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # nosec - expected for controlled URLs
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError:
        # Some environments get blocked (403). Treat as "no results" rather than failing the run.
        return []
    except urllib.error.URLError:
        return []

    urls: list[str] = []
    for m in re.finditer(r'href="[^"]*uddg=([^"&]+)', html):
        try:
            u = urllib.parse.unquote(m.group(1))
        except Exception:
            continue
        if not u.startswith(("http://", "https://")):
            continue
        urls.append(u)
        if len(urls) >= max_results:
            break
    return _dedupe_preserve_order(urls)


def _candidate_urls_for_song(title: str, max_candidates: int) -> list[tuple[str, str]]:
    # Returns list of (fmt, url) in preference order.
    queries = [
        f"\"{title}\" filetype:musicxml",
        f"\"{title}\" filetype:mxl",
        f"\"{title}\" filetype:mscz",
        f"\"{title}\" filetype:mid",
        f"\"{title}\" filetype:midi",
        f"\"{title}\" filetype:pdf",
        f"\"{title}\" musicxml",
        f"\"{title}\" mxl",
        f"\"{title}\" mscz",
        f"\"{title}\" midi",
        f"\"{title}\" sheet music pdf",
        f"\"{title}\" noter pdf",
        f"\"{title}\" site:svensktvisarkiv.se pdf",
        f"\"{title}\" site:imslp.org pdf",
        f"\"{title}\" site:imslp.org mxl",
        f"\"{title}\" site:commons.wikimedia.org filetype:mid",
        f"\"{title}\" site:commons.wikimedia.org filetype:pdf",
        f"\"{title}\" site:archive.org pdf",
        f"\"{title}\" site:arkivkopia.se pdf",
        f"\"{title}\" site:runeberg.org pdf",
        f"\"{title}\" site:musopen.org sheet music",
        f"\"{title}\" site:openscore.cc musicxml",
        f"\"{title}\" site:mutopiaproject.org midi",
        f"\"{title}\" site:cpdl.org pdf",
        f"\"{title}\" site:hymnary.org musicxml",
        f"\"{title}\" site:mamalisa.com midi",
        f"\"{title}\" site:github.com musicxml",
        f"\"{title}\" site:github.com mxl",
        f"\"{title}\" site:github.com mscz",
        f"\"{title}\" site:github.com mid",
    ]
    gathered: list[str] = []
    for q in queries:
        gathered.extend(_search_duckduckgo_urls(q, max_results=10))
    gathered = _dedupe_preserve_order(gathered)
    direct = [u for u in gathered if _is_direct_score_url(u)]

    scored: list[tuple[int, str, str]] = []
    for u in direct:
        fmt = _guess_format_from_url(u)
        scored.append((_format_priority(fmt), fmt, u))
    scored.sort(key=lambda t: t[0])
    out: list[tuple[str, str]] = []
    for _p, fmt, u in scored:
        out.append((fmt, u))
        if len(out) >= max_candidates:
            break
    return out


def _strip_html_to_text(html: str) -> str:
    # Very lightweight cleanup: remove tags, keep some line breaks.
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\\1>", " ", html)
    text = re.sub(r"(?is)<br\\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\\s*>", "\n\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \\t\\r\\f\\v]+", " ", text)
    text = re.sub(r"\\n{3,}", "\n\n", text)
    return text.strip()


def _download_text(url: str, timeout_sec: float = 60.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; CodexCLI/1.0; +https://openai.com/)",
            "Accept": "text/html,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # nosec - expected for controlled URLs
        raw = resp.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="ignore")
    if "<html" in text.lower():
        return _strip_html_to_text(text)
    return text.strip()


def _resolve_audiveris() -> list[str] | None:
    candidates = [
        ["/opt/audiveris/bin/Audiveris"],
        ["audiveris"],
        ["Audiveris"],
    ]
    for cmd in candidates:
        try:
            subprocess.run([*cmd, "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return cmd
        except Exception:
            continue
    return None


def _audiveris_export_pdf_to_mxl(
    audiveris_cmd: list[str],
    pdf_path: Path,
    out_dir: Path,
    log_dir: Path,
    tmp_dir: Path,
    display: str,
) -> tuple[Path | None, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    import os

    env = os.environ.copy()
    env["JAVA_TOOL_OPTIONS"] = f"-Djava.io.tmpdir={tmp_dir}"
    env["TMPDIR"] = str(tmp_dir)
    env["DISPLAY"] = display

    log_path = log_dir / f"{pdf_path.stem}.audiveris.log"
    with log_path.open("wb") as logf:
        proc = subprocess.run(
            [*audiveris_cmd, "-batch", "-export", "-output", str(out_dir), str(pdf_path)],
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
        )
    if proc.returncode != 0:
        return None, log_path

    mxl_path = out_dir / f"{pdf_path.stem}.mxl"
    if mxl_path.exists():
        return mxl_path, log_path
    return None, log_path


def _musescore_export_midi_to_musicxml(midi_path: Path, out_path: Path) -> tuple[bool, str]:
    import os

    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("HOME", "/tmp/musescore-home")
    env.setdefault("XDG_CONFIG_HOME", "/tmp/musescore-home")

    try:
        proc = subprocess.run(
            ["musescore3", "--no-webview", "-o", str(out_path), str(midi_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "musescore3 not found on PATH"

    if proc.returncode != 0:
        return False, (proc.stdout or "").strip()
    if not out_path.exists():
        return False, "musescore3 exited 0 but output file was not created"
    return True, ""


def _musescore_export_musicxml_to_midi(xml_path: Path, out_path: Path) -> tuple[bool, str]:
    import os

    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("HOME", "/tmp/musescore-home")
    env.setdefault("XDG_CONFIG_HOME", "/tmp/musescore-home")

    try:
        proc = subprocess.run(
            ["musescore3", "--no-webview", "-o", str(out_path), str(xml_path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "musescore3 not found on PATH"

    if proc.returncode != 0:
        return False, (proc.stdout or "").strip()
    if not out_path.exists():
        return False, "musescore3 exited 0 but output file was not created"
    return True, ""


def _musescore_export_musicxml_to_pdf(xml_path: Path, out_path: Path) -> tuple[bool, str]:
    # MuseScore picks output format by filename extension.
    return _musescore_export_musicxml_to_midi(xml_path, out_path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_file", type=Path)
    ap.add_argument("--sheets-dir", type=Path, default=Path("assets/sheets"))
    ap.add_argument("--xml-dir", type=Path, default=Path("assets/xml"))
    ap.add_argument("--midi-dir", type=Path, default=Path("assets/midi"))
    ap.add_argument("--lyrics-dir", type=Path, default=Path("assets/lyrics"))
    ap.add_argument("--build-dir", type=Path, default=Path("assets/_build"))
    ap.add_argument("--report", type=Path, default=Path("assets/_build/reports/download_scores/DOWNLOAD_REPORT.md"))
    ap.add_argument(
        "--search-direct",
        action="store_true",
        help="Search the web for direct MusicXML/MXL/MSCZ/MIDI URLs for each song title (best-effort).",
    )
    ap.add_argument(
        "--no-pdf",
        action="store_true",
        help="When searching direct sources, skip downloading PDFs entirely (XML/MIDI only).",
    )
    ap.add_argument("--max-direct-candidates", type=int, default=5)
    ap.add_argument(
        "--no-convert",
        action="store_true",
        help="Do not attempt format conversions (MuseScore PDF/MIDI/MusicXML exports, Audiveris PDF→MXL).",
    )
    ap.add_argument(
        "--xml-only",
        action="store_true",
        help="Only count outputs as successful if we end up with MusicXML/MXL (direct or converted).",
    )
    ap.add_argument(
        "--convert-pdf-to-mxl",
        action="store_true",
        help="If we fall back to PDFs, also try Audiveris to export MXL into assets/_build/xml/ (ignored when --no-convert).",
    )
    ap.add_argument(
        "--no-lyrics",
        action="store_true",
        help="Do not attempt lyrics search/download.",
    )
    ap.add_argument("--display", type=str, default=":1", help="X11 DISPLAY for Audiveris (default ':1').")
    ap.add_argument(
        "--verify-downloads",
        action="store_true",
        help="Best-effort check that a downloaded file looks like the intended format and contains title tokens (warning-only).",
    )
    args = ap.parse_args()

    rows = _read_rows(args.csv_file)
    if not rows:
        raise SystemExit(f"No usable rows found in {args.csv_file}")

    report_lines: list[str] = []
    report_lines.append("# DOWNLOAD_REPORT\n")
    report_lines.append(f"CSV: `{args.csv_file}`\n")

    processed = 0
    found = 0
    skipped = 0
    converted = 0
    convert_failed = 0

    args.sheets_dir.mkdir(parents=True, exist_ok=True)
    args.xml_dir.mkdir(parents=True, exist_ok=True)
    args.midi_dir.mkdir(parents=True, exist_ok=True)
    args.lyrics_dir.mkdir(parents=True, exist_ok=True)

    build_xml_dir = args.build_dir / "xml"
    build_midi_dir = args.build_dir / "midi"
    build_sheets_dir = args.build_dir / "sheets"
    build_xml_logs_dir = build_xml_dir / "logs"
    build_tmp_audiveris_dir = args.build_dir / "tmp" / "audiveris"
    build_xml_dir.mkdir(parents=True, exist_ok=True)
    build_midi_dir.mkdir(parents=True, exist_ok=True)
    build_sheets_dir.mkdir(parents=True, exist_ok=True)

    audiveris_cmd = None
    if args.convert_pdf_to_mxl and not args.no_convert:
        audiveris_cmd = _resolve_audiveris()
        if audiveris_cmd is None:
            report_lines.append("WARNING: `--convert-pdf-to-mxl` requested but no Audiveris executable was found.\n")

    # Group rows by song number so multiple sources per song can be listed in the CSV.
    by_song: dict[str, list[Row]] = {}
    for row in rows:
        by_song.setdefault(row.number, []).append(row)

    for number, song_rows in sorted(by_song.items(), key=lambda kv: kv[0]):
        processed += 1
        title = song_rows[0].title
        status = song_rows[0].status
        composer_or_origin = song_rows[0].composer_or_origin
        report_lines.append(f"## Song #{number}: {title}\n")

        if status.upper().startswith("SKYDDAD"):
            skipped += 1
            report_lines.append("Status: SKIPPED (SKYDDAD)\n")
            continue

        candidates: list[tuple[str, str, str]] = []  # (fmt, url, source)
        if args.search_direct:
            for fmt, url in _candidate_urls_for_song(title, max(1, int(args.max_direct_candidates))):
                if args.no_pdf and fmt.upper() == "PDF":
                    continue
                candidates.append((fmt, url, "duckduckgo"))

        # CSV-provided candidates (fallback). Sort XML/MIDI ahead of PDF if present.
        for r in sorted(song_rows, key=lambda rr: _format_priority(rr.fmt)):
            if args.no_pdf and r.fmt.upper() == "PDF":
                continue
            candidates.append((r.fmt.strip().upper(), r.url, r.source))

        # Deduplicate by URL.
        seen: set[str] = set()
        deduped: list[tuple[str, str, str]] = []
        for fmt, url, src in candidates:
            if url in seen:
                continue
            seen.add(url)
            deduped.append((fmt, url, src))

        if not deduped:
            report_lines.append("Status: NOT FOUND\n")
            report_lines.append("Search notes:\n")
            report_lines.append("- No eligible candidates.\n")
            continue

        deduped.sort(key=lambda t: _format_priority(t[0]))
        report_lines.append("Tried candidates (in priority order):\n")
        for fmt, url, src in deduped:
            report_lines.append(f"- {fmt} | {src} | {url}\n")

        report_lines.append("\nGoal per song: PDF sheet + MusicXML/MXL + MIDI + lyrics.\n")
        report_lines.append("Priority: obtain MusicXML or MIDI first; then export the rest from it.\n")

        song_slug = _slug(title)
        canonical_musicxml = build_xml_dir / "swedish_children" / f"{number}_{song_slug}.musicxml"
        canonical_midi = build_midi_dir / f"{number}_{song_slug}.mid"
        canonical_pdf = build_sheets_dir / f"{number}_{song_slug}.pdf"
        canonical_lyrics = args.lyrics_dir / f"{number}_{song_slug}.txt"
        (build_xml_dir / "swedish_children").mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        have_xml_or_midi = False

        report_lines.append("\nStep 1: Download XML/MIDI (preferred)\n")
        primary_kind = ""
        primary_path: Path | None = None
        for fmt, url, src in [t for t in deduped if t[0].upper() in {"MUSICXML", "XML", "MXL", "MSCZ", "MIDI", "MID"}]:
            ext_guess = {
                "MIDI": "mid",
                "MID": "mid",
                "MXL": "mxl",
                "MSCZ": "mscz",
                "MUSICXML": "musicxml",
                "XML": "musicxml",
            }.get(fmt.upper(), "bin")
            base = f"{number}_{song_slug}_{_slug(src)}"
            out_dir = args.midi_dir if fmt.upper() in {"MIDI", "MID"} else args.xml_dir
            out_path = out_dir / f"{base}.{ext_guess}"
            try:
                _download(url, out_path)
                found += 1
                primary_kind = fmt.upper()
                primary_path = out_path
                have_xml_or_midi = True
                report_lines.append(f"- Downloaded `{out_path}` | Source: {url} | Format: {fmt}\n")
                if args.verify_downloads:
                    for w in _verify_downloaded_file(out_path, title):
                        warnings.append(f"{out_path.name}: {w}")
                break
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                report_lines.append(f"- FAILED {fmt} {url}: {type(e).__name__}: {e}\n")

        report_lines.append("\nStep 2: Export remaining formats from primary (best-effort)\n")
        xml_for_exports: Path | None = None
        if primary_path is not None and not args.no_convert:
            if primary_kind in {"MIDI", "MID"}:
                ok, msg = _musescore_export_midi_to_musicxml(primary_path, canonical_musicxml)
                if ok:
                    have_xml_or_midi = True
                    xml_for_exports = canonical_musicxml
                    report_lines.append(f"- Derived `{canonical_musicxml}` | Engine: musescore3 | Input: `{primary_path}`\n")
                else:
                    warnings.append(f"MIDI→MusicXML failed: {msg}")
                    report_lines.append(f"- MIDI→MusicXML FAILED: {msg}\n")
            else:
                # Use downloaded MusicXML-ish directly for exports.
                xml_for_exports = primary_path
                ok, msg = _musescore_export_musicxml_to_midi(xml_for_exports, canonical_midi)
                if ok:
                    report_lines.append(f"- Derived `{canonical_midi}` | Engine: musescore3 | Input: `{xml_for_exports}`\n")
                else:
                    warnings.append(f"MusicXML→MIDI failed: {msg}")
                    report_lines.append(f"- MusicXML→MIDI FAILED: {msg}\n")

            if xml_for_exports is not None:
                ok, msg = _musescore_export_musicxml_to_pdf(xml_for_exports, canonical_pdf)
                if ok:
                    report_lines.append(f"- Derived `{canonical_pdf}` | Engine: musescore3 | Input: `{xml_for_exports}`\n")
                else:
                    warnings.append(f"MusicXML→PDF failed: {msg}")
                    report_lines.append(f"- MusicXML→PDF FAILED: {msg}\n")
        elif primary_path is not None and args.no_convert:
            warnings.append("Conversions skipped due to `--no-convert`; cannot export missing formats.")

        report_lines.append("\nStep 3: If primary conversion failed, try downloading missing formats separately\n")
        if not have_xml_or_midi:
            report_lines.append("- No XML/MIDI downloaded.\n")
        else:
            have_musicxml = primary_kind in {"MUSICXML", "XML", "MXL"} or canonical_musicxml.exists() or (xml_for_exports is not None)
            have_midi = primary_kind in {"MIDI", "MID"} or canonical_midi.exists()
            have_pdf = canonical_pdf.exists()

            if not have_musicxml:
                report_lines.append("- Missing MusicXML/MXL after conversion; trying separate download.\n")
                for fmt, url, src in [t for t in deduped if t[0].upper() in {"MUSICXML", "XML", "MXL", "MSCZ"}]:
                    ext_guess = {
                        "MXL": "mxl",
                        "MSCZ": "mscz",
                        "MUSICXML": "musicxml",
                        "XML": "musicxml",
                    }.get(fmt.upper(), "bin")
                    base = f"{number}_{song_slug}_{_slug(src)}"
                    out_path = args.xml_dir / f"{base}.{ext_guess}"
                    try:
                        _download(url, out_path)
                        found += 1
                        have_musicxml = True
                        xml_for_exports = out_path
                        report_lines.append(f"- Downloaded `{out_path}` | Source: {url} | Format: {fmt}\n")
                        if args.verify_downloads:
                            for w in _verify_downloaded_file(out_path, title):
                                warnings.append(f"{out_path.name}: {w}")
                        break
                    except (urllib.error.URLError, TimeoutError, ValueError) as e:
                        report_lines.append(f"- FAILED {fmt} {url}: {type(e).__name__}: {e}\n")

            if have_musicxml and xml_for_exports is not None and not args.no_convert:
                if not have_midi:
                    ok, msg = _musescore_export_musicxml_to_midi(xml_for_exports, canonical_midi)
                    if ok:
                        have_midi = True
                        report_lines.append(f"- Derived `{canonical_midi}` | Engine: musescore3 | Input: `{xml_for_exports}`\n")
                    else:
                        warnings.append(f"MusicXML→MIDI failed (after separate XML download): {msg}")
                        report_lines.append(f"- MusicXML→MIDI FAILED: {msg}\n")
                if not have_pdf:
                    ok, msg = _musescore_export_musicxml_to_pdf(xml_for_exports, canonical_pdf)
                    if ok:
                        have_pdf = True
                        report_lines.append(f"- Derived `{canonical_pdf}` | Engine: musescore3 | Input: `{xml_for_exports}`\n")
                    else:
                        warnings.append(f"MusicXML→PDF failed (after separate XML download): {msg}")
                        report_lines.append(f"- MusicXML→PDF FAILED: {msg}\n")

            if not have_midi:
                report_lines.append("- Missing MIDI after conversion; trying separate download.\n")
                for fmt, url, src in [t for t in deduped if t[0].upper() in {"MIDI", "MID"}]:
                    base = f"{number}_{song_slug}_{_slug(src)}"
                    out_path = args.midi_dir / f"{base}.mid"
                    try:
                        _download(url, out_path)
                        found += 1
                        have_midi = True
                        report_lines.append(f"- Downloaded `{out_path}` | Source: {url} | Format: {fmt}\n")
                        if args.verify_downloads:
                            for w in _verify_downloaded_file(out_path, title):
                                warnings.append(f"{out_path.name}: {w}")
                        break
                    except (urllib.error.URLError, TimeoutError, ValueError) as e:
                        report_lines.append(f"- FAILED {fmt} {url}: {type(e).__name__}: {e}\n")

            if not have_pdf:
                report_lines.append("- Missing PDF sheet after conversion; trying separate download.\n")
                for fmt, url, src in [t for t in deduped if t[0].upper() == "PDF"]:
                    base = f"{number}_{song_slug}_{_slug(src)}"
                    out_path = args.sheets_dir / f"{base}.pdf"
                    try:
                        _download(url, out_path)
                        found += 1
                        have_pdf = True
                        report_lines.append(f"- Downloaded `{out_path}` | Source: {url} | Format: PDF\n")
                        if args.verify_downloads:
                            for w in _verify_downloaded_file(out_path, title):
                                warnings.append(f"{out_path.name}: {w}")
                        break
                    except (urllib.error.URLError, TimeoutError, ValueError) as e:
                        report_lines.append(f"- FAILED PDF {url}: {type(e).__name__}: {e}\n")

        # If no XML/MIDI found, fall back to PDF downloads (and optionally Audiveris).
        if not have_xml_or_midi:
            report_lines.append("\nFallback: Download PDF sheets\n")
            pdf_downloaded = False
            for fmt, url, src in [t for t in deduped if t[0].upper() == "PDF"]:
                base = f"{number}_{song_slug}_{_slug(src)}"
                out_path = args.sheets_dir / f"{base}.pdf"
                try:
                    _download(url, out_path)
                    found += 1
                    pdf_downloaded = True
                    report_lines.append(f"- Downloaded `{out_path}` | Source: {url} | Format: PDF\n")
                    if args.verify_downloads:
                        for w in _verify_downloaded_file(out_path, title):
                            warnings.append(f"{out_path.name}: {w}")
                    if args.convert_pdf_to_mxl and audiveris_cmd is not None and not args.no_convert:
                        mxl_path, log_path = _audiveris_export_pdf_to_mxl(
                            audiveris_cmd=audiveris_cmd,
                            pdf_path=out_path,
                            out_dir=build_xml_dir,
                            log_dir=build_xml_logs_dir,
                            tmp_dir=build_tmp_audiveris_dir,
                            display=args.display,
                        )
                        if mxl_path is not None:
                            converted += 1
                            report_lines.append(f"- Derived `{mxl_path}` | Engine: Audiveris | Input: `{out_path}`\n")
                        else:
                            convert_failed += 1
                            warnings.append(f"PDF→MXL failed; see log {log_path}")
                            report_lines.append(f"- MusicXML export FAILED | Log: `{log_path}`\n")
                    break
                except (urllib.error.URLError, TimeoutError, ValueError) as e:
                    report_lines.append(f"- FAILED PDF {url}: {type(e).__name__}: {e}\n")
            if not pdf_downloaded:
                warnings.append("No MIDI/XML found and no PDF downloaded; moving on to next song.")

        report_lines.append("\nStep 4: Lyrics\n")
        if not args.no_lyrics:
            queries = [
                f"\"{title}\" sångtext",
                f"\"{title}\" text",
                f"\"{title}\" lyrics",
                f"\"{title}\" {composer_or_origin} sångtext" if composer_or_origin else "",
            ]
            queries = [q for q in queries if q]
            lyric_urls: list[str] = []
            for q in queries:
                lyric_urls.extend(_search_duckduckgo_urls(q, max_results=5))
            lyric_urls = _dedupe_preserve_order([u for u in lyric_urls if u.startswith(("http://", "https://"))])
            if not lyric_urls:
                warnings.append("No lyric URLs found via search.")
                report_lines.append("- No lyric URLs found via search.\n")
            else:
                lyric_url = lyric_urls[0]
                try:
                    text = _download_text(lyric_url)
                    if not text:
                        raise ValueError("empty lyric text after extraction")
                    canonical_lyrics.write_text(text + "\n", encoding="utf-8")
                    found += 1
                    report_lines.append(f"- Downloaded `{canonical_lyrics}` | Source: {lyric_url}\n")
                except Exception as e:
                    warnings.append(f"Lyrics download failed: {type(e).__name__}: {e}")
                    report_lines.append(f"- Lyrics FAILED {lyric_url}: {type(e).__name__}: {e}\n")
        else:
            report_lines.append("- Skipped (`--no-lyrics`).\n")

        if warnings:
            report_lines.append("\nWarnings:\n")
            for w in warnings:
                report_lines.append(f"- {w}\n")

        # Status semantics:
        # - With --xml-only, we require a usable MusicXML/MXL (downloaded or derived).
        have_xml = (
            primary_kind in {"MUSICXML", "XML", "MXL"}
            or canonical_musicxml.exists()
            or any((build_xml_dir / "swedish_children").glob(f"{number}_{song_slug}.*"))
            or any(args.xml_dir.glob(f"{number}_{song_slug}_*.*"))
        )
        if args.xml_only:
            report_lines.append("\nStatus: FOUND\n" if have_xml else "\nStatus: NOT FOUND\n")
        else:
            report_lines.append("\nStatus: FOUND\n" if (primary_path is not None) else "\nStatus: NOT FOUND\n")

    report_lines.append("\n---\n")
    report_lines.append(f"Total songs processed: {processed}\n")
    report_lines.append(f"Total successful downloads/outputs: {found}\n")
    report_lines.append(f"Songs skipped (SKYDDAD): {skipped}\n")
    if args.convert_pdf_to_mxl and not args.no_convert:
        report_lines.append(f"PDF→MXL exported: {converted}\n")
        report_lines.append(f"PDF→MXL failed: {convert_failed}\n")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(report_lines).rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
