#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
表格数据转 Tiptap Editor JSON 格式工具
支持：
- 输入：JSON 数组/对象，或 CSV 文件
- 自动识别表头、数字右对齐
- 处理合并单元格 (rowspan/colspan)
- 单元格样式 (背景色、文字颜色等)
- 多段落文本 (按换行分割)
- 表格转置
- 导出为 Tiptap 表格 JSON
"""

import argparse
import csv
import json
import re
import sys
import uuid
from typing import Any, Dict, List, Optional, Union

# Windows console 默认 GBK，强制 UTF-8 输出避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _is_sparse(data: List[List]) -> bool:
    """
    判断表格是否为稀疏矩阵（因合并单元格导致列数不一致）
    """
    if not data:
        return False
    max_col = 0
    for row in data:
        col_count = 0
        for cell in row:
            if cell is not None:
                col_count += cell.get("colspan", 1)
            else:
                col_count += 1
        max_col = max(max_col, col_count)
    for row in data:
        col_count = 0
        for cell in row:
            if cell is not None:
                col_count += cell.get("colspan", 1)
            else:
                col_count += 1
        if col_count < max_col:
            return True
    return False


def _fill_sparse_nulls(data: List[List]) -> List[List]:
    """
    将稀疏矩阵填充为完整矩阵，缺失位置用 None 补齐，以便后续处理。
    """
    if not data:
        return data
    max_col = 0
    for row in data:
        col_count = 0
        for cell in row:
            if cell is not None:
                col_count += cell.get("colspan", 1)
            else:
                col_count += 1
        max_col = max(max_col, col_count)

    if not _is_sparse(data):
        return data

    rows = len(data)
    occupied = [[False] * max_col for _ in range(rows)]
    result = []

    for i in range(rows):
        new_row = []
        col = 0
        cell_idx = 0
        while col < max_col:
            if occupied[i][col]:
                new_row.append(None)
                col += 1
                continue
            if cell_idx >= len(data[i]):
                new_row.append(None)
                col += 1
                continue
            cell = data[i][cell_idx]
            cell_idx += 1
            if cell is None:
                new_row.append(None)
                occupied[i][col] = True
                col += 1
                continue
            rowspan = cell.get("rowspan", 1)
            colspan = cell.get("colspan", 1)
            new_row.append(cell)
            for r in range(i, min(i + rowspan, rows)):
                for c in range(col, min(col + colspan, max_col)):
                    occupied[r][c] = True
            col += colspan
        result.append(new_row)
    return result


_NUMBER_RE = re.compile(r'^[+-]?[\d,]+\.?\d*%?$')


def _is_number(text: str) -> bool:
    """判断字符串是否为数字（含百分数）"""
    if not text:
        return False
    return bool(_NUMBER_RE.match(text.strip()))


def _detect_header_rows(data: List[List]) -> int:
    """
    自动检测表头行数：以连续加粗的行作为表头，至少为 1。
    """
    header_count = 0
    for row in data:
        has_bold = any(
            cell is not None and cell.get("bold", False)
            for cell in row
        )
        if has_bold:
            header_count += 1
        else:
            break
    return max(header_count, 1)


def _apply_smart_styles(
    data: List[List],
    header_rows: Optional[int] = None,
    default_align: str = "center",
    default_bold: bool = False,
) -> List[List]:
    """
    智能样式应用：
    - 数字列右对齐
    - 表头行居中加粗
    - 其余行使用默认对齐和加粗
    """
    if not data:
        return data

    if header_rows is None:
        header_rows = _detect_header_rows(data)

    result = []
    for i, row in enumerate(data):
        new_row = []
        is_header = i < header_rows
        for cell in row:
            if cell is None:
                new_row.append(None)
                continue
            new_cell = dict(cell)
            if "align" not in new_cell:
                text = new_cell.get("text", "")
                if _is_number(text):
                    new_cell["align"] = "right"
                elif is_header:
                    new_cell["align"] = "center"
                else:
                    new_cell["align"] = default_align
            if "bold" not in new_cell:
                new_cell["bold"] = True if is_header else default_bold
            new_row.append(new_cell)
        result.append(new_row)
    return result


def _merge_structure_data(spec: Dict[str, Any]) -> List[List]:
    """
    将结构化数据（headers, data, merge_columns, summary）转换为二维列表。
    """
    headers = spec.get("headers", [])
    raw_data = spec.get("data", [])
    merge_cols = spec.get("merge_columns", [])
    summary = spec.get("summary", None)

    result = [list(row) for row in headers]

    if raw_data:
        cell_rows = []
        for raw_row in raw_data:
            cell_row = []
            for val in raw_row:
                if isinstance(val, dict):
                    cell_row.append(val)
                else:
                    cell_row.append({"text": str(val)})
            cell_rows.append(cell_row)

        # 按列合并相邻相同值的单元格（rowspan）
        merged_positions = set()
        for col_idx in merge_cols:
            i = 0
            while i < len(cell_rows):
                if col_idx >= len(cell_rows[i]):
                    i += 1
                    continue
                current_cell = cell_rows[i][col_idx]
                current_val = current_cell.get("text", "") if current_cell else ""
                j = i + 1
                while j < len(cell_rows):
                    if col_idx >= len(cell_rows[j]):
                        break
                    next_cell = cell_rows[j][col_idx]
                    next_val = next_cell.get("text", "") if next_cell else ""
                    if next_val != current_val:
                        break
                    j += 1
                span = j - i
                if span > 1 and current_cell:
                    current_cell["rowspan"] = span
                    for k in range(i + 1, j):
                        merged_positions.add((k, col_idx))
                i = j

        for row_idx, cell_row in enumerate(cell_rows):
            sparse_row = [
                cell for col_idx, cell in enumerate(cell_row)
                if (row_idx, col_idx) not in merged_positions
            ]
            result.append(sparse_row)

    if summary:
        summary_row = []
        for val in summary:
            if val is None:
                summary_row.append(None)
            elif isinstance(val, dict):
                summary_row.append(val)
            else:
                summary_row.append({"text": str(val), "bold": True})
        result.append(summary_row)

    return result


def format_table_to_json(
    data: Union[List[List[Optional[Dict[str, Any]]]], Dict[str, Any]],
    default_align: str = "center",
    default_bold: bool = False,
    header_rows: Optional[int] = None,
    auto_style: bool = True,
    split_lines: bool = False,           # 新增：是否将文本按换行分割为多个段落
    default_style: Optional[str] = None, # 新增：默认单元格 CSS 样式
    table_id: Optional[str] = None,      # 新增：自定义表格 ID
) -> Dict[str, Any]:
    """
    将表格数据转换为 Tiptap Editor 的 table 节点 JSON。

    参数：
        data: 二维列表或结构化字典（包含 headers, data, merge_columns, summary）
        default_align: 默认文本对齐方式
        default_bold: 默认是否加粗
        header_rows: 表头行数，None 表示自动检测
        auto_style: 是否启用智能样式（数字右对齐，表头加粗居中）
        split_lines: 是否将单元格文本中的 '\n' 分割为多个段落
        default_style: 全局默认 CSS 样式字符串，如 "background:#fff;color:#000"
        table_id: 自定义表格 ID，不指定则自动生成

    返回：
        Tiptap 表格 JSON 对象
    """
    if isinstance(data, dict):
        if "header_rows" in data and header_rows is None:
            header_rows = data["header_rows"]
        data = _merge_structure_data(data)

    if not data or not data[0]:
        print("Error: empty data (no rows or first row empty)", file=sys.stderr)
        sys.exit(1)

    # 兼容纯字符串单元格：自动转为 {"text": str}
    data = [
        [({"text": str(cell)} if isinstance(cell, str) else cell) for cell in row]
        for row in data
    ]

    data = _fill_sparse_nulls(data)

    if auto_style:
        data = _apply_smart_styles(
            data,
            header_rows=header_rows,
            default_align=default_align,
            default_bold=default_bold,
        )

    # 生成 ID
    tid = table_id if table_id else f"table-{uuid.uuid4().hex[:8]}"
    section_uuid = f"section-{uuid.uuid4().hex[:8]}"

    rows = len(data)
    # 计算最大列数（考虑 colspan）
    max_col = 0
    for i in range(rows):
        col_idx = 0
        for j in range(len(data[i])):
            cell = data[i][j]
            if cell is not None:
                col_idx += cell.get("colspan", 1)
            else:
                col_idx += 1
        max_col = max(max_col, col_idx)

    occupied = [[False] * max_col for _ in range(rows)]
    table_rows = []

    for i in range(rows):
        row_cells = []
        col = 0
        j = 0
        while j < len(data[i]):
            while col < max_col and occupied[i][col]:
                col += 1
            if col >= max_col:
                break
            cell_dict = data[i][j]
            if cell_dict is None:
                j += 1
                continue

            rowspan = cell_dict.get("rowspan", 1)
            colspan = cell_dict.get("colspan", 1)
            text = cell_dict.get("text", "")
            align = cell_dict.get("align", default_align)
            bold = cell_dict.get("bold", default_bold)

            # 标记占用位置
            for r in range(i, min(i + rowspan, rows)):
                for c in range(col, min(col + colspan, max_col)):
                    occupied[r][c] = True

            # ---------- 处理单元格样式 ----------
            # 构造 style 属性：合并默认样式、单元格自定义 style、以及 background/color 等字段
            cell_style_parts = []
            if default_style:
                cell_style_parts.append(default_style)
            if cell_dict.get("style"):
                cell_style_parts.append(cell_dict["style"])
            # 可单独指定 background 和 color
            if cell_dict.get("background"):
                cell_style_parts.append(f"background-color:{cell_dict['background']}")
            if cell_dict.get("color"):
                cell_style_parts.append(f"color:{cell_dict['color']}")
            if cell_dict.get("fontSize"):
                cell_style_parts.append(f"font-size:{cell_dict['fontSize']}")
            # 合并样式字符串（用分号连接）
            style_str = ";".join([s.rstrip(';') for s in cell_style_parts if s]) if cell_style_parts else None

            # ---------- 生成单元格内容（段落） ----------
            # 若 split_lines 且文本包含换行，则分割为多个段落
            if split_lines and "\n" in text:
                paragraphs = []
                for line in text.split("\n"):
                    if not line and not any(c for c in text if c not in '\n'):  # 全空行则保留空段落
                        line = ""
                    text_node = {"type": "text", "text": line}
                    if bold:
                        text_node["marks"] = [{"type": "bold"}]
                    paragraph = {
                        "type": "paragraph",
                        "attrs": {"textAlign": align},
                        "content": [text_node]
                    }
                    paragraphs.append(paragraph)
                # 若因分割产生空列表（理论上不会），给一个空白段落
                if not paragraphs:
                    paragraphs.append({
                        "type": "paragraph",
                        "attrs": {"textAlign": align},
                        "content": [{"type": "text", "text": ""}]
                    })
                cell_content = paragraphs
            else:
                # 单个段落
                text_node = {"type": "text", "text": text}
                if bold:
                    text_node["marks"] = [{"type": "bold"}]
                paragraph = {
                    "type": "paragraph",
                    "attrs": {"textAlign": align},
                    "content": [text_node]
                }
                cell_content = [paragraph]

            # 构建 tableCell 节点
            cell_attrs = {}
            if colspan > 1:
                cell_attrs["colspan"] = colspan
            if rowspan > 1:
                cell_attrs["rowspan"] = rowspan
            if style_str:
                cell_attrs["style"] = style_str

            table_cell = {
                "type": "tableCell",
                "content": cell_content
            }
            if cell_attrs:
                table_cell["attrs"] = cell_attrs

            row_cells.append(table_cell)
            j += 1
            col += colspan

        if row_cells:
            table_rows.append({
                "type": "tableRow",
                "content": row_cells
            })

    return {
        "type": "table",
        "attrs": {
            "id": tid,
            "sectionUuid": section_uuid,
        },
        "content": table_rows
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert table data to Tiptap editor JSON format",
        epilog="支持 JSON / CSV 输入，自动识别表头，合并单元格，样式定制等。"
    )
    parser.add_argument(
        "--data",
        required=True,
        help="数据来源：JSON 字符串，或 @/path/to/file.json (或 .csv)，或直接传入 CSV 内容（需配合 --format csv）"
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="输入数据格式，默认 json。当文件扩展名为 .csv 时自动切换为 csv"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出文件路径（自动追加 .json 后缀），默认输出到 stdout"
    )
    parser.add_argument(
        "--align",
        default="center",
        choices=["left", "center", "right"],
        help="默认文本对齐方式，默认 center"
    )
    parser.add_argument(
        "--bold",
        action="store_true",
        default=False,
        help="所有文本默认加粗（表头默认加粗）"
    )
    parser.add_argument(
        "--header-rows",
        type=int,
        default=None,
        help="指定表头行数（自动检测则省略）"
    )
    parser.add_argument(
        "--no-auto-style",
        action="store_true",
        default=False,
        help="关闭智能样式（表头加粗居中、数字右对齐）"
    )
    parser.add_argument(
        "--transpose",
        action="store_true",
        default=False,
        help="转置表格（行<->列互换）"
    )
    parser.add_argument(
        "--split-lines",
        action="store_true",
        default=False,
        help="将单元格文本中的换行符 \\n 分割为多个段落"
    )
    parser.add_argument(
        "--default-style",
        default=None,
        help="全局默认 CSS 样式，如 'background:#f0f0f0;color:#333'"
    )
    parser.add_argument(
        "--table-id",
        default=None,
        help="自定义表格 id，默认自动生成"
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON 输出缩进空格数，默认 2"
    )
    args = parser.parse_args()

    # ---------- 读取数据 ----------
    raw_data = args.data
    if raw_data.startswith("@"):
        file_path = raw_data[1:]
        # 自动检测格式：若扩展名为 .csv 则使用 csv 模式
        if file_path.lower().endswith(".csv") and args.format == "json":
            args.format = "csv"
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                if args.format == "csv":
                    # CSV 解析
                    reader = csv.reader(f)
                    data = list(reader)
                else:
                    data = json.load(f)
        except FileNotFoundError:
            print(f"Error: file not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        except (json.JSONDecodeError, csv.Error) as e:
            print(f"Error: invalid data in file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # 直接传入内容
        if args.format == "csv":
            # 将字符串按行分割为二维列表
            lines = raw_data.strip().splitlines()
            reader = csv.reader(lines)
            data = list(reader)
        else:
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                print(f"Error: invalid JSON data: {e}", file=sys.stderr)
                sys.exit(1)

    # ---------- 数据预处理 ----------
    # 如果输入是二维数组且不是字典，且元素是列表，则转换为字典格式（兼容）
    if isinstance(data, list) and data and isinstance(data[0], list):
        # 如果是 CSV 读取的，所有元素都是字符串，需转换为 {"text": ...}，后续 format 函数会自动处理
        pass  # 保持原样

    # 转置（若需要）
    if args.transpose:
        if isinstance(data, list) and data and all(isinstance(row, list) for row in data):
            # 确保所有行等长（用 None 补齐）
            max_len = max(len(row) for row in data)
            padded = [row + [None] * (max_len - len(row)) for row in data]
            # 转置
            transposed = [[padded[r][c] for r in range(len(padded))] for c in range(max_len)]
            data = transposed
        else:
            print("Warning: --transpose only works for simple 2D array input, ignoring", file=sys.stderr)

    # ---------- 转换 ----------
    result = format_table_to_json(
        data,
        default_align=args.align,
        default_bold=args.bold,
        header_rows=args.header_rows,
        auto_style=not args.no_auto_style,
        split_lines=args.split_lines,
        default_style=args.default_style,
        table_id=args.table_id,
    )

    # ---------- 输出 ----------
    output_json = json.dumps(result, ensure_ascii=False, indent=args.indent)
    if args.output:
        output_path = args.output if args.output.endswith(".json") else f"{args.output}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(output_path)
    else:
        print(output_json)


if __name__ == "__main__":
    main()