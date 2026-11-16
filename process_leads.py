#!/usr/bin/env python3
"""
Filter hasil gosom/google-maps-scraper jadi daftar leads:
- buang yang sudah punya website beneran
- nomor dinormalisasi ke format +62xxxxxxxxxx (auto jadi blue text di WhatsApp)
- pisahkan nomor HP (kemungkinan besar ada WA) dari telepon rumah/kantor
- buang nomor yang sudah ada di contacted.txt (opsional, satu nomor per baris)
- urut: tanpa web dulu, lalu yang ulasannya paling banyak (biasanya bisnis paling aktif)

Pakai:  python3 process_leads.py results.csv [--strict] [--min-rating 4.5] [--max-days 180] [--no-niche-filter]
  --strict          : buang juga yang cuma punya IG/FB/Linktree (hanya yang website-nya kosong)
  --min-rating X    : buang yang ratingnya di bawah X (default 0 = tidak ada batas)
  --max-days N      : buang yang ulasan terakhirnya lebih lama dari N hari (butuh data ulasan,
                      lihat input extra_reviews di workflow). Default 0 = tidak difilter.
  --no-niche-filter : jangan buang hasil yang tidak nyambung dengan sedot WC
"""
import argparse
import csv
import json
import os
import time
import re
import sys
from urllib.parse import urlparse

# Domain yang bukan website beneran (sosmed / link-in-bio / chat / halaman bawaan Google)
NON_WEBSITE = (
    "instagram.com", "facebook.com", "fb.com", "fb.me", "tiktok.com",
    "twitter.com", "x.com", "youtube.com", "t.me", "wa.me", "wa.link",
    "whatsapp.com", "linktr.ee", "linkin.bio", "beacons.ai", "bit.ly",
    "business.site", "g.page", "google.com", "goo.gl",
)

# Hasil harus nyambung dengan niche sedot WC (cek nama + kategori)
NICHE_RE = re.compile(
    r"sedot|septic|septik|tinja|\bwc\b|toilet|kuras|limbah|saluran|ipal|tangki|"
    r"pembersih(an)?|kebersihan|drainase|mampet", re.I)

FIELDS = ["nama", "nomor", "web_status", "website", "kategori",
          "alamat", "rating", "ulasan", "ulasan_terakhir_hari", "maps_link"]


def last_review_days(raw):
    """Umur ulasan terbaru (hari) dari kolom user_reviews; None kalau tidak ada data."""
    if not raw:
        return None
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return None
    stamps = [(i.get("posted_at_unix_micros") or 0) for i in (items or []) if isinstance(i, dict)]
    stamps = [t for t in stamps if t]
    if not stamps:
        return None
    return int((time.time() - max(stamps) / 1e6) / 86400)


def host_of(url):
    if "://" not in url:
        url = "http://" + url
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def web_status(url):
    url = (url or "").strip()
    if not url:
        return "tanpa_web"
    h = host_of(url)
    if any(h == d or h.endswith("." + d) for d in NON_WEBSITE):
        return "cuma_sosmed"
    return "punya_web"


