// 测试用 Node.js skill 模块 — 被 skill_runner.js 调用。
// runner 传入整个 arguments 字典作为单个参数。

export function echo(args) {
    return `NodeJS echo: ${args.text}`;
}

export function add(args) {
    return args.a + args.b;
}
