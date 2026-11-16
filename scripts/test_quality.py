"""Test sifati hisoboti: JSON yoki mustaqil HTML dashboard.

Misol::

    python scripts/test_quality.py --test-code m3rash25 --html quality.html
    python scripts/test_quality.py --exam-id 12 --json quality.json

Hisobot: Cronbach α, EAP ishonchlilik, item p/r_pbi/infit/outfit,
SRMSR/RMSEA/CFI/TLI (limited-information), Wright xaritasi, TIF.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from database.db import Database  # noqa: E402
from database.repository import Repositories  # noqa: E402
from services import test_quality  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test sifati hisoboti")
    parser.add_argument("--test-code", default="", help="Imtihon test kodi")
    parser.add_argument("--exam-id", type=int, default=0, help="Imtihon ID")
    parser.add_argument(
        "--source",
        choices=("online", "offline", "combined"),
        default="combined",
        help="Manba: online / offline / combined (default)",
    )
    parser.add_argument("--json", default="", help="JSON fayl yo'li")
    parser.add_argument("--html", default="", help="HTML dashboard yo'li")
    return parser


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return html.escape(str(value))


def _cards(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    cards = [
        ("Ishtirokchilar", summary.get("participants"), "N"),
        ("Itemlar", summary.get("items"), "K"),
        ("Cronbach α", _fmt(summary.get("cronbach_alpha"), 3), "≥ 0.80 yaxshi"),
        ("EAP ishonchlilik", _fmt(summary.get("eap_reliability"), 3), "≥ 0.80 yaxshi"),
        ("O'rtacha ball", _fmt(summary.get("mean_raw"), 2), "xom ball"),
        ("SD (xom)", _fmt(summary.get("sd_raw"), 2), ""),
        ("Min / Max", f"{summary.get('min_raw', '—')} / {summary.get('max_raw', '—')}", ""),
        ("SRMSR", _fmt(summary.get("srmr"), 3), "past — yaxshi"),
        ("RMSEA", _fmt(summary.get("rmsea"), 3), "< 0.05 yaxshi"),
        ("CFI / TLI", f"{_fmt(summary.get('cfi'), 3)} / {_fmt(summary.get('tli'), 3)}", "≥ 0.95 yaxshi"),
        ("M2 (df, p)", f"{_fmt(summary.get('m2'), 1)} ({summary.get('df', '—')}, p={_fmt(summary.get('m2_p'), 3)})", "approx"),
        ("O'rtacha r_pbi", _fmt(summary.get("mean_r_pbi"), 3), ""),
    ]
    return "".join(
        f'<div class="card"><div class="k">{html.escape(title)}</div>'
        f'<div class="v">{value}</div>'
        f'<div class="h">{html.escape(note)}</div></div>'
        for title, value, note in cards
    )


def _items_table(report: dict[str, Any]) -> str:
    rows = []
    for item in report.get("items") or []:
        p = item.get("p")
        tone = "good" if p is not None and p >= 0.70 else ("mid" if p is not None and p >= 0.40 else "bad")
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('label')))}</td>"
            f"<td>{_fmt(item.get('b'), 3)}</td>"
            f'<td class="{tone}">{_fmt(p, 3)}</td>'
            f"<td>{_fmt(item.get('r_pbi'), 3)}</td>"
            f"<td>{_fmt(item.get('infit'), 3)}</td>"
            f"<td>{_fmt(item.get('outfit'), 3)}</td>"
            "</tr>"
        )
def _wright_html(report: dict[str, Any]) -> str:
    data = report.get("wright") or {}
    centers = data.get("bins") or []
    persons = data.get("person_counts") or []
    items = data.get("item_counts") or []
    max_person = max(persons) if persons else 1
    max_item = max(items) if items else 1
    rows = []
    for center, person, item in zip(centers, persons, items, strict=True):
        person_h = 100.0 * person / max_person if max_person else 0.0
        item_h = 100.0 * item / max_item if max_item else 0.0
        rows.append(
            '<div class="wrow">'
            f'<span class="wl">{float(center):+.2f}</span>'
            '<div class="wbar">'
            f'<span class="pbar" style="height:{person_h:.1f}%"></span>'
            f'<span class="ibar" style="height:{item_h:.1f}%"></span>'
            "</div>"
            f'<span class="wc">{person} / {item}</span>'
            "</div>"
        )
    return (
        '<div class="legend"><span class="dot p"></span>Ishtirokchilar '
        '<span class="dot i"></span>Savollar</div>'
        '<div class="wright">' + "".join(rows) + "</div>"
    )


def _tif_svg(report: dict[str, Any]) -> str:
    data = report.get("tif") or {}
    thetas = [float(value) for value in data.get("theta") or []]
    info = [float(value) for value in data.get("information") or []]
    if not thetas or not info:
        return "<p class='muted'>TIF ma'lumoti yo'q.</p>"
    low, high = min(thetas), max(thetas)
    max_info = max(info) or 1.0
    width, height = 900, 240
    left, right, top, bottom = 50, 20, 20, 35
    plot_w = width - left - right
    plot_h = height - top - bottom
    points = []
    for theta, value in zip(thetas, info, strict=True):
        x = left + (theta - low) / (high - low) * plot_w
        y = top + plot_h - (value / max_info) * plot_h
        points.append(f"{x:.1f},{y:.1f}")
    axis = (
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" '
        f'y2="{top + plot_h}" stroke="#94a3b8"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" '
        f'stroke="#94a3b8"/>'
        f'<text x="{left}" y="{height - 8}" font-size="11" fill="#64748b">{low:+.1f}</text>'
        f'<text x="{left + plot_w - 25}" y="{height - 8}" font-size="11" fill="#64748b">{high:+.1f}</text>'
        f'<text x="8" y="{top + 10}" font-size="11" fill="#64748b">{max_info:.1f}</text>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}">'
        f"{axis}"
        f'<polyline fill="none" stroke="#7c3aed" stroke-width="2.5" points="{" ".join(points)}"/>'
        "</svg>"
    )


def render_html(report: dict[str, Any]) -> str:
    """Mustaqil (offline) HTML dashboard."""
    title = html.escape(str(report.get("title") or "Test sifati"))
    code = html.escape(str(report.get("test_code") or ""))
    warnings = "".join(
        f"<li>{html.escape(str(value))}</li>" for value in report.get("warnings") or []
    )
    return f"""<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — test sifati</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#f1f5f9;color:#0f172a;margin:0;padding:24px}}
