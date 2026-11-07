RamNaym Cloud 免费容器自动续期（GitHub Actions）
给 RamNaym Cloud 的免费项目用的：免费套餐 24 小时到期，续期走一遍广告页后
把过期时间重置为约 24 小时。脚本自动登录面板 → 读剩余时间 → 不够了就走
完整续期流程 → 回读剩余时间确认回到约 24 小时才报成功。
真实流程是 2026-11-07 登录实测走通一遍确认的（续前 22h46m → 续后 23h59m）：
登录 POST /login 有两个坑：表单带隐藏字段 csrf_token，且 POST 必须带
   Referer/Origin 头，缺任何一个都会报 “Your security session expired”，
   看起来像密码错误。
GET /free-renew/<项目ID> 本身不续期，它跳到广告商 blitz-ly.com，
   跳转地址的 url= 参数里带着一次性完成地址 /free-renew/complete/<令牌>。
等约 25 秒（广告页倒计时 20 秒），再带会话 GET 那个 complete 地址，
   才真正续期。落地页没有任何成功提示，只能看倒计时变化。
续期是【重置】不是叠加：完成后剩余回到约 23h59m，管理页写的
   “adds 24 hours” 和广告页写的 “8 more hours” 都与实测不符，以数字为准。
文件
renew.py — 续期脚本，只用 Python 标准库，无第三方依赖
renew.yml — GitHub Actions 工作流（放 .github/workflows/renew.yml）
部署步骤
新建一个 GitHub 仓库（建议 Private），把 renew.py 放仓库根目录，
   renew.yml 放 .github/workflows/renew.yml。
仓库 Settings → Secrets and variables → Actions，加 Secrets：
RAMNAYM_USERNAME（必填）：面板账号名
RAMNAYM_PASSWORD（必填）：面板密码
RAMNAYM_PROJECT_ID（选填）：项目 ID，默认 1264，不填就是 1264
TG_BOT_TOKEN / TG_CHAT_ID（选填）：要 Telegram 汇报才填
Actions 页面手动跑一次 workflow 验证（见下面“怎么算真续上”）。
运行节奏
workflow 每 6 小时跑一次；脚本里有阈值：剩余 >12 小时就跳过、不续，
  剩余 ≤12 小时才续 +24h。所以实际约每天续一次，某一次跑失败了，
  6 小时后还有下一次机会，不会直接过期。
想改阈值：在 renew.py 的运行环境里加变量 RENEW_BELOW_HOURS（小时数）。
怎么算真续上（重要）
脚本报 ✅ 不算数，以回读为准：续期后脚本会重新打开管理页读 “Time left”，
必须回到约 24 小时（≥23 小时且大于续前值）才报成功；没回去会报 ❌ 续期未生效。
第一次手动跑完，去面板看一眼 Time left 是否真的回到 23h59m 左右，双重确认。
如果日志里出现“没解析到 Time left”并附带原始页面片段，把那段全文贴回来，
那是按真实页面结构修解析用的证据。
注意
密码只放在你自己仓库的 Secrets 里，不要写进代码、不要发聊天。
面板若改版（登录字段、续期链接、Time left 文案变了），脚本会报解析失败，
  到时把报错贴回来按新页面改。
本脚本已在本地用模拟面板实测过三条路径：可续期→续上并回读确认、
  剩余充足→跳过、密码错误→明确报错。真实面板的首跑结果以你的
  第一次 Actions 运行 + 面板 Time left 为准。
