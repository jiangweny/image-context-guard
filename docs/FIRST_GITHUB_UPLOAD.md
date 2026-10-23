# 第一次把项目上传到 GitHub

此目录就是仓库内容，推荐仓库名 image-context-guard。第一次只做源码发布即可，不需要发布到 PyPI 或申请软件商店。

## 1. 发布前检查

- 阅读 README.md，确认实验版状态和范围符合你的意愿。
- LICENSE 默认使用 MIT，署名为 Image Context Guard contributors；首次发布前可改成你希望公开的名字或网名。
- 运行 python -m unittest discover -s tests -v 和 python tools/check_release.py。
- 不上传真实会话、API key、auth.json、私有配置、备份或任务图片。发布图片包括人工数字测试图 examples/demo.png 和项目封面 封面.jpg；封面须与 README 一起上传并保留文件名。
- .gitignore 只影响 Git 提交，不会替网页上传过滤文件；仍需检查文件列表。

## 2. 在 GitHub 创建空仓库

登录 GitHub，选择 New repository：

1. Repository name 填 image-context-guard。
2. Description 可填：Keep image-heavy agent conversations focused with isolated vision requests, text caching, and recoverable history cleanup.
3. Visibility 选择 Public，表示公开。
4. 不勾选自动添加 README、.gitignore 或许可证，目录中已有这些文件。
5. 创建仓库，保留网页显示的 HTTPS 地址。

## 3. 推荐用终端上传

如果当前目录位于其他 Git 仓库里，先把完整目录复制到一个独立位置，再用 VS Code 打开复制后的目录。不要在父项目执行 git add .。

在 image-context-guard 目录终端依次执行：

~~~bash
git init -b main
git status --short
git add .
git diff --cached --stat
git diff --cached --check
git commit -m "Initial experimental release"
~~~

如果 Git 提示没有提交者信息，在此仓库设置希望公开的名字和 GitHub 私密提交邮箱，然后重新提交：

~~~bash
git config user.name "你的公开名字或网名"
git config user.email "从 GitHub 邮箱设置复制的 noreply 地址"
git commit -m "Initial experimental release"
~~~

不要直接复制中文占位值。noreply 地址可在 GitHub Settings → Emails 中找到。

把下面 YOUR_GITHUB_USERNAME 换成你的 GitHub 用户名；仓库名不同也相应替换：

~~~bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/image-context-guard.git
git push -u origin main
~~~

按 Git/VS Code 提示登录。不要把 token 写进 remote URL、源码或 README。如果 origin 已存在，先 git remote -v 核对，避免推到错误仓库。

上传后检查首页 README 和 Actions 测试结果。首次 GitHub CI 尚未执行，不能提前宣称各系统测试通过。

## 4. 不想使用 Git 时

可在空仓库网页选择 uploading an existing file 或 Add file → Upload files，上传目录内容并提交。保留层级，确保 .github、.gitignore、.gitattributes 等隐藏项也被选中。终端方式更容易完整保留这些文件。

## 5. 可选：创建第一个版本

上传成功后进入 Releases → Draft a new release：标签 v0.1.0，标题 v0.1.0 — Experimental，勾选预发布选项。填写实际测试结果，说明真实 API 验证是否仍未完成。

GitHub 可根据标签提供源码归档，无需先上传自己的压缩包。

以后修改后运行测试，再 git add、git commit、git push。用户可通过 Issue 报告问题，通过 Pull Request 提交修改。

本教程没有创建远程仓库或替你发布。执行推送时才会把本地内容上传。
