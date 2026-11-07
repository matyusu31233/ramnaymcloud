RamNaym Cloud 免费容器自动续期（GitHub Actions）
给 RamNaym Cloud 的免费项目用的：免费套餐 24 小时到期，续一次 +24 小时。
脚本自动登录面板 → 读剩余时间 → 不够了就续 → 回读剩余时间确认真的变大才报成功。
续期方式是 2026-11-07 登录 https://www.ramnaymcloud.com/manage/1264 实测确认的：
登录 POST /login（账号+密码），续期就是 GET /free-renew/<项目ID> 这个链接本身
（页面按钮原文 “Renew for 24 hours”），没有单独的 API、没有 CSRF 表单。
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
必须比续期前多出约 24 小时才报成功；没多出来会报 ❌ 续期未生效。
第一次手动跑完，去面板看一眼 Time left 是否真的变大了，双重确认。
注意
密码只放在你自己仓库的 Secrets 里，不要写进代码、不要发聊天。
面板若改版（登录字段、续期链接、Time left 文案变了），脚本会报解析失败，
  到时把报错贴回来按新页面改。
本脚本已在本地用模拟面板实测过三条路径：可续期→续上并回读确认、
  剩余充足→跳过、密码错误→明确报错。真实面板的首跑结果以你的
  第一次 Actions 运行 + 面板 Time left 为准。
