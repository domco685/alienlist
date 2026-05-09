#!/usr/bin/env python3
"""
Generate LLM summaries for every PDF in assets/pdf/ → writes summaries.json.

Each catalog card on index.html auto-upgrades when summaries.json is present
to show: TL;DR, verbatim pull quotes, key facts, and the source transcript
(toggleable tabs), in addition to the original "Open full PDF" button.

Pipeline per record:
  1. pdftotext (fast, born-digital PDFs)
  2. tesseract OCR fallback for scanned PDFs (most FBI files)
  3. Anthropic Claude API → JSON with tldr / quotes / key_facts
  4. Append to summaries.json (resumable — re-runs skip already-summarized records)

Estimated cost: ~$0.05–0.20 per record × 129 records = ~$10–25 total at
Claude Sonnet 4.6 prices. Most cost is OCR text input. Run time depends
on tesseract OCR speed (1–10 minutes per scanned PDF). Total wall time
typically 30–90 minutes; the script saves progress incrementally so
you can ctrl+C and resume.

Setup
=====
  brew install poppler tesseract                 # text extraction + OCR
  pip install anthropic pdfplumber               # SDK + structured PDF extraction
  export ANTHROPIC_API_KEY=sk-ant-...

Run
===
  python3 summarize.py                           # full pass
  python3 summarize.py --only 1,2,3              # specific record IDs
  python3 summarize.py --limit 10                # first N
  python3 summarize.py --skip-ocr                # skip records that need OCR
  python3 summarize.py --model claude-sonnet-4-6 # override model

After it finishes, redeploy the site — the cards on index.html auto-detect
summaries.json and upgrade the UI in place.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS_PDF = ROOT / "assets" / "pdf"
CATALOG_PATH = ROOT / "catalog.json"
SUMMARIES_PATH = ROOT / "summaries.json"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"  # cheapest Claude tier; plenty for summarization
MAX_INPUT_CHARS = 60_000  # ~15k tokens; well under Sonnet's window
TRANSCRIPT_STORE_CHARS = 50_000  # truncate transcript saved to JSON

PROMPT = """You're summarizing a U.S. government UAP / UFO document for a public catalog. Strip ceremony — no preamble, no apologies, just the JSON.

Document title: {title}
Agency: {agency}
Incident date: {incident_date}
Incident location: {location}

Extracted text (may contain OCR artifacts):
\"\"\"
{text}
\"\"\"

Return a single JSON object with these keys:

- "tldr": one paragraph, 3–6 sentences, plain English. Lead with what the document IS (memo, mission report, witness account…) and what it documents. If a witness sighting is described, include: date/time, location, what was reported, observer's role, and what the agency concluded (or that it remained unresolved). Skip filler. No hedging language unless the source itself hedges.

- "quotes": array of 2–4 short verbatim excerpts (≤200 chars each) pulled directly from the text. Pick the most concrete sensor descriptions, witness statements, or technical details. Use the exact wording from the source — these are quotes, not paraphrases. If the source is heavily redacted, lean on the unredacted fragments.

- "key_facts": array of 3–6 atomic facts the document establishes (specific dates, names, units, sensor types, distances, durations, locations). Each entry one short line.

If the text is too short, garbled, or contains nothing summarizable (e.g., empty page after OCR), return: {{"tldr": "Document text could not be extracted reliably — open the PDF.", "quotes": [], "key_facts": []}}

