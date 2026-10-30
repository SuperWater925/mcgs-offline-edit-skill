# 仓库工作约定

本仓库只维护昆仑通态触摸屏离线编辑的方法、工具、技能及验证资料。Stu 和 Pro 共用运行环境，按实际工程家族和归档结构选择适配器；软件大小版本只记录，不设准入白名单；不加入 PLC 程序开发、整机控制方案或客户工程。

- 先读 `CONTRIBUTING.md` 和对应格式参考，检查当前工作树；保留其他人的未提交修改。
- 文件修改走离线脚本，原厂程序只用于已授权的验证。不得把静态检查、预览或编译缓存作为原厂编译证明。
- 保留未知字节、对象 ID、权限与未列字段；不跳过源 SHA、前指纹、白名单及备份守卫。
- 测试生成物放在仓库外或 `local-artifacts/`，不提交客户资料、运行数据、凭据和厂商程序。
- 维护仓库不意味着同时覆盖本机已安装技能；发布、推送、邀请协作者和修改远程规则按用户授权执行。
- 提交前运行 `python scripts/check_repository.py --update-manifest`、`python scripts/check_repository.py` 和 `pwsh -NoProfile -File scripts/check_powershell.ps1`。有工程格式改动时补充相应回环、差异及原厂验证记录。
- `references/source-provenance.json` 和 `references/validation.json` 保存原始来源及既有验证范围；不能为了让新提交通过而伪改历史结果。当前文件清单由 `scripts/check_repository.py` 生成。
