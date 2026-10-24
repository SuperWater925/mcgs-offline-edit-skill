# 安装和运行

## 软件与依赖

接收电脑需要Windows x64或x86、已安装的Python 3.11或更新版本，以及用于最终验证的McgsPro 3.5.1.6963。文件写入使用Windows自带的32位Windows PowerShell 5.1、ADOX和Microsoft.Jet.OLEDB.4.0数据库组件；脚本会选32位进程，与Python自身位数无关。

无需pip包、pywinauto、psutil、Access安装或MCP服务器。requirements.txt记录这些要求，不需要执行pip install。安装检查会真实创建临时数据库、写入二进制字段并回读，然后清理临时文件；缺失组件时应报告错误，不能跳过检查。Python和原厂软件由接收方预先安装；本包不是它们的安装介质。

解压整个mcgs-offline-engineering目录到`%USERPROFILE%\.codex\skills\`。可直接在Windows终端使用，也可通过Codex调用`$mcgs-offline-engineering`。

## 开始使用

在skill目录执行：

```bat
run.cmd doctor
run.cmd create --spec examples\create.json --output C:\Work\示例.mcp
run.cmd inspect C:\Work\示例.mcp
```

也可一条命令实跑完整的新建与修改示例（Demo目录必须不存在，父目录必须存在）：

```bat
run.cmd demo --directory C:\Work\Demo
```

它会生成demo.mcp、实际SHA对应的edit.json、demo-edited.mcp和results.json。两份工程均由文件脚本直接写出，不启动编辑器；接收方再用原厂软件验证demo-edited.mcp。

输出目录必须已存在，目标MCP必须不存在。run.cmd优先使用MCGS_PYTHON指定的解释器，再使用PATH中的python，最后使用Windows的py启动器。也可直接使用绝对路径：

```bat
python -X utf8 scripts\mcgs_file.py doctor
python -X utf8 scripts\mcgs_file.py create --spec examples\create.json --output C:\Work\示例.mcp
```

Python已安装但没有加入PATH时，在PowerShell中指定现有解释器即可，无需重新安装：

```powershell
$env:MCGS_PYTHON = 'C:/实际安装路径/python.exe'
./run.cmd doctor
```

也可在Codex终端通过`Get-Command python`定位解释器，或直接用其绝对路径调用scripts/mcgs_file.py。不要因为失效的py启动器就误判已安装的Python不可用。

setup.ps1是相同环境检查的可选入口，不安装全局依赖，不修改执行策略。Windows策略限制ps1时直接使用run.cmd或Python入口。本包以数据输入调用Windows数据库组件，不需要执行外部下载脚本。

## 修改工程

先inspect获得源SHA、页面ID、控件名称及SHA，按editing.md生成编辑规格，然后执行：

```bat
run.cmd edit --source C:\Work\原工程.mcp --spec C:\Work\edit.json --output C:\Work\修改工程.mcp
run.cmd inspect C:\Work\修改工程.mcp
```

规范JSON必须为UTF-8；路径带空格时加双引号。所有脚本从自身目录加载assets，不依赖当前工作目录或作者机器路径。

## 返回值

成功退出码0，错误退出码1，stdout返回JSON。create/edit仅在写入后全表回读符合预期时返回`file_readback_passed`；`host_validation=pending`要求接收方另做原厂验证。

doctor通过意味着本机具备实际数据库创建/二进制读写能力，不证明原厂软件已安装或工程编译通过。依赖缺失、未知版本、原件变化、输出已存在及对象不唯一都会拒绝。发生异常后不要将失败候选当成果使用；检查输出回执和文件状态，再用新输出路径执行修正后的规格，不能循环重试同一失败。
