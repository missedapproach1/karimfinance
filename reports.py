"""Отчёты: месячный PDF с графиками и недельный текстовый."""
import io
import logging
import datetime
import calendar

logger = logging.getLogger(__name__)


def aggregate_period(operations, debts_before, debts_after, start, end):
    income_by_cat = {}
    expense_by_cat = {}
    debt_payments = 0
    total_income = 0
    total_expense = 0
    ops = [o for o in operations if o.get("дата")]
    ops.sort(key=lambda o: o["дата"])
    for o in ops:
        d = o["дата"].date() if isinstance(o["дата"], datetime.datetime) else o["дата"]
        amt = float(o.get("сумма", 0) or 0)
        cat = str(o.get("категория", "Прочее")).strip()
        if d < start or d > end:
            continue
        if amt > 0:
            total_income += amt
            income_by_cat[cat] = income_by_cat.get(cat, 0) + amt
        elif amt < 0:
            total_expense += abs(amt)
            if cat == "Долги/кредиты":
                debt_payments += abs(amt)
            else:
                expense_by_cat[cat] = expense_by_cat.get(cat, 0) + abs(amt)
    return {
        "start": start, "end": end,
        "total_income": round(total_income),
        "total_expense": round(total_expense),
        "income_by_cat": {k: round(v) for k, v in income_by_cat.items()},
        "expense_by_cat": {k: round(v) for k, v in expense_by_cat.items()},
        "debt_payments": round(debt_payments),
    }


def format_weekly_text(agg, ai_comment=""):
    s = agg["start"].strftime("%d.%m")
    e = agg["end"].strftime("%d.%m")
    lines = [f"📅 Отчёт за неделю ({s}–{e})", ""]
    lines.append(f"💵 Доходы: {agg['total_income']:,} ₽")
    lines.append(f"💸 Расходы: {agg['total_expense']:,} ₽")
    if agg["debt_payments"]:
        lines.append(f"🔴 На долги: {agg['debt_payments']:,} ₽")
    lines.append("")
    if agg["expense_by_cat"]:
        lines.append("Траты по категориям:")
        for cat, v in sorted(agg["expense_by_cat"].items(), key=lambda x: -x[1]):
            lines.append(f"  • {cat}: {v:,} ₽")
    if ai_comment:
        lines.append("")
        lines.append(f"🤖 {ai_comment}")
    return "\n".join(lines)


def _make_charts(agg):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    charts = {}
    exp = agg["expense_by_cat"]
    if exp:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        cats = list(exp.keys())
        vals = list(exp.values())
        colors = plt.cm.Set3(range(len(cats)))
        ax.pie(vals, labels=cats,
               autopct=lambda p: f'{int(round(p*sum(vals)/100)):,}',
               colors=colors, startangle=90, textprops={'fontsize': 9})
        ax.set_title("Расходы по категориям", fontsize=13, fontweight='bold')
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        charts['expense_pie'] = buf
    fig, ax = plt.subplots(figsize=(6, 3.5))
    labels = ['Доходы', 'Расходы', 'На долги']
    values = [agg['total_income'], agg['total_expense'], agg['debt_payments']]
    bars = ax.bar(labels, values, color=['#4CAF50', '#FF7043', '#C62828'])
    ax.set_title("Итоги месяца", fontsize=13, fontweight='bold')
    ax.set_ylabel("руб")
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f'{val:,}', ha='center', va='bottom', fontsize=9)
    buf2 = io.BytesIO()
    fig.savefig(buf2, format='png', dpi=120, bbox_inches='tight')
    plt.close(fig)
    buf2.seek(0)
    charts['summary_bar'] = buf2
    return charts


def build_monthly_pdf(agg, debts_summary, ai_comment, out_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                    Table, TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_name = "DejaVu"
    try:
        pdfmetrics.registerFont(TTFont(font_name, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont(font_name + "-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
        bold_name = font_name + "-Bold"
    except Exception as e:
        logger.warning(f"Шрифт не найден: {e}")
        font_name = "Helvetica"
        bold_name = "Helvetica-Bold"
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Title"], fontName=bold_name, fontSize=20)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName=bold_name, fontSize=14)
    normal = ParagraphStyle("N", parent=styles["Normal"], fontName=font_name, fontSize=11, leading=16)
    small = ParagraphStyle("S", parent=styles["Normal"], fontName=font_name, fontSize=9, textColor=colors.grey)
    doc = SimpleDocTemplate(out_path, pagesize=A4, topMargin=1.5*cm, bottomMargin=1.5*cm,
                            leftMargin=1.8*cm, rightMargin=1.8*cm)
    story = []
    months_ru = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                 "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    m = agg["start"].month
    y = agg["start"].year
    story.append(Paragraph("Финансовый отчёт", title_style))
    story.append(Paragraph(f"{months_ru[m]} {y}", h2))
    story.append(Spacer(1, 0.4*cm))
    saldo = agg["total_income"] - agg["total_expense"]
    data = [
        ["Доходы за месяц", f"{agg['total_income']:,} \u20bd"],
        ["Расходы за месяц", f"{agg['total_expense']:,} \u20bd"],
        ["  из них на долги", f"{agg['debt_payments']:,} \u20bd"],
        ["Сальдо (доход - расход)", f"{saldo:+,} \u20bd"],
        ["Общий долг стало", f"{debts_summary.get('total_after', 0):,} \u20bd"],
    ]
    t = Table(data, colWidths=[9*cm, 6*cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("TEXTCOLOR", (1, 3), (1, 3), colors.green if saldo >= 0 else colors.red),
        ("FONTNAME", (0, 3), (1, 3), bold_name),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5*cm))
    try:
        charts = _make_charts(agg)
        if 'summary_bar' in charts:
            story.append(Image(charts['summary_bar'], width=15*cm, height=8.75*cm))
            story.append(Spacer(1, 0.3*cm))
        if 'expense_pie' in charts:
            story.append(Image(charts['expense_pie'], width=14*cm, height=10.5*cm))
    except Exception as e:
        logger.warning(f"Графики: {e}")
    closed = debts_summary.get("closed", [])
    if closed:
        story.append(Paragraph("Закрытые долги за месяц:", h2))
        for name in closed:
            story.append(Paragraph(f"✓ {name}", normal))
        story.append(Spacer(1, 0.3*cm))
    if ai_comment:
        story.append(Paragraph("Комментарий помощника:", h2))
        for para in ai_comment.split("\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), normal))
                story.append(Spacer(1, 0.15*cm))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"Сформировано {datetime.date.today().strftime('%d.%m.%Y')}", small))
    doc.build(story)
    return out_path


def last_week_range(today=None):
    if today is None:
        today = datetime.date.today()
    this_monday = today - datetime.timedelta(days=today.weekday())
    last_monday = this_monday - datetime.timedelta(days=7)
    last_sunday = this_monday - datetime.timedelta(days=1)
    return last_monday, last_sunday


def current_month_range(today=None):
    if today is None:
        today = datetime.date.today()
    start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = today.replace(day=last_day)
    return start, end