def normalize_phone(raw):
    """Return (+62xxxxxxxx, 'mobile'|'landline') atau (None, None)."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None, None
    if digits.startswith("62"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if not digits:
        return None, None
    # HP Indonesia: 08xx -> nasional 8xx, total 9-12 digit setelah 0
    if digits.startswith("8") and 9 <= len(digits) <= 12:
        return "+62" + digits, "mobile"
    return "+62" + digits, "landline"


def to_int(v):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (ValueError, TypeError):
        return 0


def load_contacted(path="contacted.txt"):
    done = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                num, _ = normalize_phone(line)
                if num:
                    done.add(num)
    return done


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--min-rating", type=float, default=0.0)
    ap.add_argument("--max-days", type=int, default=0)
    ap.add_argument("--no-niche-filter", action="store_true")
    args = ap.parse_args()

    contacted = load_contacted()
    stats = {"total": 0, "punya_web": 0, "tutup": 0, "tanpa_nomor": 0,
             "sudah_dihubungi": 0, "duplikat": 0, "bukan_niche": 0,
             "rating_rendah": 0, "tidak_aktif": 0}
    mobile, landline = [], []

    with open(args.input, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            stats["total"] += 1
            status_text = (r.get("status") or "").lower()
            if "permanent" in status_text or "permanen" in status_text:
                stats["tutup"] += 1
                continue

            if not args.no_niche_filter and not NICHE_RE.search(
                    (r.get("title") or "") + " " + (r.get("category") or "")):
                stats["bukan_niche"] += 1
                continue

            rating_val = float(r.get("review_rating") or 0)
            if rating_val < args.min_rating:
                stats["rating_rendah"] += 1
                continue

            days = last_review_days(r.get("user_reviews"))
            if args.max_days and (days is None or days > args.max_days):
                stats["tidak_aktif"] += 1
                continue

            ws = web_status(r.get("website"))
            if ws == "punya_web" or (args.strict and ws == "cuma_sosmed"):
                stats["punya_web"] += 1
                continue

            num, kind = normalize_phone(r.get("phone"))
            if not num:
                stats["tanpa_nomor"] += 1
                continue
            if num in contacted:
                stats["sudah_dihubungi"] += 1
                continue

            row = {
                "nama": (r.get("title") or "").strip(),
                "nomor": num,
                "web_status": ws,
                "website": (r.get("website") or "").strip(),
                "kategori": (r.get("category") or "").strip(),
                "alamat": (r.get("address") or "").strip(),
                "rating": r.get("review_rating") or "",
                "ulasan": to_int(r.get("review_count")),
                "ulasan_terakhir_hari": "" if days is None else days,
                "maps_link": r.get("link") or "",
            }
            (mobile if kind == "mobile" else landline).append(row)

    def sort_key(x):
        d = x["ulasan_terakhir_hari"]
        # tanpa web dulu, lalu yang ulasan terakhirnya paling baru, lalu ulasan terbanyak
        return (0 if x["web_status"] == "tanpa_web" else 1,
                d if d != "" else 99999, -x["ulasan"])

    def dedupe(rows):
        seen, out = set(), []
        for x in sorted(rows, key=sort_key):
            if x["nomor"] in seen:
                stats["duplikat"] += 1
                continue
            seen.add(x["nomor"])
            out.append(x)
        return out

    mobile, landline = dedupe(mobile), dedupe(landline)
    write_csv("leads.csv", mobile)
    write_csv("leads_landline.csv", landline)

    n_noweb = sum(1 for x in mobile if x["web_status"] == "tanpa_web")
    print(f"Total hasil scrape      : {stats['total']}")
    print(f"Dibuang (sudah punya web): {stats['punya_web']}")
    print(f"Dibuang (tutup permanen) : {stats['tutup']}")
    print(f"Dibuang (bukan niche)    : {stats['bukan_niche']}")
    print(f"Dibuang (rating rendah)  : {stats['rating_rendah']}")
    print(f"Dibuang (tidak aktif)    : {stats['tidak_aktif']}")
    print(f"Dibuang (tanpa nomor)    : {stats['tanpa_nomor']}")
    print(f"Dibuang (sudah dihubungi): {stats['sudah_dihubungi']}")
    print(f"Dibuang (duplikat)       : {stats['duplikat']}")
    print(f"=> leads.csv (nomor HP)  : {len(mobile)}  ({n_noweb} tanpa web, {len(mobile) - n_noweb} cuma sosmed)")
    print(f"=> leads_landline.csv    : {len(landline)}")

    # Tabel ringkas di halaman Summary GitHub Actions (gampang di-copy dari HP)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as s:
            s.write(f"### Leads siap outreach: {len(mobile)} nomor HP "
                    f"({n_noweb} tanpa web)\n\n")
            s.write("| Nama | Nomor | Web | Rating | Ulasan | Terakhir (hari) |\n|---|---|---|---|---|---|\n")
            for x in mobile[:100]:
                nama = x["nama"].replace("|", "/")
                s.write(f"| {nama} | `{x['nomor']}` | {x['web_status']} | {x['rating']} | "
                        f"{x['ulasan']} | {x['ulasan_terakhir_hari']} |\n")
            if len(mobile) > 100:
                s.write(f"\n_...dan {len(mobile) - 100} lainnya di leads.csv (Artifacts)_\n")


if __name__ == "__main__":
    sys.exit(main())
