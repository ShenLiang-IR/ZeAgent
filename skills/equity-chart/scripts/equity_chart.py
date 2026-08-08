import argparse
import json
import mimetypes
import sys
from pathlib import Path
from graphviz import Digraph

# Windows console 默认 GBK，强制 UTF-8 输出避免中文乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
def generate_equity_structure(data, output_file='', rankdir='TB'):
    dot = Digraph(name=output_file, format='png')
    FONT = 'SimSun'
    dot.attr(
        rankdir=rankdir,
        splines='ortho',
        nodesep='0.9',
        ranksep='1.1',
        dpi='200',
        bgcolor='white',
        pad='0.5',
        fontname=FONT,
    )
    nodes = set()
    for item in data:
        nodes.add(item['parent'])
        nodes.add(item['child'])
    for node in nodes:
        dot.node(
            node, node,
            fontname=FONT,
            fontsize='16',
            shape='box',
            style='solid',
            color='black',
            fontcolor='black',
            penwidth='2.0',
            margin='0.25,0.15',
        )
    for item in data:
        ratio = item['ratio']
        label = str(ratio).replace('%', '') + '%' if '%' not in str(ratio) else str(ratio)
        dot.edge(
            item['parent'], item['child'],
            xlabel=label,
            fontname=FONT,
            fontsize='14',
            fontcolor='black',
            color='black',
            penwidth='1.2',
            arrowsize='0.8',
        )
    dot.render(output_file, view=False, cleanup=True)
    print(f"OK:  {output_file}.png")
def upload_chart(local_path: str, category: str) -> dict:
    from infrastructure.storage.upload_factory import get_file_uploader
    from infrastructure.storage.upload_base import UploadRequest
    content_type = mimetypes.guess_type(local_path)[0] or "image/png"
    uploader = get_file_uploader()
    result = uploader.upload(UploadRequest(
        local_path=local_path,
        category=category,
        content_type=content_type,
    ))
    return {
        "provider": result.provider,
        "bucketName": result.bucket_name,
        "filePath": result.file_path,
    }
def main():
    parser = argparse.ArgumentParser(description="Generate equity structure chart (PNG) from JSON data")
    parser.add_argument('--data', required=True, help="JSON data string or @file.json to read from file")
    parser.add_argument('--output', default='', help="output file path (auto append .png)")
    parser.add_argument('--rankdir', default='TB', choices=['TB', 'LR'], help="graph direction: TB (top-bottom, default) or LR (left-right)")
    parser.add_argument('--upload', action='store_true', default=True, help="auto upload to persistent storage (default on)")
    parser.add_argument('--no-upload', dest='upload', action='store_false', help="skip upload, only generate local file")
    parser.add_argument('--category', default='equity-chart', help="upload path category prefix (default equity-chart)")
    args = parser.parse_args()
    raw = args.data
    if raw.startswith('@'):
        filepath = raw[1:]
        try:
            raw = Path(filepath).read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            print(f"ERROR: : {e}", file=sys.stderr)
            sys.exit(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON : {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list) or len(data) == 0:
        print("ERROR: ", file=sys.stderr)
        sys.exit(1)
    generate_equity_structure(data, args.output, args.rankdir)
    if args.upload:
        output_png = f"{args.output}.png"
        if not Path(output_png).exists():
            print(f"ERROR: : {output_png}", file=sys.stderr)
            sys.exit(1)
        try:
            upload_result = upload_chart(output_png, args.category)
            print(f"UPLOAD_RESULT: {json.dumps(upload_result, ensure_ascii=False)}")
        except Exception as e:
            print(f"WARN: : {e}", file=sys.stderr)
if __name__ == "__main__":
    main()