#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""validate_workflow.py -- 校验工作流命令文件是否符合 references/workflow-schema.yaml。

用法:
    python validate_workflow.py <workflow.md> [--strict] [--catalog PATH] [--json]

退出码:
    0  无 error（加 --strict 时还要求无 warning）
    1  存在 error
    2  文件或依赖不可读

检查项见 references/workflow-schema.yaml 末尾的 E1-E9 / W1-W3。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 PyYAML: pip install pyyaml\n")
    raise SystemExit(2)

KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")
OUTPUT_FORMATS = {"pdf", "markdown", "docx", "json", "jsonl", "png"}
IO_TYPES = {"files", "text", "json", "jsonl", "decision", "image"}
EMPTY_FALLBACK = {"", "-", "none", "n/a", "null", "无", "略"}
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, code: str, msg: str) -> None:
        self.errors.append(f"[{code}] {msg}")

    def warn(self, code: str, msg: str) -> None:
        self.warnings.append(f"[{code}] {msg}")


def read_frontmatter(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---"):
        raise ValueError("文件未以 '---' 开头，缺少 YAML frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("frontmatter 未闭合，缺少结束的 '---'")
    data = yaml.safe_load(text[3:end])
    if not isinstance(data, dict):
        raise ValueError("frontmatter 不是 YAML 映射")
    return data


def load_catalog(path: str) -> set[str]:
    """从 stage-catalog.md 抓取 '## stage-name：说明' 形式的阶段名。"""
    names: set[str] = set()
    if not os.path.isfile(path):
        return names
    pat = re.compile(r"^##\s+([a-z][a-z0-9-]+)\s*[：:]")
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            m = pat.match(line.strip())
            if m:
                names.add(m.group(1))
    return names


def check(path: str, catalog: set[str]) -> Report:
    rep = Report()
    try:
        fm = read_frontmatter(path)
    except Exception as exc:  # noqa: BLE001
        rep.err("E0", f"frontmatter 解析失败: {exc}")
        return rep

    wf = fm.get("workflow") or {}
    stages = fm.get("stages") or []
    ext = (fm.get("extensions") or {}).get("custom_stages") or []

    if not isinstance(wf, dict):
        rep.err("E0", "workflow 段缺失或不是映射")
        return rep

    # ---- name / version / domain / description -------------------------
    name = wf.get("name")
    if not name:
        rep.err("E1", "workflow.name 缺失")
    elif not KEBAB.match(str(name)):
        rep.err("E1", f"workflow.name 不是 kebab-case: {name}")

    ver = wf.get("version")
    if ver is None:
        rep.err("E2", "workflow.version 缺失")
    elif not SEMVER.match(str(ver)):
        rep.err("E2", f"workflow.version 不是 semver: {ver}")

    if not wf.get("domain"):
        rep.err("E0", "workflow.domain 缺失")
    if not wf.get("description"):
        rep.err("E0", "workflow.description 缺失")

    # ---- source_policy -------------------------------------------------
    sp = wf.get("source_policy") or {}
    if not isinstance(sp, dict) or not sp.get("primary"):
        rep.err("E0", "source_policy.primary 缺失")
        sp = sp if isinstance(sp, dict) else {}
    if "anchor_required" not in sp:
        rep.err("E0", "source_policy.anchor_required 缺失")
    if not sp.get("conflict_policy"):
        rep.err("E0", "source_policy.conflict_policy 缺失")

    # ---- outputs -------------------------------------------------------
    outs = wf.get("outputs") or []
    if not outs:
        rep.err("E9", "workflow.outputs 为空")
    else:
        for i, o in enumerate(outs):
            if not isinstance(o, dict):
                rep.err("E9", f"outputs[{i}] 不是映射")
                continue
            fmt = o.get("format")
            if fmt not in OUTPUT_FORMATS:
                rep.err("E9", f"outputs[{i}].format 非法: {fmt}")
            if not o.get("destination"):
                rep.err("E9", f"outputs[{i}].destination 缺失")

    # ---- stages --------------------------------------------------------
    if len(stages) < 2:
        rep.err("E3", f"stages 少于 2 个（当前 {len(stages)}）")

    custom_names = {c.get("name") for c in ext if isinstance(c, dict)}
    for c in ext:
        if isinstance(c, dict) and not c.get("reason"):
            rep.err("E4", f"自定义阶段 {c.get('name')} 未写明 reason")

    stage_names: list[str] = []
    for i, st in enumerate(stages):
        if not isinstance(st, dict):
            rep.err("E5", f"stages[{i}] 不是映射")
            continue
        sname = st.get("name")
        tag = sname or f"stages[{i}]"
        stage_names.append(str(sname))

        known = (sname in catalog) or (sname in custom_names)
        if not known and catalog:
            rep.err("E4", f"阶段 {tag} 既不在 stage-catalog 也未在 extensions.custom_stages 声明")

        if not st.get("description"):
            rep.err("E5", f"阶段 {tag} 缺少 description")
        if not st.get("input"):
            rep.err("E5", f"阶段 {tag} 缺少 input")
        else:
            for j, io in enumerate(st["input"]):
                if isinstance(io, dict):
                    if not io.get("name"):
                        rep.err("E5", f"阶段 {tag} input[{j}] 缺少 name")
                    if io.get("type") not in IO_TYPES:
                        rep.err("E5", f"阶段 {tag} input[{j}].type 非法: {io.get('type')}")
                    if "required" not in io:
                        rep.err("E5", f"阶段 {tag} input[{j}] 缺少 required")
                else:
                    rep.err("E5", f"阶段 {tag} input[{j}] 不是映射")
        if not st.get("output"):
            rep.err("E5", f"阶段 {tag} 缺少 output")
        else:
            for j, io in enumerate(st["output"]):
                if isinstance(io, dict):
                    if not io.get("name"):
                        rep.err("E5", f"阶段 {tag} output[{j}] 缺少 name")
                    if io.get("type") not in IO_TYPES:
                        rep.err("E5", f"阶段 {tag} output[{j}].type 非法: {io.get('type')}")
                else:
                    rep.err("E5", f"阶段 {tag} output[{j}] 不是映射")
        if not st.get("agent_actions"):
            rep.err("E5", f"阶段 {tag} 缺少 agent_actions")
        if "human_gate" not in st:
            rep.err("E5", f"阶段 {tag} 缺少 human_gate")

        fb = st.get("fallback")
        if fb is None:
            rep.err("E5", f"阶段 {tag} 缺少 fallback")
        elif str(fb).strip().lower() in EMPTY_FALLBACK:
            rep.warn("W1", f"阶段 {tag} 的 fallback 是无意义占位: {fb!r}")

        for ref in st.get("references") or []:
            p = os.path.join(SKILL_DIR, str(ref))
            if not os.path.exists(p):
                rep.warn("W2", f"阶段 {tag} 引用的文件不存在: {ref}")

    # ---- human gates ---------------------------------------------------
    gates = wf.get("human_gates") or []
    gate_stages = {g.get("stage") for g in gates if isinstance(g, dict)}
    for g in gates:
        if not isinstance(g, dict):
            continue
        if g.get("stage") not in stage_names:
            rep.err("E6", f"human_gates 引用了不存在的阶段: {g.get('stage')}")
        if not g.get("condition") or not str(g.get("condition", "")).strip():
            rep.err("E6", f"闸门 {g.get('stage')} 缺少 condition")
        if g.get("on_fail") not in {"halt", "warn", "rollback"}:
            rep.err("E6", f"闸门 {g.get('stage')} 的 on_fail 非法: {g.get('on_fail')}")

    for st in stages:
        if isinstance(st, dict) and st.get("human_gate") is True:
            if st.get("name") not in gate_stages:
                rep.err("E6", f"阶段 {st.get('name')} 标记 human_gate=true 但未在 workflow.human_gates 中声明")

    if "authority-arbitrate" in stage_names and "authority-arbitrate" not in gate_stages:
        rep.err("E7", "存在 authority-arbitrate 阶段，但 human_gates 未覆盖它")

    if "authority-arbitrate" in stage_names and not sp.get("secondary"):
        rep.err("E8", "source_policy.secondary 为 null，却声明了 authority-arbitrate 阶段")

    # ---- W3 原文锚定要落到 compose 阶段 --------------------------------
    if sp.get("anchor_required") is True:
        compose = next((s for s in stages if isinstance(s, dict) and s.get("name") == "compose"), None)
        if compose is None:
            rep.warn("W3", "anchor_required=true 但工作流中没有 compose 阶段")
        else:
            blob = " ".join(str(a) for a in compose.get("agent_actions") or [])
            if not any(k in blob for k in ("来源", "定位", "引用", "anchor", "citation")):
                rep.warn("W3", "anchor_required=true，但 compose 阶段的 agent_actions 未要求附来源定位")

    # ---- 文件名与 name 对齐（仅提醒） ---------------------------------
    base = os.path.basename(path)
    if base.startswith("workflow-") and name and base != f"{name}.md":
        rep.warn("W4", f"文件名 {base} 与 workflow.name {name} 不一致")

    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="校验工作流命令文件是否符合 workflow-schema.yaml")
    ap.add_argument("file", help="待校验的工作流 Markdown 文件")
    ap.add_argument("--strict", action="store_true", help="warning 也视为失败")
    ap.add_argument("--catalog", default=os.path.join(SKILL_DIR, "references", "stage-catalog.md"),
                    help="阶段目录文件路径")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        sys.stderr.write(f"文件不存在: {args.file}\n")
        return 2

    catalog = load_catalog(args.catalog)
    if not catalog:
        sys.stderr.write(f"[warn] 未能从 {args.catalog} 读到任何阶段名，跳过 E4\n")

    rep = check(args.file, catalog)

    if args.json:
        print(json.dumps({
            "file": args.file,
            "ok": not rep.errors and not (args.strict and rep.warnings),
            "errors": rep.errors,
            "warnings": rep.warnings,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"校验: {args.file}")
        print(f"阶段目录: {args.catalog}  (匹配到 {len(catalog)} 个标准阶段)")
        if rep.errors:
            print(f"\n错误 {len(rep.errors)} 条:")
            for e in rep.errors:
                print("  x", e)
        if rep.warnings:
            print(f"\n警告 {len(rep.warnings)} 条:")
            for w in rep.warnings:
                print("  !", w)
        if not rep.errors and not rep.warnings:
            print("\n通过：结构与 Schema 完全一致。")
        elif not rep.errors:
            print("\n通过（有警告）。加 --strict 可将警告视为失败。")

    return 0 if (not rep.errors and not (args.strict and rep.warnings)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
