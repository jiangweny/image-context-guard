# Contributing

欢迎使用中文或 English 提交 Issue / Pull Request。

先阅读 README 和 docs/DESIGN.md。每次修改围绕一个可复现问题，提供操作系统、Python/Codex 版本、provider 类型和最小步骤。使用人工图片和模拟 JSONL，避免真实会话、密钥或客户材料。

~~~bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python tools/check_release.py
~~~

测试不访问外部 API。网络测试应明确标为手动、需要用户配置并说明费用。历史测试应检查文字、工具关联、顺序和回滚保留；不要删除当前会话或锁检查以获得通过。

PR 应说明问题、变化和实际执行的检查。未运行的平台/供应商验证应明确标记。不提交个人路径、真实日志、运行结果、安装生成的 runtime.json 或虚拟环境。

提交贡献表示你有权提供内容，并愿意按本项目 MIT 许可证分发。
