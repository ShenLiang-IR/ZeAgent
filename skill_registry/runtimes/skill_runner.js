/**
 * 通用 Skill 执行器（Node.js）— 在 skill 的独立 node_modules 中被调用。
 *
 * 协议（JSON over stdio，与 Python runner 一致）：
 *   输入（stdin 一行 JSON）：
 *     {"module_path": "test_node_skill.js", "function_name": "echo", "arguments": {"text": "hello"}}
 *   输出（stdout 一行 JSON）：
 *     {"success": true, "result": "NodeJS echo: hello"}
 *
 * module_path 可以是：
 *   - 绝对路径
 *   - 相对于 skill_registry 目录的路径
 *   - 相对于 cwd（node env 目录）的路径
 */

import * as path from "path";
import * as fs from "fs";
import * as url from "url";
import * as readline from "readline";

const __filename_runner = url.fileURLToPath(import.meta.url);
const __dirname_runner = path.dirname(__filename_runner);
const _SKILL_REGISTRY_DIR = path.dirname(__dirname_runner);
const _AGENT_DIR = path.dirname(_SKILL_REGISTRY_DIR);

function resolveModulePath(modulePath) {
    // 1. 绝对路径
    if (path.isAbsolute(modulePath) && fs.existsSync(modulePath)) {
        return path.toNamespacedPath(modulePath);
    }
    // 2. 相对于 skill_registry 目录
    const skillRegPath = path.join(_SKILL_REGISTRY_DIR, modulePath);
    if (fs.existsSync(skillRegPath)) {
        return path.toNamespacedPath(skillRegPath);
    }
    // 3. 相对于 agent 根目录
    const agentPath = path.join(_AGENT_DIR, modulePath);
    if (fs.existsSync(agentPath)) {
        return path.toNamespacedPath(agentPath);
    }
    // 4. 相对于 cwd
    const cwdPath = path.resolve(modulePath);
    if (fs.existsSync(cwdPath)) {
        return path.toNamespacedPath(cwdPath);
    }
    // 5. 原样返回（让 Node 尝试解析）
    return modulePath;
}

async function handleRequest(req) {
    const modulePath = req.module_path || "";
    const functionName = req.function_name || "";
    const args = req.arguments || {};

    if (!modulePath || !functionName) {
        return { success: false, error: "module_path 和 function_name 不能为空" };
    }

    try {
        const resolvedPath = resolveModulePath(modulePath);
        const fullPath = path.toNamespacedPath(resolvedPath);
        const moduleUrl = url.pathToFileURL(fullPath).href;

        const module = await import(moduleUrl);
        const func = module[functionName] || module.default?.[functionName];
        if (typeof func !== "function") {
            return { success: false, error: `函数 '${functionName}' 不存在于模块 '${modulePath}'` };
        }

        const result = await Promise.resolve(func(args));
        return { success: true, result };
    } catch (e) {
        return { success: false, error: `${e.constructor?.name || "Error"}: ${e.message}` };
    }
}

async function main() {
    const rl = readline.createInterface({ input: process.stdin });

    const line = await new Promise((resolve) => {
        rl.once("line", resolve);
    });

    if (!line || !line.trim()) {
        process.stdout.write(JSON.stringify({ success: false, error: "空输入" }) + "\n");
        return;
    }

    let req;
    try {
        req = JSON.parse(line.trim());
    } catch (e) {
        process.stdout.write(JSON.stringify({ success: false, error: `JSON 解析失败: ${e.message}` }) + "\n");
        return;
    }

    const resp = await handleRequest(req);
    process.stdout.write(JSON.stringify(resp) + "\n");
}

main();
