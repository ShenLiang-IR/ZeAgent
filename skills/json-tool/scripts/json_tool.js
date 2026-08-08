#!/usr/bin/env node
/**
 * JSON 工具脚本
 *
 * 支持 format / minify / keys / query 四种操作。
 * 纯 Node.js 内置 API，无外部依赖。
 */

"use strict";

const fs = require("fs");
const path = require("path");

// ─── 参数解析 ──────────────────────────────────────────────

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith("--")) {
      const key = argv[i].slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith("--")) {
        args[key] = next;
        i++;
      } else {
        args[key] = true;
      }
    }
  }
  return args;
}

// ─── 路径查询 ──────────────────────────────────────────────

function queryPath(obj, pathStr) {
  const parts = pathStr.split(".");
  let current = obj;
  for (const part of parts) {
    if (current == null) return undefined;
    // 支持数组索引
    const idx = parseInt(part, 10);
    if (!isNaN(idx) && Array.isArray(current)) {
      current = current[idx];
    } else if (typeof current === "object") {
      current = current[part];
    } else {
      return undefined;
    }
  }
  return current;
}

// ─── 收集所有键 ──────────────────────────────────────────

function collectKeys(obj, prefix) {
  prefix = prefix || "";
  const keys = [];
  if (typeof obj !== "object" || obj === null) return keys;

  for (const key of Object.keys(obj)) {
    const fullKey = prefix ? prefix + "." + key : key;
    keys.push(fullKey);
    if (typeof obj[key] === "object" && obj[key] !== null && !Array.isArray(obj[key])) {
      const nested = collectKeys(obj[key], fullKey);
      keys.push(...nested);
    }
  }
  return keys;
}

// ─── 主流程 ──────────────────────────────────────────────

function main() {
  const args = parseArgs(process.argv);

  if (!args.input) {
    console.error("ERROR: 缺少 --input 参数");
    process.exit(1);
  }
  if (!args.action) {
    console.error("ERROR: 缺少 --action 参数");
    process.exit(1);
  }

  // 读取 JSON 数据
  let rawData;
  let inputPath;
  const resolvedInput = path.resolve(args.input);
  if (fs.existsSync(resolvedInput)) {
    rawData = fs.readFileSync(resolvedInput, "utf-8");
    inputPath = resolvedInput;
  } else {
    // 当作 JSON 字符串
    rawData = args.input;
  }

  let data;
  try {
    data = JSON.parse(rawData);
  } catch (e) {
    console.error("ERROR: JSON 解析失败:", e.message);
    process.exit(1);
  }

  // 执行操作
  let result;
  switch (args.action) {
    case "format":
      result = JSON.stringify(data, null, 2);
      break;

    case "minify":
      result = JSON.stringify(data);
      break;

    case "keys":
      result = JSON.stringify(collectKeys(data), null, 2);
      break;

    case "query":
      if (!args.path) {
        console.error("ERROR: query 操作需要 --path 参数");
        process.exit(1);
      }
      result = JSON.stringify(queryPath(data, args.path), null, 2);
      break;

    default:
      console.error("ERROR: 未知操作:", args.action);
      console.error("支持的操作: format, minify, keys, query");
      process.exit(1);
  }

  console.log(result);
}

main();
