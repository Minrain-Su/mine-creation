#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_pdf.py -- 通用构建：封面与正文分别渲染 → 合并 → 盖页码 → 写书签 → 落盘。

用法:
    python build_pdf.py --body body.html --cover cover.html \
        --out build/book.pdf --dest "课本/书名.pdf" \
        --title "心房颤动" --author "医学教材编辑部"

要点（都是实测踩过的）:
  * 封面必须单独渲染（@page margin:0），不能靠负 margin 抵消正文版心；
  * 页码从正文第 1 页起，封面不编号；
  * 书签由正文 <h2> 文本反查页码，标题文本必须与正文完全一致；
  * 目标文件被占用 → 另存带后缀副本并如实报告，不谎称成功。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

try:
    import pymupdf
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 PyMuPDF: pip install pymupdf\n")
    raise SystemExit(2)

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]


def find_browser() -> str:
    for p in BROWSERS:
        if os.path.isfile(p):
            return p
    raise SystemExit("找不到 Chromium 内核浏览器（Edge/Chrome），请用 --browser 指定")


def render(browser: str, src: str, out: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           "--run-all-compositor-stages-before-draw", "--virtual-time-budget=9000",
           f"--print-to-pdf={out}", "file:///" + os.path.abspath(src).replace("\\", "/")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not os.path.exists(out):
        sys.stderr.write(r.stdout + "\n" + r.stderr + "\n")
        raise SystemExit(f"渲染失败: {src}")


def norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", s)


def h2_titles(html_path: str) -> list[str]:
    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()
    out = []
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", html, re.S):
        t = re.sub(r"<[^>]+>", "", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        # 二级标题常写成 <span class="n">一</span>定义，书签里补一个空格更好读
        t = re.sub(r"^([一二三四五六七八九十]+)(?=[^\s])", r"\1 ", t)
        if t:
            out.append(t)
    return out


def stamp_and_toc(pdf: str, titles: list[str], meta: dict) -> int:
    doc = pymupdf.open(pdf)
    texts = [norm(doc[i].get_text()) for i in range(doc.page_count)]

    outline = [[1, "封面", 1]]
    cursor = 1
    for t in titles:
        key = norm(t)
        hit = None
        for i in range(cursor, doc.page_count):
            if key and key in texts[i]:
                hit = i
                break
        if hit is None:
            sys.stderr.write(f"[warn] 书签定位失败: {t}\n")
            continue
        outline.append([2, re.sub(r"\s+", " ", t), hit + 1])
        cursor = hit

    for i in range(1, doc.page_count):
        page = doc[i]
        w, h = page.rect.width, page.rect.height
        page.insert_text((w / 2 - 5, h - 24), str(i), fontname="helv", fontsize=8.2,
                         color=(0.36, 0.42, 0.48))

    doc.set_toc(outline)
    doc.set_metadata({k: v for k, v in meta.items() if v})
    doc.saveIncr()
    n = doc.page_count
    doc.close()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="封面+正文 → 成品 PDF")
    ap.add_argument("--body", required=True)
    ap.add_argument("--cover")
    ap.add_argument("--out", required=True, help="中间产物路径")
    ap.add_argument("--dest", help="最终落盘路径；被占用时自动改名")
    ap.add_argument("--title", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--keywords", default="")
    ap.add_argument("--browser")
    args = ap.parse_args()

    browser = args.browser or find_browser()

    body_pdf = os.path.join(os.path.dirname(os.path.abspath(args.out)), "_body.pdf")
    render(browser, args.body, body_pdf)

    if args.cover:
        cover_pdf = os.path.join(os.path.dirname(os.path.abspath(args.out)), "_cover.pdf")
        render(browser, args.cover, cover_pdf)
        dst = pymupdf.open(cover_pdf)
        dst.insert_pdf(pymupdf.open(body_pdf))
        dst.save(args.out)
        dst.close()
    else:
        shutil.copy(body_pdf, args.out)

    pages = stamp_and_toc(args.out, h2_titles(args.body), {
        "title": args.title, "author": args.author,
        "subject": args.subject, "keywords": args.keywords,
    })

    target = args.out
    if args.dest:
        os.makedirs(os.path.dirname(os.path.abspath(args.dest)), exist_ok=True)
        try:
            shutil.copy(args.out, args.dest)
            target = args.dest
        except PermissionError:
            stem, ext = os.path.splitext(args.dest)
            alt = f"{stem}（终）{ext}"
            shutil.copy(args.out, alt)
            target = alt
            sys.stderr.write("!! 目标文件被占用，已输出到: " + alt + "\n")

    print(f"OK pages={pages} size={os.path.getsize(target)/1024/1024:.2f}MB -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
