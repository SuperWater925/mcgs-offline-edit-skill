# 共同运行环境

此目录保留Pro格式适配器及通用模板，不再单独注册技能。统一依赖为Windows、PowerShell 7、同位数ACE 16.0/12.0、Python 3.11+和新建所需ADOX.Catalog。没有pip运行依赖，不使用32位PowerShell 5.1/Jet宿主。

主入口、安装和doctor见[统一环境](../../../references/environment-and-tools.md)；JSON规格见[editing.md](editing.md)。兼容入口`run.cmd`、`setup.ps1`继续工作，但使用同一个共用连接层。MCGS_PYTHON、MCGS_PWSH可指定本机现有解释器。

软件发行版本仅用于报告。模板来自McgsPro 3.5.1.6963不构成版本限制；实际不支持项按字段、类和归档布局报错。create/edit仅在全表回读等于预期后返回file_readback_passed；host_validation=pending仍需要原厂检查和相关本机验证。
