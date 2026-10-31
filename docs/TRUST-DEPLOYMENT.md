# 正式签名组件的自有会话部署

本指南面向安装工程师及agent。Windows文件签名、PTC许可解锁、Creo加载策略和组件实际加载是四个不同检查。只有最后的完整EXE/JAR/DLL原生验收能证明完整启动通过。

## 与内部未签名试用的区别

本页保留正式签名路线。C6本次选择独立、非默认的[内部未签名试用](INTERNAL-UNSIGNED-TRIAL.md)，使用重新构建、普通`-c`解锁的DLL和经明确授权的新自有会话策略，不再以等待外部签名作为本轮前置。内部模式仍如实报告NotSigned，不调用本页的签名通过结论，也不能加载尚未签名的`-cd`准备件。

正式`inherit`和`signed-only`路线继续要求真实签名、发布者pin及有效策略，检查没有删除。内部准确13.4.1.0配置只写unsigned Always，记录signed关键字不受支持；它不声明signed默认值或正式路线已通过，见[启动配置](STARTUP-NATIVE.md#本机13410有限配置)。工程师不能从本任务批准推导自己电脑的策略授权。签名或组件ready也不证明没有恢复弹窗；每次新进程仍须按[启动指南](STARTUP-NATIVE.md#每个进程独立的恢复数据)隔离workflow和会话恢复数据，保留记录，并核验实际配置与可见弹窗。

## C4/C5签名记录与保留待办

C4产品源码是`27a130c1841d2281c0c6ee6db31fe010743fe83f`，接手文档提交是`5749c4cbfabe8cb2540898517430350af962816a`。它们不能混用。原C4 EXE和R5 DLL的Authenticode状态为NotSigned。JAR不适用Authenticode检查；合法`-java`解锁加入了PTC的Java签名。

C5交付时观察到宿主的CurrentUser/My和LocalMachine/My中没有代码签名证书。Windows SDK的SignTool已安装。缺的是有权使用的企业或CA代码签名证书及签名服务，并非缺一个“允许”按钮。不得生成自签证书再自行加入受信根，也不得接受来源提示来补验收。

JDK25.0.3对C4 JAR的严格检查返回4：内容签名可校验，但PTC签名证书是自签链，JDK默认信任链不成立，并有旧算法及无时间戳警告。这不等于JAR没有PTC签名，也不等于它已通过企业Java信任部署。不要修改JDK安全算法或导入该证书来隐藏警告。PTC说明解锁会加入自身签名，也允许标准jarsigner；实际Creo加载、Java版本和许可仍须另验。[PTC Java解锁与签名](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r13/usascii/creo_toolkit/user_guide/Unlocking_Running_and_Signing_the_Creo_Object_TOOLKIT_Java_Application.html)。

## 一次性部署准备

1. 提供有权使用的发布者代码签名服务，或由企业签名操作者指定真实证书thumbprint及时间戳服务。私钥留在受控存储或HSM，不交给agent，不在参数或日志中提供密码。
2. 在新目录编译DLL，再用本机合法PTC工具`protk_unlock -cd`准备签名。`-c`解锁成功不产生Windows Authenticode签名。`-cd`准备后仍必须由合法签名方签名，不能把待签名文件加载进Creo。不要修改C4或已解锁旧包。[PTC原生应用解锁](https://support.ptc.com/help/creo_toolkit/protoolkit_pma/r13/usascii/creo_toolkit/user_guide/Unlocking_a_Creo_Toolkit_Application.html)。
3. 只有在用户批准具体发布者和范围后，由有权的签名操作者对新`signing-input`副本执行签名。以下是命令格式，不是已执行记录；`/sha1`选择证书thumbprint，文件签名摘要仍为SHA256。

```text
signtool sign /s My /sha1 <APPROVED_SIGNER_THUMBPRINT> /fd SHA256 /tr <APPROVED_RFC3161_TSA_URL> /td SHA256 <OWNED_SIGNING_INPUT_DLL>
```

4. 用Windows Authenticode及`signtool verify /pa /all /v`核对签名链、明确发布者和时间戳。保留未签输入，核对签名返回的全部原始PE及PTC解锁字节；只允许校验和、证书目录和新增签名表的规定变化。重新绑定签后完整文件SHA，不预测它。[Microsoft签名操作](https://learn.microsoft.com/en-us/windows/win32/seccrypto/using-signtool-to-sign-a-file)、[SignTool验证](https://learn.microsoft.com/en-us/windows/win32/seccrypto/using-signtool-to-verify-a-file-signature)。
5. 先核查有效Creo策略。PTC公开`open_protk_signed_apps`和`open_protk_unsigned_apps`的Always、Never、Prompt三值。未找到公开的每DLL或每证书白名单；不能把类别策略描述成单文件授权。若有效signed策略为Prompt，合法签名本身也不保证无提示；不依赖未经验证的“记住选择”缓存。[PTC加载签名检查](https://support.ptc.com/help/creo_toolkit/protoolkit_pma/r13/usascii/creo_toolkit/user_guide/Digitally_Signing_the_Application.html)。

## 需要明确批准的会话配置

可提议的配置仅写入本任务新建且明确声明的startup目录，示意内容如下。批准前不得把它写成生效`config.pro`，也不修改安装目录、用户home、系统信任库或已有实例。

```text
open_protk_signed_apps always
open_protk_unsigned_apps never
```

影响是该自有Creo会话对**所有签名TOOLKIT应用类别**采用Always，并拒绝未签名类别；它不是只允许creo-cli或某证书。自有注册文件应仅列已绑定组件，并在启动前核对全部组件SHA及授权发布者。其他进程不因这个局部文件而改变策略。

PTC在启动时最后读取startup目录配置，但受管理员`config.sup`锁定的设置不能由局部`config.pro`覆盖。发现锁定或冲突就停止并交管理员处理；不换路径规避。本机r13官方配置说明最后一段与前面的锁定说明存在冲突，本指南按明确的锁定规则保守处理。[PTC配置读取顺序](https://support.ptc.com/help/creo/creo_pma/r13/usascii/fundamentals/fundamentals/About_Configuration_Files.html)。unsigned的官方默认值为Prompt；r13公开配置列表没有列出signed默认值，本指南不猜测它。[r13配置选项](https://support.ptc.com/help/creo/creo_pma/r13/usascii/configuration_options/creo_parametric_toolkit_configuration_options.html)。

## 每次启动与版本变化

每次启动都核对已批准发布者、签名状态、签后EXE/JAR/DLL与manifest的完整SHA、许可和合法Java路径，保留`delay_start false`。启动新自有进程后独立检查JAR来源、DLL加载模块及握手、WSession能力，不能以文件签名代替加载身份。最后正常退出，再从同一冻结部署冷启动一次，重复完整加载检查。

编译、PTC解锁、签名或时间戳都会形成不同字节。任何构件变化都要重新签名或验证相应签名，重新生成SHA和完整绑定。证书续期或轮换要核对新的真实发布者thumbprint及授权；同一签名类别策略仍不能授予未审阅新代码资格。JAR变更重新解锁，不能在解锁后随意改类或资源。Creo、Java、管理员策略或证书链变化均需重新验证，不承诺跨版本自动信任。

## 开发准备与只读验签脚本

以下脚本是开发和部署工具，需要开发Python及SDK；最终工程师的EXE客户端不因此增加Python依赖。它不签名、不导入证书、不写加载策略，也不启动或连接Creo。

```powershell
python scripts/prepare_native_signing.py prepare --creo '<LEGAL_CREO_ROOT>' --output '<NEW_OWNED_DIRECTORY>'
python scripts/prepare_native_signing.py verify --preparation '<PREPARATION_JSON>' --signed-dll '<RETURNED_SIGNED_DLL>' --expected-signer '<APPROVED_SIGNER_THUMBPRINT>' --signtool '<WINDOWS_SDK_SIGNTOOL>' --report '<NEW_VERIFICATION_JSON>'
```

prepare保留未签原件和独立签名输入，记录`pending_authorized_external_authenticode_signing`。verify只在发布者、Windows Valid、时间戳、SignTool和完整预签字节保护全部满足时声明`authenticode_verified=true`，仍保持`creo_load_trust_verified=false`。`-cd`可能按PTC规定占用开发许可15分钟；不能把它写成不使用许可的普通复制操作。

## 启动前检查与实际策略读回

`start-owned-creo.ps1`默认`-TrustPolicy inherit`，不写加载策略。正式签名路线在启动前要求真实DLL为Windows Valid Authenticode，并与`-ExpectedNativeSignerThumbprint`明确发布者匹配。继承路线还须从声明的配置来源证明signed为Always；未知默认值不能当作已满足。

`-TrustPolicy signed-only`只有在调用者已获得上述范围授权时使用。它先检查发布者和受保护配置，再仅在新自有startup写入两行策略。`-LoginConfigurationDirectory`可明确声明登录配置目录；未指定时记录当前用户目录。安装、登录及声明备用路径只读选定的两项配置和文件hash，其他内容不写入报告。受保护值冲突或不可确认均拒绝。

加`-PreflightOnly`仅作文件检查，不创建startup/runtime，也不启动Creo。每次检查在startup路径旁写独立`.preflight-<id>.json`，失败为`status=not_started`及明确原因，不覆盖旧结果。未签C4原件已实际按此路线拒绝，未再启动来源提示进程。

正常正式签名路线启动仍只做原有一次认证`/session`就绪读回。它必须同时返回原生实际`deployment_policy`两项及完整性：signed为Always，signed-only路线的unsigned为Never；inherit路线核对实际unsigned与预检观察一致。不符则该代次未通过，不再发CAD调用或自动重试。时间戳是否存在单独报告，实际签名信任依Windows验证状态，不能只凭TimeStamper字段判断。
