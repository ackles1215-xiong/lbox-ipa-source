# LBox IPA Source

这是一个自动跟踪开源 iOS IPA 的 LBox / AltStore source，目前包含：

- [iTorrent](https://github.com/XITRIX/iTorrent)
- [Palladium](https://github.com/tfourj/Palladium)

## 添加到 LBox

复制下面的地址：

```text
https://raw.githubusercontent.com/ackles1215-xiong/lbox-ipa-source/main/apps.json
```

然后在 LBox 中打开 **Sources / Repositories → Add Source**，粘贴地址并添加。LBox 会按 bundle id 和版本识别 LiveContainer 中已安装的 App；更新时选择更新现有 App，可保留其用户数据。

## AltStore Classic

现代 AltStore Classic 可使用：

```text
https://raw.githubusercontent.com/ackles1215-xiong/lbox-ipa-source/main/source.json
```

`apps.json` 使用 LBox 能直接解析的扁平版本字段；`source.json` 使用 AltStore 当前的 `versions` 数组结构。

## 自动更新机制

GitHub Actions 每 12 小时运行一次，也可以在 Actions 页面手动运行：

1. 查询两个上游仓库的 GitHub Releases。
2. 只处理最新的非草稿、非预发布 Release。
3. 找到与 App 匹配的 `.ipa` 后下载并直接读取 IPA 内的 `Info.plist`。
4. 从 IPA 获取 bundle id、版本、build 和最低 iOS 版本；从 Release 获取下载地址、文件大小、发布时间和更新说明。
5. 校验两个 JSON 后，仅在内容变化时提交。

若最新稳定 Release 没有直接 IPA、IPA 下载失败、存在多个可疑匹配，或 IPA 元数据无法验证，自动化会保留仓库中上一有效版本，不会把无效数据写入 source。

经常变化的数据都来自 GitHub API 与 IPA；只在 `config/apps.json` 中维护上游仓库、IPA 文件名规则和展示文案。

## 本地验证

```bash
python3 scripts/update_sources.py
python3 -m unittest discover -s tests -v
python3 scripts/validate_sources.py
```

## 说明

本仓库只提供上游官方 GitHub Release IPA 的索引，不重新打包或镜像 App。App 的版权与许可证归各自项目所有。
