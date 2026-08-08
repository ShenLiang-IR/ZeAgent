#!/usr/bin/env bash
# 文本统计脚本
# 统计指定文本文件的字符数、词数、行数，输出 JSON 格式结果

set -euo pipefail

if [ $# -eq 0 ]; then
    echo '{"error": "请提供至少一个文件路径"}' >&2
    exit 1
fi

total_chars=0
total_words=0
total_lines=0
files_json=""

for filepath in "$@"; do
    if [ ! -f "$filepath" ]; then
        echo "{\"error\": \"文件不存在: $filepath\"}" >&2
        exit 1
    fi

    filename=$(basename "$filepath")
    # 统计行数、词数、字符数
    lines=$(wc -l < "$filepath" | tr -d ' ')
    words=$(wc -w < "$filepath" | tr -d ' ')
    chars=$(wc -m < "$filepath" | tr -d ' ')

    total_chars=$((total_chars + chars))
    total_words=$((total_words + words))
    total_lines=$((total_lines + lines))

    if [ -n "$files_json" ]; then
        files_json="${files_json},"
    fi
    files_json="${files_json}{\"path\":\"${filename}\",\"chars\":${chars},\"words\":${words},\"lines\":${lines}}"
done

cat <<EOF
{
  "files": [${files_json}],
  "totals": {"chars":${total_chars},"words":${total_words},"lines":${total_lines}}
}
EOF