h1{{margin:0 0 4px;font-size:24px}} h2{{font-size:17px;margin:24px 0 10px}}
.sub{{color:#64748b;margin-bottom:18px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px}}
.card .k{{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.04em}}
.card .v{{font-size:20px;font-weight:700;margin-top:4px}}
.card .h{{font-size:11px;color:#94a3b8;margin-top:2px}}
.panel{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:14px;margin-top:10px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th,td{{padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
th{{background:#f8fafc;color:#475569;position:sticky;top:0}}
.good{{color:#15803d;font-weight:600}} .mid{{color:#b45309}} .bad{{color:#b91c1c}}
.wright{{display:flex;gap:2px;align-items:flex-end;height:150px;margin-top:12px}}
.wrow{{display:flex;flex-direction:column;align-items:center;flex:1;height:100%}}
.wl,.wc{{font-size:9px;color:#94a3b8}}
.wbar{{display:flex;align-items:flex-end;gap:2px;height:110px}}
.pbar,.ibar{{display:block;width:7px;border-radius:3px 3px 0 0}}
.pbar{{background:#8b5cf6}} .ibar{{background:#f97316}}
.legend{{font-size:12px;color:#475569}} .dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 12px}}
.dot.p{{background:#8b5cf6}} .dot.i{{background:#f97316}}
.muted{{color:#64748b}} ul{{margin:6px 0 0 18px;color:#b45309}}
</style></head><body>
<h1>{title}</h1>
<div class="sub">Kod: <b>{code}</b> · Metrika: {html.escape(str(report.get("metrics_version")))} · Manba: {html.escape(str(report.get("source")))}</div>
<div class="cards">{_cards(report)}</div>
{'<div class="panel"><h2>Ogohlantirishlar</h2><ul>' + warnings + '</ul></div>' if warnings else ''}
<div class="panel"><h2>Itemlar</h2>{_items_table(report)}</div>
<div class="panel"><h2>Wright xaritasi</h2>{_wright_html(report)}</div>
<div class="panel"><h2>Test axborot funksiyasi (TIF)</h2>{_tif_svg(report)}</div>
</body></html>"""


async def _main(args: argparse.Namespace) -> int:
    db = Database(config.DB_PATH)
    await db.connect()
    try:
        repos = Repositories(db)
        exam = None
        if args.exam_id:
            exam = await repos.exams.get(int(args.exam_id))
        elif args.test_code:
            exam = await repos.exams.get_by_code(args.test_code)
        if exam is None:
            print("Imtihon topilmadi. --exam-id yoki --test-code bering.")
            return 2

        report = await test_quality.build_exam_quality(
            repos, exam, source=args.source
        )
        summary = report["summary"]
        print(f"Exam: #{report['exam_id']} {report['test_code']} — {report['title']}")
        print(
            "N={participants} K={items} α={alpha} EAP={eap} "
            "SRMSR={srmr} RMSEA={rmsea} CFI={cfi} TLI={tli}".format(
                participants=summary.get("participants"),
                items=summary.get("items"),
                alpha=_fmt(summary.get("cronbach_alpha"), 3),
                eap=_fmt(summary.get("eap_reliability"), 3),
                srmr=_fmt(summary.get("srmr"), 3),
                rmsea=_fmt(summary.get("rmsea"), 3),
                cfi=_fmt(summary.get("cfi"), 3),
                tli=_fmt(summary.get("tli"), 3),
            )
        )
        for warning in report.get("warnings") or []:
            print(f"⚠️ {warning}")

        wrote = False
        if args.json:
            target = Path(args.json)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"JSON: {target}")
            wrote = True
        if args.html:
            target = Path(args.html)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render_html(report), encoding="utf-8")
            print(f"HTML: {target}")
            wrote = True
        if not wrote:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        await db.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_main(args))
    except test_quality.TestQualityError as exc:
        print(f"Test sifati xatosi: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