Return ONLY the JSON object, no markdown fences, no commentary."""


def have(cmd: str) -> bool:
    return subprocess.run(["which", cmd], capture_output=True).returncode == 0


def extract_text_pdftotext(pdf: Path) -> str:
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", "-q", str(pdf), "-"],
            capture_output=True, text=True, timeout=120,
        )
        return r.stdout.strip()
    except Exception:
        return ""


OCR_DPI = 150          # 200 was overkill; 150 reads cleanly and renders 2× faster
OCR_FIRST_PAGES = 25   # cap pages rasterized — 25 pages ~= 75k chars OCR'd, plenty
                       # for MAX_INPUT_CHARS while staying under timeouts on 500p FBI files

def extract_text_ocr(pdf: Path) -> str:
    """OCR via tesseract (slow, used only when pdftotext yields too little).

    Renders ONLY the first N pages — long FBI sections (500+ pages) would
    otherwise time out. The Claude prompt has a 60k char input cap anyway,
    so reading ~25 pages is enough to summarize meaningfully.
    """
    if not have("tesseract"):
        return ""
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            r = subprocess.run(
                [
                    "pdftoppm",
                    "-r", str(OCR_DPI),
                    "-gray", "-png",
                    "-f", "1", "-l", str(OCR_FIRST_PAGES),
                    str(pdf), str(tdir / "p")
                ],
                capture_output=True, timeout=900,
            )
            if r.returncode != 0:
                return ""
            images = sorted(tdir.glob("p-*.png")) + sorted(tdir.glob("p-*.pgm")) + sorted(tdir.glob("p-*.ppm"))
            if not images:
                return ""
            print(f"      OCR: {len(images)} pages @ {OCR_DPI} DPI", flush=True)
            text_parts = []
            for img in images:
                t = subprocess.run(
                    ["tesseract", str(img), "-", "-l", "eng", "--psm", "6"],
                    capture_output=True, text=True, timeout=120,
                )
                text_parts.append(t.stdout)
                if sum(len(p) for p in text_parts) > MAX_INPUT_CHARS:
                    break
            return "\n".join(text_parts).strip()
    except Exception as e:
        print(f"      OCR error: {e}", file=sys.stderr)
        return ""


def extract_text(pdf: Path, allow_ocr: bool = True) -> tuple[str, str]:
    """Return (text, method) — method is 'pdftotext' or 'ocr' or 'none'."""
    text = extract_text_pdftotext(pdf)
    if len(text) >= 500:
        return text, "pdftotext"
    if allow_ocr:
        text = extract_text_ocr(pdf)
        if text:
            return text, "ocr"
    return "", "none"


def call_claude(text: str, record: dict, model: str) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    prompt = PROMPT.format(
        title=record["title"],
        agency=record.get("agency", "Unknown"),
        incident_date=record.get("incidentDate") or "N/A",
        location=record.get("incidentLocation") or "N/A",
        text=text[:MAX_INPUT_CHARS],
    )
    msg = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # Trim any accidental markdown fences
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="Process at most N new records")
    ap.add_argument("--only", default="", help="Comma-separated record ids (e.g. '1,5,42')")
    ap.add_argument("--skip-ocr", action="store_true", help="Skip records that need OCR (fast pass for born-digital PDFs only)")
    ap.add_argument("--force", action="store_true", help="Re-summarize even records already in summaries.json")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        print("Get a key at https://console.anthropic.com/ and:", file=sys.stderr)
        print("    export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
        sys.exit(1)

    if not have("pdftotext"):
        print("ERROR: pdftotext not found. Install with: brew install poppler", file=sys.stderr)
        sys.exit(1)

    catalog = json.loads(CATALOG_PATH.read_text())
    summaries = {}
    if SUMMARIES_PATH.exists():
        summaries = json.loads(SUMMARIES_PATH.read_text())
        print(f"Loaded {len(summaries)} existing summaries — resuming")

    only_ids = set(args.only.split(",")) if args.only else None
    processed = 0
    started = time.time()

    for rec in catalog:
        rid = str(rec["id"])
        if only_ids and rid not in only_ids: continue
        if rid in summaries and not args.force: continue
        if not rec.get("localFile"): continue
        pdf = ROOT / rec["localFile"]
        if not pdf.exists() or pdf.suffix.lower() != ".pdf":
            continue

        title = rec["title"][:60]
        print(f"[{rid:>3}] {title}", flush=True)

        text, method = extract_text(pdf, allow_ocr=not args.skip_ocr)
        if not text:
            print(f"      skip — no extractable text", flush=True)
            continue
        if args.skip_ocr and method == "ocr":
            print(f"      skip — needs OCR", flush=True)
            continue
        print(f"      extracted {len(text):,} chars via {method}", flush=True)

        try:
            data = call_claude(text, rec, args.model)
        except Exception as e:
            print(f"      Claude error: {e}", flush=True)
            time.sleep(3)
            continue

        # Truncate transcript before storage
        data["transcript"] = text[:TRANSCRIPT_STORE_CHARS]
        data["extraction_method"] = method
        summaries[rid] = data
        SUMMARIES_PATH.write_text(json.dumps(summaries, indent=2, ensure_ascii=False))
        processed += 1
        elapsed = time.time() - started
        print(f"      ✓ saved ({processed} done, {elapsed:.0f}s)", flush=True)

        if args.limit and processed >= args.limit:
            print(f"\nReached --limit {args.limit}")
            break

        # Gentle pacing for the API
        time.sleep(0.3)

    print(f"\nDone. {len(summaries)}/{len(catalog)} records summarized.")
    print(f"Output: {SUMMARIES_PATH}")
    print(f"Reload index.html — cards will auto-upgrade.")


if __name__ == "__main__":
    main()
