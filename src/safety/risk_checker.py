"""风险检测。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.auditor.schema import AuditResult, RiskLevel


DANGER_KEYWORDS = [
    r"\brm\b",
    r"\bsudo\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bdrop\b",
    r"\bdelete\b",
    r"\btruncate\b",
    r"\bupdate\b",
    r"reset\s*--hard",
    r"prisma\s+migrate\s+reset",
    r"git\s+clean\s+-[A-Za-z]*[fxd]+",
    r"git\s+push\s+--force",
    r"\bclean\b",
    r"\bprune\b",
    r"\bforce\b",
    r"\boverwrite\b",
    r"\bformat\b",
    r"\bremove\b",
    r"\bdel\b",
    r"rd\s*/s",
    r"rm\s+-rf",
    r"Remove-Item\s+.*(-Recurse|-Force)",
    r"rmdir\s+/s",
    r"\bdel\s+/s\b",
    r"数据库删除",
    r"数据库清空",
    r"清空数据库",
    r"本地数据库.{0,12}(清空|重置|reset)",
    r"(users|user|用户|账号|账户).{0,16}(role|角色|权限).{0,16}(admin|管理员)",
    r"(role|角色|权限).{0,16}(改成|设成|更新为|变成).{0,16}(admin|管理员)",
    r"清表",
    r"(订单表|用户表|数据表|表).{0,12}(删干净|删除|清掉|清空)",
    r"(权限表|角色表|权限数据|角色数据).{0,12}(清空|删除|删掉|删干净|批量删除)",
    r"(清空|删除|删掉|删干净|批量删除).{0,12}(权限表|角色表|权限数据|角色数据)",
    r"生产库",
    r"生产数据库",
    r"覆盖文件",
    r"覆盖\s*config\.ya?ml",
    r"覆盖.{0,12}(配置|配置文件|yaml|yml|json)",
    r"删除目录",
    r"node\s*modules",
    r"删了",
    r"删掉",
    r"重新装",
    r"npm\s+install",
    r"pip\s+install\s+--force",
    r"停药",
    r"(这个药|降压药|药|布洛芬|感冒药|退烧药).{0,16}(能不能停|怎么吃|剂量|吃两片|要不要加|能不能吃|一起吃|加量|吃多少)",
    r"(孩子|小孩|儿童|孕妇|老人).{0,20}(发烧|高烧|退烧药|吃多少|剂量|急诊|要不要去|需不需要去)",
    r"(发烧|高烧).{0,20}(退烧药|吃多少|剂量|急诊|要不要去|需不需要去)",
    r"(降压药|药|布洛芬|感冒药|退烧药).{0,24}(漏吃|补两片|补服|多吃|少吃|剂量|加量|减量|要不要加|能不能补|一起吃|吃多少)",
    r"(漏吃|补两片|补服|多吃|少吃|剂量|加量|减量|要不要加|能不能补|一起吃|吃多少).{0,24}(降压药|药|布洛芬|感冒药|退烧药)",
    r"(误服|误吃|吃错|吃多了|过量|超量|重复吃|吃了两次|吃了三次|补服|多吃).{0,24}(药|退烧药|降压药|布洛芬|感冒药|止痛药|抗生素)",
    r"(药|退烧药|降压药|布洛芬|感冒药|止痛药|抗生素).{0,24}(误服|误吃|吃错|吃多了|过量|超量|重复吃|吃了两次|吃了三次|补服|多吃)",
    r"(胸口疼|胸闷|心梗|报告).{0,16}(判断|诊断|是不是|吃什么药|医疗建议|急诊)",
    r"(胸痛|胸口痛|胸口疼|胸闷|冒冷汗|呼吸困难|意识不清|抽搐|中风|心梗|打\s*120).{0,24}(是不是|要不要|该不该|判断|诊断|用药|吃什么药|急诊|120|打\s*120)",
    r"(我妈|我爸|妈妈|爸爸|老人|患者|病人).{0,24}(胸痛|胸口痛|胸口疼|冒冷汗|呼吸困难|意识不清|抽搐|中风|心梗|打\s*120)",
    r"(检查报告|化验单|报告).{0,24}(肿瘤|癌|心梗|糖尿病|判断|诊断|是不是|用药)",
    r"(患者|病人|症状|急诊|复查|孩子|小孩|儿童|孕妇|老人).{0,16}(判断|诊断|是不是|要不要|医疗建议|剂量|吃多少)",
    r"(判断|诊断).{0,16}(患者|病人|症状|急诊|复查)",
    r"买哪只股票",
    r"推荐买",
    r"直接给买卖建议",
    r"(基金|股票|ETF|房贷|贷款|USDT|稳定币|钱包|链上地址).{0,24}(能买吗|买入|卖出|适合买|仓位|加仓|提前还|还房贷|直接给建议|转到|转账|直接操作)",
    r"(仓位|加仓|买入|卖出|提前还|还房贷|转账|转到|直接操作).{0,24}(基金|股票|ETF|币|房贷|贷款|USDT|稳定币|钱包|链上地址)",
    r"(币|合约|杠杆).{0,16}(十倍|10倍|开仓|合约|杠杆)",
    r"(USDT|稳定币|币|钱包|链上地址).{0,24}(手续费|地址|转账|转到|直接操作)",
    r"(交易|转账|资金|订单|支付).{0,16}(放行|操作|处理|打款|退款)",
    r"(放行|操作|处理|打款|退款).{0,16}(交易|转账|资金|订单|支付)",
    r"(交易|转账|资金|订单|支付|提现|提款|出款|充值|扣款|退款单|退款).{0,24}(直接)?(放行|通过|操作|处理|打款|退款|原路退回|绕过|跳过|不用审核|不要走审核|别走审核|别走人工复核|不用人工复核)",
    r"(放行|通过|操作|处理|打款|退款|原路退回|绕过|跳过|不用审核|不要走审核|别走审核|别走人工复核|不用人工复核).{0,24}(交易|转账|资金|订单|支付|提现|提款|出款|充值|扣款|退款单|退款)",
    r"(身份证|手机号|手机号码|病历|用户数据|客户数据|隐私数据).{0,16}(导出|发给|发送|复制|泄露|公开)",
    r"(身份证|手机号|手机号码|病历|银行卡号|用户数据|客户数据|隐私数据|姓名|邮箱|邮件|地址|收货地址|订单明细|就诊记录|检查报告).{0,20}(导出|发给|发送|复制|泄露|公开|打包|压缩|上传|截图|发群|发到群|给供应商|给第三方|给销售|给外包)",
    r"(API\s*key|api\s*key|密钥|token|访问令牌|secret).{0,16}(写到日志|打印|发给|发送|公开|提交|泄露)",
    r"(OPENAI_API_KEY|API_KEY|DATABASE_URL|数据库密码|password|passwd|cookie|access\s*token|refresh\s*token).{0,16}(贴到日志|写到日志|打印|发给|发送|公开|提交|泄露|控制台)",
    r"(导出|发给|发送|复制).{0,16}(身份证|手机号|手机号码|病历|用户数据|客户数据|隐私数据)",
    r"(导出|发给|发送|复制|打包|压缩|上传|截图|发群|发到群|给供应商|给第三方|给销售|给外包).{0,20}(身份证|手机号|手机号码|病历|银行卡号|用户数据|客户数据|隐私数据|姓名|邮箱|邮件|地址|收货地址|订单明细|就诊记录|检查报告)",
    r"(写到日志|打印|发给|发送|公开|提交).{0,16}(API\s*key|api\s*key|密钥|token|访问令牌|secret)",
    r"(贴到日志|写到日志|打印|发给|发送|公开|提交|控制台).{0,16}(OPENAI_API_KEY|API_KEY|DATABASE_URL|数据库密码|password|passwd|cookie|access\s*token|refresh\s*token)",
]

HIGH_RISK_PATTERNS = [
    r"数据库删除",
    r"数据库清空",
    r"清空数据库",
    r"prisma\s+migrate\s+reset",
    r"本地数据库.{0,12}(清空|重置|reset)",
    r"(users|user|用户|账号|账户).{0,16}(role|角色|权限).{0,16}(admin|管理员)",
    r"(role|角色|权限).{0,16}(改成|设成|更新为|变成).{0,16}(admin|管理员)",
    r"生产库",
    r"生产数据库",
    r"清表",
    r"(订单表|用户表|数据表|表).{0,12}(删干净|删除|清掉|清空)",
    r"(权限表|角色表|权限数据|角色数据).{0,12}(清空|删除|删掉|删干净|批量删除)",
    r"(清空|删除|删掉|删干净|批量删除).{0,12}(权限表|角色表|权限数据|角色数据)",
    r"\bdelete\s+from\b",
    r"\bdrop\s+table\b",
    r"\btruncate\b",
    r"rm\s+-rf",
    r"Remove-Item\s+.*(-Recurse|-Force)",
    r"rmdir\s+/s",
    r"\bdel\s+/s\b",
    r"reset\s*--hard",
    r"git\s+clean\s+-[A-Za-z]*[fxd]+",
    r"git\s+push\s+--force",
    r"rd\s*/s",
    r"删除目录",
    r"覆盖文件",
    r"覆盖\s*config\.ya?ml",
    r"覆盖.{0,12}(配置|配置文件|yaml|yml|json)",
    r"\bmkfs\b",
    r"\bformat\b",
    r"(API\s*key|api\s*key|密钥|token|访问令牌|secret).{0,16}(写到日志|打印|发给|发送|公开|提交|泄露)",
    r"(写到日志|打印|发给|发送|公开|提交).{0,16}(API\s*key|api\s*key|密钥|token|访问令牌|secret)",
    r"(OPENAI_API_KEY|API_KEY|DATABASE_URL|数据库密码|password|passwd|cookie|access\s*token|refresh\s*token).{0,16}(贴到日志|写到日志|打印|发给|发送|公开|提交|泄露|控制台)",
    r"(贴到日志|写到日志|打印|发给|发送|公开|提交|控制台).{0,16}(OPENAI_API_KEY|API_KEY|DATABASE_URL|数据库密码|password|passwd|cookie|access\s*token|refresh\s*token)",
    r"(身份证|手机号|手机号码|病历|银行卡号|用户数据|客户数据|隐私数据).{0,16}(导出|发给|发送|复制|泄露|公开)",
    r"(导出|发给|发送|复制).{0,16}(身份证|手机号|手机号码|病历|银行卡号|用户数据|客户数据|隐私数据)",
    r"(身份证|手机号|手机号码|病历|银行卡号|用户数据|客户数据|隐私数据|姓名|邮箱|邮件|地址|收货地址|订单明细|就诊记录|检查报告).{0,20}(导出|发给|发送|复制|泄露|公开|打包|压缩|上传|截图|发群|发到群|给供应商|给第三方|给销售|给外包)",
    r"(导出|发给|发送|复制|打包|压缩|上传|截图|发群|发到群|给供应商|给第三方|给销售|给外包).{0,20}(身份证|手机号|手机号码|病历|银行卡号|用户数据|客户数据|隐私数据|姓名|邮箱|邮件|地址|收货地址|订单明细|就诊记录|检查报告)",
    r"(币|合约|杠杆).{0,16}(十倍|10倍|开仓|合约|杠杆)",
    r"(USDT|稳定币|币|钱包|链上地址).{0,24}(手续费|地址|转账|转到|直接操作)",
    r"(支付风控|风控|交易|转账|资金|订单|支付|提现|提款|出款|充值|扣款|退款单|退款).{0,28}(直接)?(放行|通过|打款|退款|原路退回|处理|操作)",
    r"(直接)?(放行|通过|打款|退款|原路退回|处理|操作).{0,28}(支付风控|风控|交易|转账|资金|订单|支付|提现|提款|出款|充值|扣款|退款单|退款)",
    r"(支付风控|风控|交易|转账|资金|订单|支付|提现|提款|出款|充值|扣款|退款单|退款).{0,28}(直接|绕过|跳过|不用审核|不要走审核|别走审核|别走人工复核|不用人工复核).{0,12}(放行|通过|打款|退款|原路退回|处理|操作)",
    r"(直接|绕过|跳过|不用审核|不要走审核|别走审核|别走人工复核|不用人工复核).{0,12}(放行|通过|打款|退款|原路退回|处理|操作).{0,28}(支付风控|风控|交易|转账|资金|订单|支付|提现|提款|出款|充值|扣款|退款单|退款)",
]

NEGATABLE_MEDICAL_MARKERS = (
    "停药",
    "降压药",
    "药",
    "胸口疼",
    "胸闷",
    "心梗",
    "报告",
    "患者",
    "病人",
    "症状",
    "急诊",
    "复查",
    "孩子",
    "小孩",
    "儿童",
    "孕妇",
    "老人",
    "布洛芬",
    "感冒药",
    "退烧药",
    "误服",
    "误吃",
    "胸痛",
    "胸口痛",
    "检查报告",
    "肿瘤",
    "打120",
    "诊断",
    "判断",
)

NEGATABLE_FINANCE_MARKERS = (
    "基金",
    "股票",
    "ETF",
    "USDT",
    "稳定币",
    "房贷",
    "贷款",
    "钱包",
    "链上地址",
    "买哪只股票",
    "推荐买",
    "买卖建议",
    "仓位",
    "加仓",
    "买入",
    "卖出",
    "交易",
    "转账",
    "资金",
    "订单",
    "支付",
    "提现",
    "提款",
    "出款",
    "充值",
    "扣款",
    "退款单",
    "放行",
    "通过",
    "审核",
    "操作",
    "打款",
    "退款",
)

NEGATABLE_PRIVACY_SECRET_MARKERS = (
    "身份证",
    "手机号",
    "手机号码",
    "病历",
    "银行卡号",
    "姓名",
    "邮箱",
    "邮件",
    "收货地址",
    "订单明细",
    "就诊记录",
    "检查报告",
    "用户数据",
    "客户数据",
    "隐私数据",
    "API",
    "key",
    "密钥",
    "token",
    "访问令牌",
    "secret",
    "OPENAI_API_KEY",
    "API_KEY",
    "DATABASE_URL",
    "数据库密码",
    "password",
    "passwd",
    "cookie",
)

NEGATED_PRIVACY_SECRET_PREFIX_RE = re.compile(
    r"(不要|不用|别|先别|先不要|禁止|不得|避免|请勿|不能|不要把)[^，。；;,.!?？\n]{0,12}$",
    re.IGNORECASE,
)

NEGATED_PRIVACY_SECRET_ACTION_RE = re.compile(
    r"(不要|不用|别|先别|先不要|禁止|不得|避免|请勿|不能|不要把)"
    r"[^，。；;,.!?？\n]{0,16}"
    r"(导出|发给|发送|复制|泄露|公开|写到日志|贴到日志|打印|提交|控制台)",
    re.IGNORECASE,
)

NEGATABLE_DESTRUCTIVE_MARKERS = (
    "drop",
    "truncate",
    "rm",
    "remove-item",
    "rmdir",
    "rd",
    "del",
    "prisma",
    "migrate",
    "git",
    "push",
    "force",
    "clean",
    "prune",
    "delete",
    "remove",
    "update",
    "users",
    "role",
    "admin",
    r"删除目录",
    r"覆盖文件",
    r"覆盖\s*config\.ya?ml",
    r"覆盖.{0,12}(配置|配置文件|yaml|yml|json)",
    "mkfs",
    "format",
)

DESTRUCTIVE_EXPLANATION_RE = re.compile(
    r"(解释|是什么意思|什么意思|概念|含义|区别|风险|风险说明|作用|影响范围|确认清单|安全清单|清理前确认|检查清单|只解释)",
    re.IGNORECASE,
)

DESTRUCTIVE_LIGHT_EXPLANATION_RE = re.compile(
    r"(解释|是什么意思|什么意思|概念|含义|区别)",
    re.IGNORECASE,
)

DESTRUCTIVE_NEGATED_ACTION_RE = re.compile(
    r"(不要|不用|别|先别|先不要|禁止|不得|避免|请勿|不能)"
    r"[^，。；;,.!?？\n]{0,18}"
    r"(生成\s*SQL|生成命令|给可执行命令|可执行命令|让我复制运行|复制运行|执行|运行|删除|清空|drop|truncate|rm\s+-rf|Remove-Item|rmdir|覆盖|格式化)",
    re.IGNORECASE,
)

DANGEROUS_COMMAND_REQUEST_RE = re.compile(
    r"(生成|给我|写|输出|提供|帮我|直接给|可执行).{0,12}"
    r"(SQL|命令|脚本|指令|PowerShell|bash|shell).{0,20}"
    r"(drop|truncate|update|rm\s+-rf|Remove-Item|rmdir|del\s+/s|prisma\s+migrate\s+reset|git\s+push\s+--force|删除|清空|覆盖|格式化)",
    re.IGNORECASE,
)

DANGEROUS_OBJECT_REQUEST_RE = re.compile(
    r"(生成|给我|写|输出|提供|直接给|可执行).{0,24}(SQL|命令|脚本|指令|PowerShell|bash|shell)",
    re.IGNORECASE,
)

NEGATED_DANGEROUS_OBJECT_REQUEST_RE = re.compile(
    r"(不要|不用|别|先别|先不要|禁止|不得|避免|请勿|不能)"
    r"[^，。；;,.!?？\n]{0,12}"
    r"(生成|给我|写|输出|提供|直接给|可执行).{0,24}(SQL|命令|脚本|指令|PowerShell|bash|shell)",
    re.IGNORECASE,
)

MEDICAL_EXPLANATION_RE = re.compile(
    r"(解释|是什么意思|什么意思|概念|含义|区别|为什么|科普|问医生清单|问题清单|咨询医生|就医问题|复查问题)",
    re.IGNORECASE,
)

MEDICAL_NEGATED_ADVICE_RE = re.compile(
    r"(不要|不用|别|先别|先不要|禁止|不得|避免|请勿|不能)"
    r"[^，。；;,.!?？\n]{0,18}"
    r"(判断|诊断|给药|用药|吃药|剂量|加量|减量|停药|医疗结论|医疗建议|治疗建议)",
    re.IGNORECASE,
)

MEDICAL_SAFETY_CHECKLIST_COUNTEREXAMPLE_RE = re.compile(
    r"(不是诊断|不是让你诊断|不做诊断|不要诊断|别诊断|不能替代医生).{0,32}"
    r"(问医生清单|问题清单|咨询医生|就医问题|复查问题|整理问题|问题整理)"
    r"|"
    r"(问医生清单|问题清单|咨询医生|就医问题|复查问题|整理问题|问题整理).{0,32}"
    r"(不是诊断|不是让你诊断|不做诊断|不要诊断|别诊断|不能替代医生)",
    re.IGNORECASE,
)

PERSONALIZED_MEDICAL_DECISION_RE = re.compile(
    r"(我|我的|帮我|患者|病人|这个药|这个降压药|今天|现在|晚上|孩子|小孩|儿童|孕妇|老人).{0,24}"
    r"(能不能|要不要|是不是|该不该|判断|诊断|吃|补服|补两片|加量|减量|剂量|停|吃多少|急诊|一起吃)",
    re.IGNORECASE,
)

NEGATED_PERSONALIZED_MEDICAL_DECISION_RE = re.compile(
    r"(不要|不用|别|先别|先不要|禁止|不得|避免|请勿|不能)"
    r"[^，。；;,.!?？\n]{0,18}"
    r"(判断|诊断)?[^，。；;,.!?？\n]{0,12}"
    r"(我|我的|患者|病人|这个药|这个降压药).{0,16}"
    r"(能不能|要不要|是不是|该不该|吃|补服|补两片|加量|减量|剂量|停)",
    re.IGNORECASE,
)

FINANCE_EXPLANATION_RE = re.compile(
    r"(解释|是什么意思|什么意思|概念|含义|区别|科普|简单解释|润色|说明文案|申诉说明|审核流程|免责声明|只说明|风险清单|checklist|确认清单|风险确认|安全清单|转账前风险)",
    re.IGNORECASE,
)

FINANCE_DOCUMENT_COUNTEREXAMPLE_RE = re.compile(
    r"(润色|文案|说明|流程|免责声明|审核|申诉)",
    re.IGNORECASE,
)

FINANCE_NEGATED_ADVICE_RE = re.compile(
    r"(不要|不用|别|先别|先不要|禁止|不得|避免|请勿|不能|不承诺)"
    r"[^，。；;,.!?？\n]{0,20}"
    r"(推荐|买卖建议|投资建议|交易建议|仓位建议|加仓建议|买入|卖出|放行|放行资金|资金操作|操作资金|打款|退款|处理交易|处理转账|转账|转到|转出|转|操作钱包|直接操作|发起真实交易|真实交易|处理真实订单|操作资产|链上转账)",
    re.IGNORECASE,
)

FINANCE_SAFETY_CHECKLIST_COUNTEREXAMPLE_RE = re.compile(
    r"(风险清单|checklist|确认清单|风险确认|安全清单|转账前风险)",
    re.IGNORECASE,
)

PERSONALIZED_FINANCE_DECISION_RE = re.compile(
    r"(这只|这个|我的|我|现在|今天|跌了|涨了|仓位|房贷|贷款|USDT|钱包|链上地址).{0,24}"
    r"(基金|股票|ETF|币|交易|转账|资金|订单|支付|房贷|贷款|USDT|稳定币|钱包|链上地址).{0,24}"
    r"(能买吗|要不要|该不该|适合|买入|卖出|加仓|仓位|放行|打款|退款|提前还|还房贷|转账|转到|直接操作)",
    re.IGNORECASE,
)


def _is_privacy_secret_pattern(pattern: str) -> bool:
    lower_pattern = pattern.lower()
    return any(marker.lower() in lower_pattern for marker in NEGATABLE_PRIVACY_SECRET_MARKERS)


def _is_destructive_pattern(pattern: str) -> bool:
    lower_pattern = pattern.lower()
    return any(marker.lower() in lower_pattern for marker in NEGATABLE_DESTRUCTIVE_MARKERS)


def _is_medical_pattern(pattern: str) -> bool:
    return any(marker in pattern for marker in NEGATABLE_MEDICAL_MARKERS)


def _is_finance_pattern(pattern: str) -> bool:
    lower_pattern = pattern.lower()
    return any(marker.lower() in lower_pattern for marker in NEGATABLE_FINANCE_MARKERS)


@dataclass
class PreScanResult:
    risk_level: RiskLevel
    need_confirm: bool
    hits: list[str]
    summary: str


class RiskChecker:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._danger = [re.compile(p, re.IGNORECASE) for p in DANGER_KEYWORDS]
        self._high = [re.compile(p, re.IGNORECASE) for p in HIGH_RISK_PATTERNS]

    def pre_scan(self, text: str) -> PreScanResult:
        if not self.enabled or not text:
            return PreScanResult("low", False, [], "")

        hits: list[str] = []
        level: RiskLevel = "low"

        for pat in self._danger:
            if self._has_actionable_match(text, pat):
                hits.append(pat.pattern)

        for pat in self._high:
            if self._has_actionable_match(text, pat):
                level = "high"
                break

        if hits and level != "high":
            level = "medium"

        need_confirm = level in ("medium", "high")
        summary = ""
        if hits:
            summary = f"检测到潜在危险操作关键词，建议 risk_level={level}, need_confirm={need_confirm}"
        return PreScanResult(level, need_confirm, hits, summary)

    def _has_actionable_match(self, text: str, pattern: re.Pattern[str]) -> bool:
        for match in pattern.finditer(text):
            if self._is_negated_privacy_secret_match(text, pattern.pattern, match):
                continue
            if self._is_safe_destructive_explanation_match(text, pattern.pattern):
                continue
            if self._is_safe_medical_explanation_match(text, pattern.pattern):
                continue
            if self._is_safe_finance_explanation_match(text, pattern.pattern):
                continue
            return True
        return False

    def _is_negated_privacy_secret_match(
        self,
        text: str,
        pattern: str,
        match: re.Match[str],
    ) -> bool:
        if not _is_privacy_secret_pattern(pattern):
            return False
        prefix = text[max(0, match.start() - 20) : match.start()]
        if re.search(r"要不要[^，。；;,.!?？\n]{0,12}$", prefix):
            return False
        if NEGATED_PRIVACY_SECRET_PREFIX_RE.search(prefix):
            return True
        return bool(NEGATED_PRIVACY_SECRET_ACTION_RE.search(match.group(0)))

    def _is_safe_destructive_explanation_match(
        self,
        text: str,
        pattern: str,
    ) -> bool:
        if not _is_destructive_pattern(pattern):
            return False
        has_dangerous_request = DANGEROUS_COMMAND_REQUEST_RE.search(text) or DANGEROUS_OBJECT_REQUEST_RE.search(text)
        if has_dangerous_request and not NEGATED_DANGEROUS_OBJECT_REQUEST_RE.search(text):
            return False
        if DESTRUCTIVE_LIGHT_EXPLANATION_RE.search(text):
            return bool(DESTRUCTIVE_NEGATED_ACTION_RE.search(text))
        return bool(DESTRUCTIVE_EXPLANATION_RE.search(text) and DESTRUCTIVE_NEGATED_ACTION_RE.search(text))

    def _is_safe_medical_explanation_match(
        self,
        text: str,
        pattern: str,
    ) -> bool:
        if not _is_medical_pattern(pattern):
            return False
        if MEDICAL_SAFETY_CHECKLIST_COUNTEREXAMPLE_RE.search(text):
            return True
        if PERSONALIZED_MEDICAL_DECISION_RE.search(text) and not NEGATED_PERSONALIZED_MEDICAL_DECISION_RE.search(text):
            return False
        return bool(MEDICAL_EXPLANATION_RE.search(text) and MEDICAL_NEGATED_ADVICE_RE.search(text))

    def _is_safe_finance_explanation_match(
        self,
        text: str,
        pattern: str,
    ) -> bool:
        if not _is_finance_pattern(pattern):
            return False
        has_safe_finance_explanation = bool(
            FINANCE_EXPLANATION_RE.search(text) and FINANCE_NEGATED_ADVICE_RE.search(text)
        )
        if has_safe_finance_explanation and (
            FINANCE_DOCUMENT_COUNTEREXAMPLE_RE.search(text)
            or FINANCE_SAFETY_CHECKLIST_COUNTEREXAMPLE_RE.search(text)
        ):
            return True
        if PERSONALIZED_FINANCE_DECISION_RE.search(text):
            return False
        return has_safe_finance_explanation

    def merge_with_result(self, result: AuditResult, raw_text: str) -> AuditResult:
        pre = self.pre_scan(raw_text)
        final = result.final_text or ""
        post = self.pre_scan(final)

        level = result.risk_level
        need = result.need_confirm

        for scan in (pre, post):
            if scan.risk_level == "high":
                level = "high"
            elif scan.risk_level == "medium" and level != "high":
                level = "medium"
            if scan.need_confirm:
                need = True

        result.risk_level = level
        result.need_confirm = need
        return result

    def describe(self, result: AuditResult) -> str:
        return f"risk_level={result.risk_level}, need_confirm={result.need_confirm}"
