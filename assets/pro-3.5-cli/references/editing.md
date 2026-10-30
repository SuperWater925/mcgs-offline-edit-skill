# JSON工程规格

## 新建

完整可执行示例见`examples/create.json`。create从随包通用空白数据新建数据库，逐项写入真实工程内容，不启动编辑器。

顶层只接受variables和pages。variables每项接受name、type、initial、note、unit；type为boolean、number或string。数值初值须为有限数值，布尔初值为0或1；字符串直接填写文本。变量ID由工具按工程顺序分配，不由调用方猜测。

pages每项接受name和controls。名称1～32字符，页名唯一；每页控件名唯一。第一项作为启动页。800×480目标模板沿用随包默认型号；更换机型、分辨率或协议配置不属于此模板参数。

控件字段：

| type | 可用字段 |
| --- | --- |
| label | name、bounds、text |
| line | name、bounds |
| rectangle | name、bounds |
| numeric-input | name、bounds、binding、minimum、maximum |

bounds为`[左,上,右,下]`四整数。右大于左、下大于上；请把控件放在画面尺寸内。水平/垂直线使用至少1像素的外接矩形。binding必须为工程中已有布尔/数值变量名，工具同时写入真实ID与名称；不接受未知变量或字符串绑定。数值上下限按minimum≤maximum校验。

## 修改

先inspect原工程。修改规格示例：

```json
{
  "source_sha256": "原工程实际SHA256",
  "add_variables": [{"name":"新设定值","type":"number","initial":"10"}],
  "variables": [{"name":"原有变量名","initial":"35","note":"新注释"}],
  "pages": [{
    "id": 1,
    "controls": [{
      "name":"原标题控件名",
      "sha256":"inspect返回的该控件SHA256",
      "edits":{"text":"新标题","bounds":[30,20,700,70]}
    }],
    "add_controls":[{"type":"numeric-input","name":"新增输入","bounds":[250,100,450,150],"binding":"新设定值","minimum":0,"maximum":100}]
  }]
}
```

从实际inspect结果填写ID、名称与SHA，不使用上述示意值。文字支持变长/变短及中文，控件记录长度会自动更新。edits可修改名称和bounds；静态标签可改text；数值输入可改binding和上下限。暂不提供变量重命名、删除、窗口重命名、任意未知属性或脚本编辑。

原有变量的初值、note、unit可更新；新增变量通过add_variables。修改已有工程时不替换其他页面、设备、权限、策略或未知控件内容；文件级全表回读会检测意外改动。实际不支持的变量布局或控件归档分支报告具体缺口；不按软件发行版本拦截。

## 编写需求时

先建立画面、变量和绑定清单，按实际支持范围生成JSON。对未实现项清楚列出缺口，不写空脚本或假地址，不把可编辑工程误说成已满足全部业务需求。修改前后分别保留摘要；用户原工程不被覆盖。
