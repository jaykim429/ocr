"""품질검토 파이프라인 CLI.

사용 예:
  quality-review samples.zip out/review
  quality-review samples/ out/review
  quality-review --ingest-agencies "식품등의+자가품질검사+매뉴얼(2018.1).pdf" --agency-pages 82-90
"""

from datetime import date, datetime
from pathlib import Path

import click

from chandra.pipeline import run_quality_review
from chandra.test_agencies import build_agency_db_from_excel, build_agency_db_from_pdf


def _parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            pages += list(range(int(a), int(b) + 1))
        elif part:
            pages.append(int(part))
    return sorted(set(pages))


@click.command()
@click.argument("input_path", type=click.Path(path_type=Path), required=False)
@click.argument("output_path", type=click.Path(path_type=Path), required=False)
@click.option("--today", type=str, default=None, help="유효기간 기준 날짜 (YYYY-MM-DD). 기본: 오늘.")
@click.option("--max-pages", type=int, default=4, help="문서당 판독할 최대 페이지 수.")
@click.option(
    "--ingest-agencies",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="위생검사전문기관 목록 PDF 를 DB로 인제스트.",
)
@click.option(
    "--agency-pages",
    type=str,
    default="82-87",
    help="식품 목록 0-기준 페이지 범위 (기본 82-87).",
)
@click.option(
    "--agency-livestock-pages",
    type=str,
    default="88-91",
    help="축산물 목록 0-기준 페이지 범위 (기본 88-91). 'none'이면 식품만.",
)
@click.option(
    "--agency-csv",
    type=click.Path(path_type=Path),
    default=None,
    help="인제스트 결과를 CSV(엑셀)로도 저장할 경로.",
)
@click.option(
    "--law-monitor",
    is_flag=True,
    default=False,
    help="식약처 식품 관련 법령·행정규칙 현행/시행예정/변경점 모니터링 실행(법제처 OC/IP 등록 필요).",
)
def main(
    input_path, output_path, today, max_pages,
    ingest_agencies, agency_pages, agency_livestock_pages, agency_csv, law_monitor,
):
    if law_monitor:
        from datetime import datetime as _dt

        from chandra.law_monitor import check_updates

        today_d = _dt.strptime(today, "%Y-%m-%d").date() if today else None
        res = check_updates(today=today_d)
        click.echo(f"법령 모니터링: 점검 {res['checked']}건 · 변경 {len(res['changed'])} · 시행예정 {len(res['upcoming'])} · 오류 {len(res['errors'])}")
        for c in res["changed"]:
            click.echo(f"  [변경] {c['item']}: {'; '.join(c['changes'])}")
        for u in res["upcoming"]:
            click.echo(f"  [시행예정] {u['item']} (시행일 {u.get('enforce_date')})")
        if res["errors"]:
            click.echo(f"  (조회 실패 {len(res['errors'])}건 — 법제처 OC/서버IP 등록 확인)")
        if not input_path:
            return

    if ingest_agencies:
        src = Path(ingest_agencies)
        csv_out = str(agency_csv) if agency_csv else None
        if src.suffix.lower() in (".xlsx", ".xls"):
            # 식약처 '시험검사기관 현황' 엑셀 (권장; 최신·정확·다시트)
            click.echo(f"시험검사기관 현황 엑셀 인제스트: {src}")
            res = build_agency_db_from_excel(str(src), csv_path=csv_out)
        else:
            # 자가품질검사 매뉴얼 PDF 텍스트레이어 (식품+축산물)
            click.echo(f"위생검사기관 목록 PDF 인제스트(텍스트레이어): {src}")
            build_agency_db_from_pdf(
                str(src), pages=_parse_pages(agency_pages),
                category="식품", section_break_kw="축산물", merge=False,
            )
            if agency_livestock_pages.lower() != "none":
                res = build_agency_db_from_pdf(
                    str(src), pages=_parse_pages(agency_livestock_pages),
                    category="축산물", section_break_kw=None, merge=True, csv_path=csv_out,
                )
            else:
                res = {"note": "식품만 인제스트"}
        click.echo(f"  완료: {res}")
        if not input_path:
            return

    if not input_path or not output_path:
        raise click.UsageError("INPUT_PATH 와 OUTPUT_PATH 가 필요합니다.")

    today_date = (
        datetime.strptime(today, "%Y-%m-%d").date() if today else date.today()
    )
    click.echo(f"품질검토 시작: {input_path} (오늘={today_date})")
    report = run_quality_review(
        input_path, output_path, today=today_date, max_pages=max_pages
    )
    click.echo(f"인식 문서: {', '.join(report['documents_found'])}")
    for step, result in report["steps"].items():
        verdict = (
            result.get("verdict", {}).get("overall_verdict")
            or result.get("overall_verdict")
            or result.get("status")
        )
        click.echo(f"  [{step}] {verdict}")
    click.echo(f"리포트 저장: {Path(output_path) / 'review_report.md'}")


if __name__ == "__main__":
    main()
