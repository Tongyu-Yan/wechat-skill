#!/usr/bin/env python3
"""Generate a one-page Chinese promo PDF for community sharing."""

from pathlib import Path
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_pdf(output_path: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCN",
        parent=styles["Title"],
        fontName="STSong-Light",
        fontSize=24,
        leading=30,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleCN",
        parent=styles["Normal"],
        fontName="STSong-Light",
        fontSize=12,
        leading=18,
        textColor=colors.HexColor("#374151"),
        spaceAfter=14,
    )
    section_style = ParagraphStyle(
        "SectionCN",
        parent=styles["Heading2"],
        fontName="STSong-Light",
        fontSize=14,
        leading=20,
        textColor=colors.HexColor("#111827"),
        spaceBefore=8,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "BodyCN",
        parent=styles["Normal"],
        fontName="STSong-Light",
        fontSize=11,
        leading=17,
        textColor=colors.HexColor("#1f2937"),
    )
    callout_style = ParagraphStyle(
        "CalloutCN",
        parent=body_style,
        backColor=colors.HexColor("#fff7ed"),
        borderColor=colors.HexColor("#fb923c"),
        borderWidth=0.8,
        borderPadding=8,
        borderRadius=4,
        textColor=colors.HexColor("#9a3412"),
        spaceBefore=8,
        spaceAfter=8,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="WeChat Event Autopilot 社群宣传",
        author="wechat-skill",
    )

    story = [
        Paragraph("微信自动化回复助手（OpenClaw + TuriX）", title_style),
        Paragraph(
            "把微信新消息事件接入 OpenClaw，让 AI 决策后通过 TuriX 操作电脑完成回复、跟进和日常消息处理。",
            subtitle_style,
        ),
        Paragraph("一句话介绍", section_style),
        Paragraph(
            "这是一个 macOS 上的微信事件驱动 skill：读取通知中心中的微信消息事件，"
            "通过 hook 发送给 OpenClaw（龙虾），再由 OpenClaw 调用 TuriX 执行电脑操作。",
            body_style,
        ),
        Paragraph("你能得到什么", section_style),
        Paragraph(
            "• 新消息自动触发，无需手动盯微信<br/>"
            "• AI 按你的规则判断是否回复、回复什么<br/>"
            "• 支持白名单 / 黑名单 / 全量三种回复模式<br/>"
            "• 可接入现有 OpenClaw 工作流，低改造成本",
            body_style,
        ),
        Paragraph("快速上手（3 步）", section_style),
        Paragraph(
            "1. 安装并配置 TuriX-CUA（必需，推荐 mac_legacy 分支）<br/>"
            "2. 配置 OpenClaw hooks 与会话参数<br/>"
            "3. 安装监听器并选择回复模式（whitelist / blacklist / all）",
            body_style,
        ),
    ]

    table_data = [
        ["模式", "适合场景"],
        ["whitelist", "只对指定联系人自动回复（最稳妥）"],
        ["blacklist", "对大部分联系人自动回复，排除少数不处理对象"],
        ["all", "对所有联系人自动回复（自动化程度最高）"],
    ]
    mode_table = Table(table_data, colWidths=[44 * mm, 120 * mm], hAlign="LEFT")
    mode_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 10.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#d1d5db")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    story.extend(
        [
            Spacer(1, 6),
            mode_table,
            Paragraph("重要说明（请务必知悉）", section_style),
            Paragraph(
                "由于微信风控较强，目前只能通过 macOS 通知中心拿取消息事件；"
                "消息可能出现延迟、被折叠、被遮挡，这属于预期现象。",
                callout_style,
            ),
            Paragraph(
                "开源地址：<br/>"
                "• wechat-skill: https://github.com/Tongyu-Yan/wechat-skill<br/>"
                "• TuriX-CUA: https://github.com/TurixAI/TuriX-CUA<br/>"
                "• 推荐分支: https://github.com/TurixAI/TuriX-CUA/tree/mac_legacy",
                body_style,
            ),
            Spacer(1, 8),
            Paragraph(
                "如果你想让微信消息处理更自动化，又希望可控、可配置、可扩展，"
                "这个方案适合你。欢迎进群交流落地经验。",
                body_style,
            ),
        ]
    )

    doc.build(story)


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("wechat-event-autopilot-community-promo.pdf")
    build_pdf(output)
    print(f"Generated: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
