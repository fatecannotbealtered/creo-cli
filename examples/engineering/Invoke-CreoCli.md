# 用PowerShell调用公开CLI

本helper面向已完成自有会话启动和身份核对的agent。运行时只需要随包EXE和PowerShell7.4以上版本，无需另装Python。开发测试使用Python，不属于工程师运行依赖。

先dot-source，再声明本次EXE、证据目录和环境。`CREO_CLI_CONFIG_DIR`必须指向已存在的持续历史目录。helper不会创建或替换历史，也不会改变权限、选择其他Creo实例或处理信任提示。

```powershell
. ./Invoke-CreoCli.ps1
$run = New-CreoCliRun -ExecutablePath 'D:/package/cli/creo-cli.exe' `
    -EvidenceDirectory 'D:/owned-run/evidence' -Environment $declaredEnvironment `
    -TimeoutSeconds 360

$read = Invoke-CreoCli -Run $run -Label '001-model' `
    -Arguments @('model', 'show', '--model', 'MiXeD_Frame.prt', '--timeout', '300')

$saved = Invoke-CreoCliWrite -Run $run -Label '002-save' `
    -Arguments @('model', 'save', '--model', 'MiXeD_Frame.prt', '--timeout', '300') `
    -Review { param($preview); $preview.data.preview.can_apply -eq $true }
```

`$declaredEnvironment`是调用者明确声明的hashtable。至少要含持续历史目录及精确的自有`http://127.0.0.1:port`端点；按Skill另行声明workspace、scope、token文件和权限。子进程清除继承的`CREO_CLI_*`、`PYTHONPATH`、`PYTHONHOME`和`PYTHONUSERBASE`，再设置这个map。Windows基础环境仍保留。

参数通过`.NET ProcessStartInfo.ArgumentList.Add`逐项传递。中文、空格、模型名大小写、引号、反引号及美元符不会被拼成PowerShell命令。helper追加`--json --compact`，其他业务参数保持不变。

模型标识仍须遵守公开reference的命名规则。helper对中文参数的传递测试不代表CLI支持中文模型标识。中文路径和文本按UTF-8处理；模型名的规范格式由CLI解析。

## 已执行的UTF-8输出路径

C10-H1的完整EXE、JAR和DLL已在自有留出工程中执行以下公开命令序列。前提是完成自有会话身份核对、当前目标的原生activate、normal状态和FRONT-derived isometric fit，并在scope中明确包含输出目录与本次`.creo-cli/staging`。准确构件及证据由当前交接 (private historical record)选择。

```powershell
# $run沿用上文已核验的自有会话；目录须换成新的、已授权的自有输出目录。
$taskOutputPath = Join-Path $ownedImageDirectory '共享源-蓝黄.jpg'
[string[]]$taskRenderArgs = @(
    'artifact', 'render', '--model', 'r38_h_review.asm', '--view', 'current',
    '--width', '1600', '--height', '1000', '--output', $taskOutputPath,
    '--timeout', '300'
)
$taskImage = Invoke-CreoCliWrite -Run $run -Label 'fresh-shared-color-image' `
    -Arguments $taskRenderArgs `
    -Review { param($preview); $preview.data.preview.can_apply -eq $true }
```

该次实际运行标签为`H1-H218-render-blue-yellow-UTF8`，preview与confirm的output字符串完全相同，得到1600×1000 JPEG，33534字节，SHA-256为`1f47ae9aba51ecd508f4aa5a0e21e505082745120c08d46916250a4000ab0e1b`。6项原生检查通过，Root实际查看了原图：两件蓝jaw、黄pad与灰pin可辨，完整轮廓无裁切。不要复用其旧确认、label或已存在输出文件。

这只证明实际产品的UTF-8输出路径。Native模型仍使用ASCII标识。组件列表中的`R38_H_JAW.prt`与`model show`中的`r38_h_jaw.prt`，只有在类型、准确origin和保存文件摘要对应后才视为同一源；不能据此对外观ID、显示名称或其他引用统一忽略大小写。未执行中文Creo模型标识测试。

## 时限、原件与停止

`TimeoutSeconds`是外层进程及输出收集的总时限。CLI的原生budget由业务参数`--timeout`另行声明；上例给CLI300秒，外层留360秒。不应把CLI时限设得比外层总时限更长。

每次label必须唯一。helper保留原始UTF-8 stdout、stderr和metadata，文件分别以`.stdout.json`、`.stderr.log`和`.metadata.json`结尾。写入会先运行`label-preview`；只有`can_apply`为布尔true、本次token存在且Review只返回一个布尔true时，才同参数确认一次为`label-confirm`。Review省略时仍检查`can_apply`和token。metadata中的确认token被脱敏；原preview保留本地原件，因此证据目录应由调用者妥善保管，不能直接公开。

非零退出、`ok=false`、非法JSON或Review拒绝都会停止本run，不自动重放。超时不会杀CLI或CAD；`$run.PendingInvocations`保留进程和仍在收集的流。保持PowerShell主机运行，保留pending记录，不再发送CAD调用。即使原CLI退出，若输出管道尚未关闭，也按pending处理。

这时唯一内建的查看接口只运行本地`operation show`：

```powershell
$local = Get-CreoCliLocalOperation -Run $run -Label '003-local-status' `
    -OperationId $retainedOperationId
```

不要用`operation query`、`doctor`或新的CAD读取探测原调用是否结束。本helper没有自动解除停止、自动保存、回滚、重试或杀进程功能。
