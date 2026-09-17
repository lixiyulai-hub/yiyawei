"""Task and domain routing for spoken prompt compilation.

The router is intentionally small and data driven. It is not meant to do deep
research; it selects the prompt chain and optional domain fragments that make a
downstream AI request more complete.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from src.auditor.intent_frame import (
    IntentFrame,
    extract_intent_frame,
    looks_like_product_plan_with_visual_subtask,
    render_intent_frame_context,
)
from src.text.normalizer import normalize_known_terms


TaskType = Literal[
    "project_evaluation",
    "code_fix",
    "ui_ux_design",
    "visual_generation",
    "presentation_deck",
    "bug_report",
    "test_plan",
    "product_planning",
    "business_analysis",
    "text_polishing",
    "generic_task",
]

DomainType = Literal[
    "ai_tool",
    "saas",
    "ecommerce",
    "education",
    "content_community",
    "game",
    "local_life",
    "enterprise_system",
    "finance_risk",
    "healthcare",
    "general",
]


@dataclass(frozen=True)
class KeywordRule:
    patterns: tuple[str, ...]
    score: int = 1


@dataclass(frozen=True)
class TaskDefinition:
    key: TaskType
    label: str
    rules: tuple[KeywordRule, ...]
    required_any: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainDefinition:
    key: DomainType
    label: str
    rules: tuple[KeywordRule, ...]
    project_evaluation_dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExampleTemplate:
    task_type: TaskType
    domain: DomainType
    user_pattern: str
    final_text_outline: str


@dataclass(frozen=True)
class TaskTemplate:
    task_type: TaskType
    label: str
    goal: str
    output_requirements: tuple[str, ...]
    guardrails: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpokenQuestionTemplate:
    task_type: TaskType
    domain: DomainType
    question: str
    retrieval_terms: tuple[str, ...]
    expected_focus: tuple[str, ...]


@dataclass(frozen=True)
class RouteResult:
    task_type: TaskType
    task_label: str
    domain: DomainType
    domain_label: str
    task_score: int
    domain_score: int
    examples: tuple[ExampleTemplate, ...] = ()
    intent_frame: IntentFrame | None = None


@dataclass(frozen=True)
class TaskPromptTemplate:
    task_type: TaskType
    title: str
    objective: str
    focus_items: tuple[str, ...]
    output_sections: tuple[str, ...]
    constraints: tuple[str, ...] = ()


DIRECT_TASK_OPENERS: dict[TaskType, str] = {
    "code_fix": "请处理以下代码修复任务，并给出可执行的定位、修改和验证方案：",
    "ui_ux_design": "请根据以下需求输出一份可落地的 UI/UX 设计方案：",
    "visual_generation": "请直接为图像模型或设计工具编写并完善作图提示词，需求如下：",
    "presentation_deck": "请根据以下需求生成一份可直接制作 PPT/演示文稿的内容方案：",
    "bug_report": "请根据以下问题反馈输出可复现、可排查、可验收的 Bug 报告：",
    "test_plan": "请根据以下需求制定一份可直接执行的测试计划：",
    "product_planning": "请根据以下需求输出可落地的产品规划方案：",
    "business_analysis": "请根据以下问题输出一份可用于决策的商业分析：",
    "text_polishing": "请在保留原意的前提下润色以下文本：",
    "generic_task": "请根据以下需求直接完成任务：",
    "project_evaluation": "请根据以下需求评估项目是否值得推进，并给出落地建议：",
}


DIRECT_TASK_GOALS: dict[TaskType, str] = {
    "code_fix": "定位根因，给出最小必要修改，并说明如何验证修复结果。",
    "ui_ux_design": "输出可交给设计师或前端执行的页面、流程、状态和验收标准。",
    "visual_generation": "输出可直接用于生成图片的正向提示词、负面约束、画面规格和验收标准；信息不足时补齐合理假设。",
    "presentation_deck": "输出可直接制作幻灯片的结构、每页内容、素材建议和演讲备注。",
    "bug_report": "把问题写成工程团队能复现、排查、修复和回归验证的缺陷报告。",
    "test_plan": "输出覆盖范围、优先级、用例、数据准备和验收标准都清晰的测试计划。",
    "product_planning": "输出目标、用户场景、功能范围、优先级、路线图和验收指标清晰的产品规划。",
    "business_analysis": "围绕客户、需求、商业模式、获客转化、成本收益和风险给出可用于决策的分析。",
    "text_polishing": "在不新增事实的前提下，让文本更自然、准确、顺口。",
    "generic_task": "直接完成用户提出的任务；如果信息不足，先列出必须确认的问题。",
    "project_evaluation": "评估项目价值、可行性、风险和验证路径，并在适合推进时给出落地方案。",
}


LIGHTWEIGHT_CHAT_PATTERNS: tuple[str, ...] = (
    r"(讲|说|来)(?:个|一个)?(?:冷笑话|笑话|段子)",
    r"(讲|说)(?:个|一个)?(?:故事|童话)",
    r"给我讲(?:个|一个)?睡前故事",
    r"夸我一句",
    r"陪我(?:聊会儿|聊一会儿|聊一下|聊两句|闲聊一下|说说话|解解闷)",
    r"安慰我一下",
    r"随便聊聊",
    r"随便说说",
    r"哄我开心",
    r"逗我一下",
    r"让我笑一下",
)

ACTIONABLE_TASK_OVERRIDE_PATTERNS: tuple[str, ...] = (
    r"(修复|最小修复|改代码|报错|异常|错误|bug|复现|排查|定位|问题单|测试计划|测试清单|测试用例|回归测试|验收测试|测试点|测哪些点|要测什么|最小测试清单)",
    r"(项目评估|帮我评估|是否值得|值不值得|是否可行|可不可行|可行性|有没有市场|MVP|PRD|需求拆解|产品规划|商业分析)",
    r"(作图|画图|绘图|生图|生成图|图片提示词|图像提示词|配图|海报|封面|主视觉|PPT|幻灯片|演示文稿|演示稿|汇报材料|路演|提案)",
    r"(接口|API|数据库|文件|函数|组件|开发|实现|部署|提交|git|搜索|调研|竞品|市场)",
    r"(新建|写入|保存|记录|删除|修改).{0,12}(笔记|文件|页面|数据库|Obsidian)",
)


TASK_DEFINITIONS: tuple[TaskDefinition, ...] = (
    TaskDefinition(
        key="project_evaluation",
        label="项目评估 / vibe coding",
        rules=(
            KeywordRule((r"(项目|产品|应用|网站|软件|工具|平台|插件|小程序|APP|App|app|SaaS|系统|社区|团购|问诊|课程|游戏|业务|想法|方向)",), 2),
            KeywordRule((r"(是否值得|值不值得|值得做|值不值|值不值做|值不值开发|是否可行|可不可行|可行性|有没有市场|还有没有市场|商业价值|开发价值|要不要做|该不该做|有没有必要做|是不是值得|是不是可行|能不能做|能否落地)",), 3),
            KeywordRule((r"(如果值得|如果可行|如果可以|我要.*开发|我要做开发|做开发|开发出来|做出来|继续开发|投入时间|落地|落地方案|验证路线|验证一下|MVP|最小版本)",), 3),
            KeywordRule((r"(帮我评估|先帮我评估|帮我看看|帮我判断|判断一下|评估一下).{0,30}(值|市场|可行|开发|商业|痛点|落地|付费|投入)",), 2),
        ),
        required_any=(r"(是否值得|值不值得|值得做|值不值|是否可行|可不可行|可行性|有没有市场|有没有必要做|如果值得|如果可行|我要做开发|开发价值|该不该做|要不要做|帮我评估|帮我判断)",),
    ),
    TaskDefinition(
        key="code_fix",
        label="代码修复",
        rules=(
            KeywordRule((r"(修复|改代码|改一下代码|报错|报\s*\d{3}|返回\s*\d{3}|(?<!对账)异常(?!提示|状态|处理)|错误(?!提示|态)|跑不起来|编译失败|接口不通|保存失败|提交异常|超时(?!关闭)|不生效|没生效|没有反应)",), 2),
            KeywordRule((r"(文件|函数|组件|接口|API|数据库|测试失败|日志|控制台|stack trace|traceback|字段|参数|token|缓存|迁移|配置|数据流)",), 1),
            KeywordRule((r"(最小修复|最小修改|先别大改|不要大改|不要顺手重构|别上来就换实现|只动必要|先定位|定位是|根因|回归点|回归测试点)",), 1),
            KeywordRule((r"((不要|不用|别|先别).{0,10}(直接)?改代码|先告诉我问题在哪|先看.{0,12}(日志|接口|组件|函数|数据|参数))",), 4),
        ),
    ),
    TaskDefinition(
        key="ui_ux_design",
        label="UI/UX 设计",
        rules=(
            KeywordRule((r"(UI|UX|界面|视觉|交互|布局|设计稿|原型|页面风格|用户体验|移动端布局)",), 2),
            KeywordRule((r"(设计|改版|重新设计|重做|梳理).{0,24}(页面|界面|页|流程|控制台|后台|模板页|信息层级|页面层级|领取界面|看板|表格|弹窗|抽屉)",), 2),
            KeywordRule((r"(配色|字体|动效|组件|信息架构|信息层级|页面层级|空状态|无结果状态|筛选标签|详情抽屉|流程|可用性|交互状态|异常提示|空态|加载态|错误态|禁用状态)",), 1),
        ),
    ),
    TaskDefinition(
        key="visual_generation",
        label="作图 / 图片生成提示词",
        rules=(
            KeywordRule((r"(作图|画图|绘图|生图|生成图|文生图|图生图|图片生成|图像生成|图片提示词|图像提示词|生图提示词|画面提示词)",), 3),
            KeywordRule((r"(配图|插画|海报|封面|banner|Banner|thumbnail|缩略图|主视觉|KV|主图|商品主图|电商主图|宣传图|营销图|广告图|详情页首图|课程封面|游戏海报|图标|icon|分镜|分镜图|镜头图|故事板|storyboard)",), 2),
            KeywordRule((r"(Midjourney|Stable Diffusion|DALL.?E|gpt-image|image\s*2(?:\.0)?|image prompt|negative prompt|负面提示词|尺寸|比例|16:9|9:16|1:1|3:4|4:3|十六比九|九比十六|三比四|四比三|一比一|十六张|16张)",), 2),
            KeywordRule((r"(主体|场景|构图|镜头|景别|光线|灯光|色彩|材质|风格|质感|写实|扁平|插画风|科技感|商务感|高级感|短剧|AI短剧|不要出现.{0,12}logo|不要.{0,12}真实品牌)",), 1),
            KeywordRule((r"(帮我|请|给我|需要|整理|生成|写|做|出图).{0,24}(作图|画图|绘图|生图|生成图|图片|图像|配图|海报|封面|主视觉|插画|banner|提示词|分镜|分镜图|故事板)",), 2),
        ),
        required_any=(
            r"(作图|画图|绘图|生图|生成图|文生图|图生图|图片生成|图像生成|图片提示词|图像提示词|生图提示词|画面提示词|图片|图像|配图|插画|海报|封面|banner|Banner|thumbnail|缩略图|主视觉|KV|主图|商品主图|电商主图|宣传图|营销图|广告图|分镜|分镜图|故事板|Midjourney|Stable Diffusion|DALL.?E|image\s*2(?:\.0)?|image prompt)",
        ),
    ),
    TaskDefinition(
        key="presentation_deck",
        label="PPT / 演示文稿",
        rules=(
            KeywordRule((r"(PPT|ppt|幻灯片|slides?|Slides?|presentation|Presentation|deck|Deck|演示文稿|演示稿|汇报材料|路演材料|提案|宣讲稿|演讲稿|讲稿|课件)",), 3),
            KeywordRule((r"(做一份|生成一份|写一份|整理一份|帮我做|帮我写|帮我整理|输出).{0,16}(PPT|ppt|幻灯片|演示文稿|演示稿|汇报材料|路演|提案|讲稿|大纲|课件)",), 2),
            KeywordRule((r"(封面页|目录页|数据页|问题页|方案页|对比页|路线图页|总结页|附录页|每页|页码|页结构|页数|页标题|演讲备注|speaker notes)",), 2),
            KeywordRule((r"(给老板看|给客户看|给投资人看|给团队看|复盘|月报|周报|汇报|路演|融资|招商|提案|培训|课程课件)",), 1),
            KeywordRule((r"(叙事主线|故事线|视觉风格|图表|素材|配图|版式|信息层级|金字塔结构|结论先行)",), 1),
        ),
        required_any=(
            r"(PPT|ppt|幻灯片|slides?|presentation|deck|演示文稿|演示稿|汇报材料|路演材料|提案|宣讲稿|演讲稿|讲稿|课件)",
        ),
    ),
    TaskDefinition(
        key="bug_report",
        label="Bug 反馈",
        rules=(
            KeywordRule((r"(bug|问题反馈|问题单|缺陷|故障|可复现|复现步骤|复现路径|复现动作|期望结果|实际结果|期望行为|实际行为)",), 3),
            KeywordRule((r"(不对|没有反应|没反应|失效|不生效|没生效|卡住|丢了|空列表|空的|旧数据|旧头像|重复(?:提交|点击|生成|发奖|扣|记录|数据|行|文件)|不同步|顺序反了|之前可以|现在不行|没收到通知|显示已发送|状态不一致|显示未申请|刷新也一样)",), 2),
            KeywordRule((r"(问题)",), 1),
            KeywordRule((r"(请检查|请修复|排查|定位|原因|影响范围|回归点|回归验证|验收回归)",), 1),
        ),
    ),
    TaskDefinition(
        key="test_plan",
        label="测试计划",
        rules=(
            KeywordRule((r"(测试计划|测试清单|验证清单|测试用例|回归测试|验收测试|测试重点|测试项|测试点|验收清单|回归清单)",), 3),
            KeywordRule((r"(边界情况|异常情况|覆盖|验证|验收|误杀|漏放|黑白名单|前置条件|测试数据|用例清单|回归列表)",), 1),
            KeywordRule((r"(该测哪些点|测哪些点|要测什么|不知道要测什么|列测试重点|列最小测试清单|生成测试|出一份.{0,8}测试|上线前验收|要验收|不会写测试点|能直接测)",), 2),
        ),
    ),
    TaskDefinition(
        key="product_planning",
        label="产品规划",
        rules=(
            KeywordRule((r"(产品规划|路线图|需求拆解|PRD|功能规划|版本规划|MVP|用户故事|第一版范围|功能范围)",), 2),
            KeywordRule((r"(帮我规划|规划一个|规划一下|拆一下|拆需求|拆功能|设计).{0,24}(功能|流程|产品|小程序|平台|系统|需求|第一版|MVP)",), 2),
            KeywordRule((r"(功能|流程|小程序|平台|系统|中心|工具|工作区|复核台|结算|预售|回放|申诉|预警).{0,16}(帮我规划|规划一下|规划|拆需求|拆功能)",), 2),
            KeywordRule((r"(帮我规划|规划一下|我想规划|帮我拆需求|拆需求)",), 2),
            KeywordRule((r"(优先级|里程碑|需求池|产品方案|用户故事|症状采集|作业批改|两端|版本节奏|权限边界|流程|验收标准|哪些先别做)",), 1),
        ),
    ),
    TaskDefinition(
        key="business_analysis",
        label="商业分析",
        rules=(
            KeywordRule((r"(商业分析|商业模式|盈利模式|收入|成本|获客|获客成本|转化|转化率|转付费|复购|市场规模|竞品|留存|销售漏斗|定价|客单价|ROI)",), 2),
            KeywordRule((r"(激活率|使用率|续费率|退款率|误杀率).{0,8}(低|下降|下滑|升高|不高)",), 2),
            KeywordRule((r"(分析|拆一下|看一下|帮我拆).{0,30}(转化|转付费|留存|收入|成本|毛利|漏斗|成交率|指标|下降|下滑|变高|变低|为什么|原因|影响|流失|复购|获客|定价|续费|使用率|曝光|点击|完成率|激活率)",), 2),
            KeywordRule((r"(付费意愿|毛利|渠道|增长|ROI|LTV|CAC|免费试用|拆指标|排查方向|次日留存|周留存|线索来源|跟进时效|成交率|掉人|掉点|用户质量|激活率|退款率|使用率|曝光|点击|完成率|流失点)",), 1),
        ),
    ),
    TaskDefinition(
        key="text_polishing",
        label="普通文本润色",
        rules=(
            KeywordRule((r"(?<!不要)(?<!不用)(?<!别)(润色|改写|优化表达|优化.{0,8}提示语|整理成一段|写得自然|写得清楚|改得顺口|改顺|改错别字|措辞|语气|文案)",), 2),
            KeywordRule((r"(这句话|这段|标题|评语|短信|通知|邮件|回复|说明|提示语|弹窗文案|商品详情).{0,20}(清楚|自然|顺口|客气|正式|温和|稳一点|短一点|礼貌|鼓励|活泼|别夸大)",), 2),
            KeywordRule((r"(不要扩写|不要展开|不要加新信息|短一点|自然一点|客气一点|正式一点|温和一点|顺口一点|别长|别夸大)",), 1),
        ),
    ),
)


TASK_PROMPT_TEMPLATES: tuple[TaskPromptTemplate, ...] = (
    TaskPromptTemplate(
        task_type="code_fix",
        title="代码修复",
        objective="定位代码或配置中的具体问题，给出最小必要修改，并说明如何验证修复结果。",
        focus_items=(
            "先复现或推断触发条件，区分现象、根因假设和已确认事实。",
            "检查相关文件、函数、组件、接口、日志、错误栈和数据流。",
            "给出修改范围，优先修复根因，避免无关重构。",
            "补充或更新必要测试，说明手动验证步骤。",
        ),
        output_sections=(
            "问题定位",
            "修改方案",
            "具体改动",
            "验证方式",
            "残余风险或需要确认的信息",
        ),
        constraints=(
            "不要只泛泛建议“检查代码”，需要落到可执行步骤。",
            "不要回滚或覆盖用户已有改动，除非用户明确要求。",
        ),
    ),
    TaskPromptTemplate(
        task_type="ui_ux_design",
        title="UI/UX 设计",
        objective="把界面、视觉和交互需求整理成可落地的设计任务，覆盖用户流程、状态和验收标准。",
        focus_items=(
            "明确目标用户、使用场景、核心任务和设计目标。",
            "梳理页面结构、信息层级、关键流程、空态、加载态、错误态和成功态。",
            "说明布局、组件、配色、字体、动效、可访问性和响应式要求。",
            "给出可执行的界面清单和交互细节，而不是只描述风格词。",
        ),
        output_sections=(
            "设计目标",
            "用户流程",
            "关键界面与组件",
            "视觉与交互规范",
            "验收标准",
        ),
        constraints=(
            "请保持在界面设计任务范围内。",
            "不要把 UI 需求改写成其他类型的分析任务。",
        ),
    ),
    TaskPromptTemplate(
        task_type="visual_generation",
        title="作图 / 图片生成提示词",
        objective="把口述的作图、海报、封面、配图或生图需求整理成可直接交给图像模型或设计工具执行的高质量视觉提示词。",
        focus_items=(
            "明确图片用途、目标受众、主体对象、场景、情绪和核心信息。",
            "补齐画面风格、构图、镜头/景别、光线、色彩、材质、细节密度和参考媒介。",
            "指定尺寸比例、输出格式、文字/Logo 使用限制、品牌安全和负面约束。",
            "如果用于 PPT、海报、电商详情、课程封面或游戏素材，请说明版式留白、标题区、可读性和后续编辑需求。",
        ),
        output_sections=(
            "用途与受众",
            "主体与场景",
            "风格与构图",
            "尺寸比例与输出格式",
            "正向提示词",
            "负面约束",
            "验收标准",
        ),
        constraints=(
            "不要默认生成或模仿真实品牌 Logo、受版权保护角色或未授权真人肖像。",
            "不要把作图需求误写成 UI 页面设计，除非用户明确要求界面方案。",
        ),
    ),
    TaskPromptTemplate(
        task_type="presentation_deck",
        title="PPT / 演示文稿",
        objective="把口述的 PPT、汇报、路演、提案或课件需求整理成可直接生成幻灯片大纲和内容的演示文稿任务。",
        focus_items=(
            "明确目标受众、汇报目标、使用场景、时长、页数和必须回答的核心问题。",
            "设计叙事主线、结论顺序、章节结构、每页标题、每页要点和页间逻辑。",
            "说明需要的数据页、图表、案例、配图、视觉风格、版式密度和品牌/行业语气。",
            "补充演讲备注、需要用户提供的素材清单、风险假设和验收标准。",
        ),
        output_sections=(
            "目标受众与汇报目标",
            "叙事主线",
            "页码结构",
            "每页要点",
            "视觉风格与图表素材",
            "演讲备注",
            "验收标准",
        ),
        constraints=(
            "不要编造业务数据、市场数据或公司内部事实；缺失数据请标注为待补充。",
            "不要只输出泛泛目录，每页都要有可执行的标题、要点和素材建议。",
        ),
    ),
    TaskPromptTemplate(
        task_type="bug_report",
        title="Bug 反馈",
        objective="把问题描述整理成可复现、可排查、可验收的缺陷反馈。",
        focus_items=(
            "拆分期望行为、实际行为、复现路径、影响范围和出现频率。",
            "保留关键环境信息，例如页面、账号角色、浏览器、版本、接口、日志或截图线索。",
            "列出优先排查方向和可能关联模块。",
            "给出修复完成后的回归验证点。",
        ),
        output_sections=(
            "问题摘要",
            "复现步骤",
            "期望行为与实际行为",
            "影响范围",
            "排查建议",
            "验收标准",
        ),
        constraints=(
            "不要把问题反馈写成泛泛的吐槽。",
            "不确定的信息请标注为待确认。",
        ),
    ),
    TaskPromptTemplate(
        task_type="test_plan",
        title="测试计划",
        objective="把测试意图整理成覆盖范围清晰、优先级明确、可执行的测试计划。",
        focus_items=(
            "明确测试对象、版本范围、入口路径、前置条件和测试环境。",
            "覆盖核心流程、回归路径、边界情况、异常情况、权限/数据状态和兼容性。",
            "区分冒烟测试、功能测试、回归测试和验收测试。",
            "为每类用例写清操作步骤、预期结果和失败时需要记录的信息。",
        ),
        output_sections=(
            "测试范围",
            "测试策略",
            "用例清单",
            "数据与环境准备",
            "验收标准",
            "风险与补充检查",
        ),
        constraints=(
            "请保持在测试计划范围内，不做无关扩展。",
            "测试项要能直接执行，避免只写抽象原则。",
        ),
    ),
    TaskPromptTemplate(
        task_type="product_planning",
        title="产品规划",
        objective="把产品想法整理成目标、范围、优先级和版本节奏清晰的规划任务。",
        focus_items=(
            "明确目标用户、核心问题、业务目标、成功指标和非目标范围。",
            "拆解功能模块、用户故事、关键流程、依赖关系和约束条件。",
            "按用户价值、实现成本、风险和依赖划分优先级。",
            "规划版本节奏、里程碑、交付物和验收标准。",
        ),
        output_sections=(
            "产品目标",
            "用户与场景",
            "功能范围",
            "优先级",
            "版本路线图",
            "指标与验收标准",
        ),
        constraints=(
            "可以提出需要补充的问题，但不要编造用户规模或确定性数据。",
            "规划要服务落地执行，避免只写愿景口号。",
        ),
    ),
    TaskPromptTemplate(
        task_type="business_analysis",
        title="商业分析",
        objective="把商业问题整理成围绕市场、客户、收入、成本、渠道和风险的分析任务。",
        focus_items=(
            "明确分析对象、目标客户、使用场景、购买动机和替代方案。",
            "分析收入模式、成本结构、定价、获客渠道、转化、留存和复购。",
            "区分已知事实、待验证假设和需要外部资料支持的信息。",
            "给出关键风险、机会点、验证实验和下一步决策建议。",
        ),
        output_sections=(
            "分析目标",
            "客户与需求",
            "商业模式",
            "获客与转化",
            "成本与收益",
            "风险与验证计划",
        ),
        constraints=(
            "不要编造市场规模、收入或竞品数据；无法确认的地方标注为假设。",
            "结论需要说明依据和不确定性。",
        ),
    ),
    TaskPromptTemplate(
        task_type="text_polishing",
        title="普通文本润色",
        objective="在保留原意的前提下，修复口语重复、病句和措辞问题，让文本更自然清楚。",
        focus_items=(
            "保留事实、态度、语气和必要的礼貌表达，不改变立场。",
            "清理口头禅、重复表达、错序句和明显错词。",
            "根据用户要求控制长度、语气和正式程度。",
            "如果用户要求不要扩写，就只做表达层面的润色。",
        ),
        output_sections=(
            "润色后文本",
            "必要说明",
        ),
        constraints=(
            "只做表达层面的清理和润色，保持短小克制。",
            "不要新增原文没有的信息。",
        ),
    ),
)


DOMAIN_DEFINITIONS: tuple[DomainDefinition, ...] = (
    DomainDefinition(
        key="ai_tool",
        label="AI 工具",
        rules=(
            KeywordRule((r"\bAI\b|人工智能|大模型|LLM|ChatGPT|Claude|Gemini|Cursor|Codex|智能体|Agent",), 2),
            KeywordRule((r"API|token|推理|工作流|自动化|RAG|向量|embedding|多模态|prompt|提示词|提示词模板|生成按钮|生成失败|复制结果",), 1),
        ),
        project_evaluation_dimensions=(
            "模型成本",
            "API 依赖",
            "差异化",
            "工作流嵌入",
            "付费意愿",
            "护城河",
            "数据闭环",
            "结果可靠性",
            "延迟体验",
            "用户可控性",
        ),
    ),
    DomainDefinition(
        key="saas",
        label="SaaS",
        rules=(
            KeywordRule((r"SaaS|订阅|多租户|B端|企业客户|席位|续费|ARR|MRR",), 2),
            KeywordRule((r"客户成功|(?<!测)试用|转付费|套餐",), 1),
        ),
        project_evaluation_dimensions=(
            "目标客群",
            "订阅定价",
            "试用转化",
            "留存续费",
            "客户成功成本",
            "集成生态",
            "权限协作",
            "数据迁移",
            "实施周期",
            "使用频次",
        ),
    ),
    DomainDefinition(
        key="ecommerce",
        label="电商",
        rules=(
            KeywordRule((r"电商|店铺|商品|SKU|库存|供应链|履约|发货|物流|退货|优惠券|购物车|售后|主图|商品主图|卖点",), 2),
            KeywordRule((r"获客|转化率|复购|毛利|客单价|投放|带货|订单|满减|结算",), 1),
        ),
        project_evaluation_dimensions=(
            "SKU",
            "供应链",
            "获客",
            "转化率",
            "复购",
            "毛利",
            "履约成本",
            "库存周转",
            "售后退货",
            "投放回本",
        ),
    ),
    DomainDefinition(
        key="education",
        label="教育",
        rules=(
            KeywordRule((r"教育|课程|在线课程|学习|学生|老师|题库|作业|教培|知识点|训练营|打卡",), 2),
            KeywordRule((r"完课率|学习效果|测评|班课|辅导|作业批改|学习打卡",), 1),
        ),
        project_evaluation_dimensions=(
            "学习效果",
            "内容供给",
            "师资或 AI 辅导",
            "完课率",
            "家长/学生付费",
            "合规风险",
            "题库质量",
            "个性化路径",
            "续班/复购",
        ),
    ),
    DomainDefinition(
        key="content_community",
        label="内容社区",
        rules=(
            KeywordRule((r"社区|内容社区|内容平台|小红书|抖音|博主|达人|笔记|帖子|评论|创作者|UGC|PGC|粉丝|推荐流",), 2),
            KeywordRule((r"审核|冷启动|留存|互动|增长|内容供给|发布",), 1),
        ),
        project_evaluation_dimensions=(
            "冷启动",
            "内容供给",
            "推荐与分发",
            "社区治理",
            "创作者激励",
            "留存",
            "内容安全",
            "互动质量",
            "商业化路径",
        ),
    ),
    DomainDefinition(
        key="game",
        label="游戏",
        rules=(
            KeywordRule((r"游戏|小游戏|玩法|关卡|数值|战斗|抽卡|联机|Steam|手游|买量",), 2),
            KeywordRule((r"留存|次日留存|付费点|美术|手感|匹配|每日任务|奖励领取|新手引导",), 1),
        ),
        project_evaluation_dimensions=(
            "核心玩法",
            "留存循环",
            "数值系统",
            "美术成本",
            "获量成本",
            "付费设计",
            "新手引导",
            "社交/匹配",
            "版本节奏",
        ),
    ),
    DomainDefinition(
        key="local_life",
        label="本地生活",
        rules=(
            KeywordRule((r"本地生活|到店|同城|外卖|门店|商家|商户|团购|附近|到店预约|门店预约",), 2),
            KeywordRule((r"地推|履约|核销|商家供给|订单状态|到店团购",), 1),
            KeywordRule((r"同城|门店预约|商家供给|到店|核销",), 1),
        ),
        project_evaluation_dimensions=(
            "供需密度",
            "商户获取",
            "履约链路",
            "地理覆盖",
            "核销体验",
            "本地获客",
            "服务质量",
            "价格补贴",
            "复购频次",
        ),
    ),
    DomainDefinition(
        key="enterprise_system",
        label="企业管理系统",
        rules=(
            KeywordRule((r"企业管理|企业审批|ERP|CRM|OA|进销存|审批|工单|管理系统|企业系统|企业.{0,8}(权限|后台|流程|报表|审计|通知|内部)",), 2),
            KeywordRule((r"组织架构|角色|业务流程|企业流程|报表|导入导出|请假流程|销售漏斗|线索来源",), 1),
        ),
        project_evaluation_dimensions=(
            "业务流程",
            "权限模型",
            "数据迁移",
            "报表",
            "系统集成",
            "实施培训",
            "角色协作",
            "审批链路",
            "ROI/降本增效",
        ),
    ),
    DomainDefinition(
        key="finance_risk",
        label="金融/风控",
        rules=(
            KeywordRule((r"金融|风控|支付|信贷|交易|反欺诈|KYC|征信|资金|(?:支付|交易|资金|风控|KYC|征信|监管).{0,8}合规|合规.{0,8}(支付|交易|资金|风控|KYC|征信|监管)",), 2),
            KeywordRule((r"风险模型|审计|监管|授信|逾期|风控规则|误杀|漏放|黑白名单",), 1),
        ),
        project_evaluation_dimensions=(
            "合规边界",
            "风险模型",
            "数据来源",
            "审计追踪",
            "资金安全",
            "误杀/漏判成本",
            "实名/KYC",
            "反欺诈策略",
            "灰度风控",
        ),
    ),
    DomainDefinition(
        key="healthcare",
        label="医疗健康",
        rules=(
            KeywordRule((r"医疗|健康|医生|患者|病历|问诊|诊断|药品|康复|心理",), 2),
            KeywordRule((r"临床|处方|健康管理|症状采集|紧急情况|分流|(?:医疗|健康|问诊|患者|病历|医生).{0,8}(隐私|合规)|(?:隐私|合规).{0,8}(医疗|健康|问诊|患者|病历|医生)",), 1),
        ),
        project_evaluation_dimensions=(
            "医疗合规",
            "隐私保护",
            "临床安全",
            "专业背书",
            "用户信任",
            "误导风险",
            "分诊边界",
            "医患责任",
            "数据脱敏",
        ),
    ),
)


EXAMPLE_TEMPLATES: tuple[ExampleTemplate, ...] = (
    ExampleTemplate(
        task_type="project_evaluation",
        domain="ai_tool",
        user_pattern="帮我分析一个 AI 工具项目是否值得开发，如果值得我要做开发",
        final_text_outline="先评估需求、竞品、模型/API 成本、结果可靠性和差异化，再输出 MVP、架构、数据闭环和开发路线图。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="saas",
        user_pattern="帮我看看这个 SaaS 订阅产品有没有市场，如果能做就给我落地方案",
        final_text_outline="先评估目标客群、付费场景、订阅定价、试用转化、续费和实施成本，再输出 MVP、权限协作和集成计划。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="ecommerce",
        user_pattern="帮我分析一个电商项目值不值得做，如果可以就落地",
        final_text_outline="先评估 SKU、供应链、获客、转化、复购、毛利、库存周转和履约成本，再输出 MVP 和运营验证计划。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="education",
        user_pattern="帮我判断这个教育题库或者课程工具值不值得做，如果值得我要开发",
        final_text_outline="先评估学习效果、题库质量、内容供给、师资或 AI 辅导、完课率和付费路径，再输出 MVP 与验证标准。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="content_community",
        user_pattern="帮我分析一个内容社区平台能不能做起来，如果可以给我开发路线",
        final_text_outline="先评估冷启动、内容供给、推荐分发、互动质量、社区治理和商业化路径，再输出 MVP 与增长实验。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="game",
        user_pattern="帮我看看这个游戏玩法项目值不值得开发，如果值得就拆开发方案",
        final_text_outline="先评估核心玩法、留存循环、数值系统、美术成本、获量成本和付费设计，再输出首版玩法验证与版本节奏。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="local_life",
        user_pattern="帮我分析一个本地生活预约平台有没有机会，如果能落地就给方案",
        final_text_outline="先评估供需密度、商户获取、履约链路、核销体验、本地获客和服务质量，再输出区域 MVP 与运营验证。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="enterprise_system",
        user_pattern="帮我评估一个企业管理系统是否值得开发，如果值得我要做开发",
        final_text_outline="先评估业务流程、权限模型、审批链路、数据迁移、系统集成、报表和实施培训，再输出模块拆分和交付计划。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="finance_risk",
        user_pattern="帮我分析一个金融风控系统是否可行，如果可行就给开发方案",
        final_text_outline="先评估合规边界、风险模型、数据来源、实名/KYC、审计追踪和误杀漏判成本，再输出 MVP 与风控灰度方案。",
    ),
    ExampleTemplate(
        task_type="project_evaluation",
        domain="healthcare",
        user_pattern="帮我看看医疗健康问诊应用值不值得做，如果值得我要开发",
        final_text_outline="先评估医疗合规、隐私保护、临床安全、分诊边界、专业背书和误导风险，再输出安全 MVP 与验收标准。",
    ),
    ExampleTemplate(
        task_type="visual_generation",
        domain="ai_tool",
        user_pattern="帮我给 AI 工具官网写一张主视觉图提示词，16:9，科技感，不要出现真实品牌 Logo",
        final_text_outline="整理为图片生成提示词，包含用途受众、主体场景、构图光线、色彩材质、尺寸比例、正向提示词、负面约束和验收标准。",
    ),
    ExampleTemplate(
        task_type="presentation_deck",
        domain="ecommerce",
        user_pattern="帮我做一份电商复盘 PPT 大纲，给老板看，包含数据页、问题页和改进计划",
        final_text_outline="整理为演示文稿任务，包含受众目标、叙事主线、页码结构、每页要点、图表素材、视觉风格、演讲备注和验收标准。",
    ),
    ExampleTemplate(
        task_type="bug_report",
        domain="general",
        user_pattern="之前可以自动粘贴，现在没有这个功能了",
        final_text_outline="整理成可复现的问题反馈，包含期望行为、实际行为、影响范围和检查项。",
    ),
)


SPOKEN_QUESTION_TEMPLATES: tuple[SpokenQuestionTemplate, ...] = (
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="ai_tool",
        question="这个 AI 工具到底有没有刚需，用户为什么不用 ChatGPT 或现成插件？",
        retrieval_terms=("AI 工具", "ChatGPT", "插件", "刚需", "替代方案"),
        expected_focus=("差异化", "工作流嵌入", "付费意愿", "护城河"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="ai_tool",
        question="如果模型调用很贵或者不稳定，这个项目还能不能赚钱、能不能交付？",
        retrieval_terms=("模型成本", "API 依赖", "稳定性", "交付"),
        expected_focus=("模型成本", "API 依赖", "结果可靠性", "延迟体验"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="saas",
        question="这个 SaaS 是卖给谁，按席位还是按用量收费，试用后怎么转付费？",
        retrieval_terms=("SaaS", "席位", "用量", "试用", "转付费"),
        expected_focus=("目标客群", "订阅定价", "试用转化", "使用频次"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="saas",
        question="客户导入数据和接入现有系统会不会太重，后续续费靠什么？",
        retrieval_terms=("数据导入", "系统接入", "续费", "客户成功"),
        expected_focus=("数据迁移", "集成生态", "客户成功成本", "留存续费"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="ecommerce",
        question="这个电商项目卖什么 SKU，供应链、库存和退货会不会把毛利吃掉？",
        retrieval_terms=("电商", "SKU", "供应链", "库存", "退货", "毛利"),
        expected_focus=("SKU", "供应链", "库存周转", "售后退货", "毛利"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="ecommerce",
        question="投放买量能不能回本，转化率和复购要做到多少才值得做？",
        retrieval_terms=("投放", "获客", "转化率", "复购", "回本"),
        expected_focus=("获客", "转化率", "复购", "投放回本"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="education",
        question="这个课程或者题库工具怎么证明学习效果，学生会不会坚持用完？",
        retrieval_terms=("课程", "题库", "学习效果", "完课率"),
        expected_focus=("学习效果", "题库质量", "完课率", "个性化路径"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="education",
        question="家长或者学生愿不愿意付费，AI 辅导和真人老师怎么搭配？",
        retrieval_terms=("家长付费", "学生付费", "AI 辅导", "老师"),
        expected_focus=("家长/学生付费", "师资或 AI 辅导", "续班/复购"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="content_community",
        question="这个内容社区冷启动怎么做，第一批内容和创作者从哪里来？",
        retrieval_terms=("内容社区", "冷启动", "创作者", "内容供给"),
        expected_focus=("冷启动", "内容供给", "创作者激励", "推荐与分发"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="content_community",
        question="社区怎么避免低质内容和灌水，靠什么留存和商业化？",
        retrieval_terms=("审核", "低质内容", "留存", "商业化"),
        expected_focus=("内容安全", "互动质量", "社区治理", "商业化路径"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="game",
        question="这个游戏玩法好不好玩，首日留存和长期循环靠什么？",
        retrieval_terms=("游戏", "玩法", "首日留存", "循环"),
        expected_focus=("核心玩法", "留存循环", "新手引导", "版本节奏"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="game",
        question="美术、数值、抽卡或者付费点要做到什么程度，买量能不能打平？",
        retrieval_terms=("美术", "数值", "抽卡", "付费点", "买量"),
        expected_focus=("数值系统", "美术成本", "付费设计", "获量成本"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="local_life",
        question="本地生活平台先做哪个城市或商圈，商户和用户怎么同时起来？",
        retrieval_terms=("本地生活", "城市", "商圈", "商户", "用户"),
        expected_focus=("供需密度", "地理覆盖", "商户获取", "本地获客"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="local_life",
        question="预约、到店、核销和售后这条链路会不会太重，服务质量怎么控？",
        retrieval_terms=("预约", "到店", "核销", "售后", "服务质量"),
        expected_focus=("履约链路", "核销体验", "服务质量", "复购频次"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="enterprise_system",
        question="这个企业管理系统解决哪个流程问题，老板凭什么愿意付实施费？",
        retrieval_terms=("企业管理系统", "流程", "实施费", "降本增效"),
        expected_focus=("业务流程", "实施培训", "ROI/降本增效", "报表"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="enterprise_system",
        question="权限、审批、导入导出和现有系统集成怎么设计才不乱？",
        retrieval_terms=("权限", "审批", "导入导出", "系统集成"),
        expected_focus=("权限模型", "审批链路", "数据迁移", "系统集成"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="finance_risk",
        question="这个金融风控项目数据从哪里来，合规和 KYC 边界怎么处理？",
        retrieval_terms=("金融风控", "数据来源", "合规", "KYC"),
        expected_focus=("数据来源", "合规边界", "实名/KYC", "审计追踪"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="finance_risk",
        question="风控模型误杀和漏判成本多高，怎么灰度上线避免资金风险？",
        retrieval_terms=("风控模型", "误杀", "漏判", "灰度", "资金风险"),
        expected_focus=("风险模型", "误杀/漏判成本", "灰度风控", "资金安全"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="healthcare",
        question="这个医疗健康应用能不能做诊断建议，分诊边界和责任怎么划？",
        retrieval_terms=("医疗健康", "诊断", "分诊", "责任"),
        expected_focus=("医疗合规", "分诊边界", "临床安全", "医患责任"),
    ),
    SpokenQuestionTemplate(
        task_type="project_evaluation",
        domain="healthcare",
        question="用户病历和健康数据怎么保护，怎么避免给出误导性建议？",
        retrieval_terms=("病历", "健康数据", "隐私", "误导建议"),
        expected_focus=("隐私保护", "数据脱敏", "用户信任", "误导风险"),
    ),
)


TASK_TEMPLATES: tuple[TaskTemplate, ...] = (
    TaskTemplate(
        task_type="project_evaluation",
        label="项目评估 / vibe coding",
        goal="把模糊项目想法编排成评估、调研、决策和开发落地 brief。",
        output_requirements=(
            "澄清项目概念、目标用户、场景、痛点和成功标准",
            "分析市场、竞品/替代方案、商业模式、付费意愿、获客和差异化",
            "评估技术可行性、成本、风险、证据强弱和不确定性",
            "如果值得或需要验证，输出 MVP、架构、UI 方向、路线图和验收标准",
        ),
        guardrails=("不要编造市场数据、竞品事实、用户规模或收入结论",),
    ),
    TaskTemplate(
        task_type="code_fix",
        label="代码修复",
        goal="把口述问题整理成可交给 coding agent 的排查和修复任务。",
        output_requirements=(
            "说明现象、影响范围、相关模块或文件线索",
            "要求先定位根因，再提出修复方案",
            "保留不要直接改代码、先分析等限制条件",
            "要求补充或运行相关测试",
        ),
        guardrails=("不要编造不存在的文件名、函数名、错误日志或实现细节",),
    ),
    TaskTemplate(
        task_type="ui_ux_design",
        label="UI/UX 设计",
        goal="把视觉和交互口述整理成可执行的产品界面设计任务。",
        output_requirements=(
            "明确目标用户、页面/流程、核心操作和信息层级",
            "给出布局、组件状态、交互反馈、空/错/加载状态",
            "说明视觉风格、密度、可访问性和响应式要求",
            "输出可交给设计或前端实现的验收标准",
        ),
        guardrails=("不要把 UI 需求写成营销落地页，除非用户明确要求",),
    ),
    TaskTemplate(
        task_type="visual_generation",
        label="作图 / 图片生成提示词",
        goal="把作图、海报、封面、配图或生图口述整理成可交给图像模型或设计工具执行的视觉提示词。",
        output_requirements=(
            "明确用途、受众、主体、场景、核心信息和画面情绪",
            "补齐风格、构图、镜头、光线、色彩、材质和细节密度",
            "指定尺寸比例、输出格式、文字区、Logo/品牌限制和负面提示词",
            "输出正向提示词、负面约束和验收标准，方便直接用于作图或二次编辑",
        ),
        guardrails=("不要默认模仿真实品牌 Logo、版权角色或未授权真人肖像",),
    ),
    TaskTemplate(
        task_type="presentation_deck",
        label="PPT / 演示文稿",
        goal="把 PPT、汇报、路演、提案或课件口述整理成受众、故事线、页结构和素材要求清晰的演示任务。",
        output_requirements=(
            "明确目标受众、汇报目标、场景、时长、页数和核心结论",
            "设计叙事主线、章节结构、页码结构、每页标题和每页要点",
            "说明视觉风格、图表素材、配图、数据缺口和演讲备注",
            "输出可直接交给 AI 生成幻灯片或人工制作的验收标准",
        ),
        guardrails=("不要编造业务数据、市场数据或公司内部事实，缺失数据标注为待补充",),
    ),
    TaskTemplate(
        task_type="bug_report",
        label="Bug 反馈",
        goal="把零散问题反馈整理成可复现、可排查的问题描述。",
        output_requirements=(
            "区分期望行为和实际行为",
            "保留复现路径、前置条件、触发动作和影响范围",
            "列出需要检查的模块、日志、状态和回归点",
            "要求修复后补充验证用例",
        ),
        guardrails=("不要把问题反馈改写成泛泛的优化建议",),
    ),
    TaskTemplate(
        task_type="test_plan",
        label="测试计划",
        goal="把测试口述整理成结构清晰的验证计划或测试清单。",
        output_requirements=(
            "覆盖核心流程、边界情况、异常情况和回归点",
            "列出测试前置条件、测试数据、步骤和预期结果",
            "区分必须测、建议测和可选扩展",
            "输出验收标准和风险提醒",
        ),
        guardrails=("不要把测试结论误改成开发任务请求",),
    ),
    TaskTemplate(
        task_type="product_planning",
        label="产品规划",
        goal="把产品想法整理成需求拆解、优先级和路线图。",
        output_requirements=(
            "明确目标用户、核心场景、用户故事和成功指标",
            "拆分 MVP、后续版本和非目标范围",
            "给出功能优先级、依赖关系、里程碑和验收标准",
            "标注关键假设和需要验证的问题",
        ),
        guardrails=("不要把规划直接扩成完整项目评估，除非用户询问是否值得开发",),
    ),
    TaskTemplate(
        task_type="business_analysis",
        label="商业分析",
        goal="把商业口述整理成市场、模式、增长和风险分析任务。",
        output_requirements=(
            "分析目标客户、需求强度、竞品/替代方案和差异化",
            "评估收入模式、成本结构、获客渠道、转化和留存",
            "列出关键假设、证据需求、风险和验证路径",
            "给出结论、优先验证项和下一步动作",
        ),
        guardrails=("不要编造确定性市场规模、收入或竞品事实",),
    ),
    TaskTemplate(
        task_type="text_polishing",
        label="普通文本润色",
        goal="把普通口述文本整理成自然、准确、不过度扩写的表达。",
        output_requirements=(
            "保留原意、语气和必要事实",
            "清理口头禅、重复、病句和标点问题",
            "按用户要求控制长度、风格和对象",
        ),
        guardrails=("不要扩写成项目方案或任务 brief，除非用户明确要求",),
    ),
)


def detect_task_route(text: str) -> RouteResult:
    cleaned = _cleanup(text)
    intent_frame = extract_intent_frame(cleaned)
    task_type, task_label, task_score = _detect_task(cleaned, intent_frame=intent_frame)
    domain, domain_label, domain_score = _detect_domain(cleaned, task_type=task_type)
    examples = retrieve_examples(task_type, domain)
    return RouteResult(
        task_type=task_type,
        task_label=task_label,
        domain=domain,
        domain_label=domain_label,
        task_score=task_score,
        domain_score=domain_score,
        examples=examples,
        intent_frame=intent_frame,
    )


def get_domain_definition(domain: DomainType) -> DomainDefinition | None:
    for definition in DOMAIN_DEFINITIONS:
        if definition.key == domain:
            return definition
    return None


def get_task_template(task_type: TaskType) -> TaskTemplate | None:
    for template in TASK_TEMPLATES:
        if template.task_type == task_type:
            return template
    return None


def retrieve_examples(task_type: TaskType, domain: DomainType, limit: int = 3) -> tuple[ExampleTemplate, ...]:
    """Placeholder retrieval API for future few-shot example selection."""

    exact = [
        example
        for example in EXAMPLE_TEMPLATES
        if example.task_type == task_type and example.domain == domain
    ]
    fallback = [
        example
        for example in EXAMPLE_TEMPLATES
        if example.task_type == task_type and example.domain != domain
    ]
    return tuple((exact + fallback)[:limit])


def retrieve_question_templates(
    task_type: TaskType,
    domain: DomainType,
    limit: int = 6,
) -> tuple[SpokenQuestionTemplate, ...]:
    """Retrieve compact spoken-question corpus entries by task and domain."""

    exact = [
        template
        for template in SPOKEN_QUESTION_TEMPLATES
        if template.task_type == task_type and template.domain == domain
    ]
    fallback = [
        template
        for template in SPOKEN_QUESTION_TEMPLATES
        if template.task_type == task_type and template.domain != domain
    ]
    return tuple((exact + fallback)[:limit])


def get_task_prompt_template(task_type: TaskType) -> TaskPromptTemplate | None:
    for template in TASK_PROMPT_TEMPLATES:
        if template.task_type == task_type:
            return template
    return None


def render_task_prompt_template(text: str, route: RouteResult) -> str:
    template = get_task_prompt_template(route.task_type)
    if not template:
        return ""

    source_text = _cleanup(text)
    opener = DIRECT_TASK_OPENERS.get(route.task_type, DIRECT_TASK_OPENERS["generic_task"])
    goal = DIRECT_TASK_GOALS.get(route.task_type, template.objective)

    lines = [
        opener,
        source_text,
        "",
        "任务目标：",
        goal,
        "",
        "输出要求：",
    ]
    lines.extend(f"- {section}" for section in template.output_sections)
    lines.append("")
    lines.append("执行要点：")
    lines.extend(f"- {item}" for item in template.focus_items)
    mixed_image_sections = _presentation_image_generation_sections(source_text, route)
    if mixed_image_sections:
        lines.append("")
        lines.append("配图/作图交付物：")
        lines.extend(f"- {item}" for item in mixed_image_sections)
    if template.constraints:
        lines.append("")
        lines.append("限制条件：")
        lines.extend(f"- {item}" for item in template.constraints)
    lines.append("")
    lines.append("请直接给出可执行结果，不要解释你将如何改写这段需求，也不要只给抽象原则。")
    return "\n".join(lines)


def _presentation_image_generation_sections(text: str, route: RouteResult) -> tuple[str, ...]:
    if route.task_type != "presentation_deck" or not _has_image_generation_deliverable(text):
        return ()
    ratio = _extract_visual_ratio(text)
    model = "image 2.0" if re.search(r"image\s*2\.0", text, re.IGNORECASE) else "图像生成模型"
    spec = f"{ratio} 比例" if ratio else "按 PPT 版式需要确定比例"
    return (
        f"同时输出一条可直接交给 {model} 的单张配图提示词，不要只写 PPT 大纲。",
        f"配图规格：{spec}；说明画面主体、场景、构图、光线、色彩、风格、文字/Logo 限制和负面约束。",
        "说明这张图放在 PPT 的哪一页、承担什么信息作用，以及需要给标题区或正文区预留哪些空间。",
    )


def _has_image_generation_deliverable(text: str) -> bool:
    if not text or not re.search(r"(PPT|ppt|幻灯片|presentation|deck|演示文稿|演示稿)", text, re.IGNORECASE):
        return False
    has_image_object = bool(
        re.search(r"(一张|1\s*张|配图|图片|图像|作图|生图|生成图|海报|封面|主视觉|主图)", text, re.IGNORECASE)
    )
    has_generation_signal = bool(
        re.search(r"(image\s*2\.0|生成|生图|作图|画图|出图|十六比九|16\s*[:：比]\s*9|九比十六|9\s*[:：比]\s*16)", text, re.IGNORECASE)
    )
    return has_image_object and has_generation_signal


def _extract_visual_ratio(text: str) -> str:
    if re.search(r"(16\s*[:：比]\s*9|十六比九)", text):
        return "16:9"
    if re.search(r"(9\s*[:：比]\s*16|九比十六)", text):
        return "9:16"
    if re.search(r"(1\s*[:：比]\s*1|一比一)", text):
        return "1:1"
    if re.search(r"(3\s*[:：比]\s*4|三比四)", text):
        return "3:4"
    if re.search(r"(4\s*[:：比]\s*3|四比三)", text):
        return "4:3"
    return ""


def build_domain_project_fragment(domain: DomainType) -> str:
    definition = get_domain_definition(domain)
    if not definition or not definition.project_evaluation_dimensions:
        return ""
    dimensions = "、".join(definition.project_evaluation_dimensions)
    return f"针对{definition.label}领域，请额外评估：{dimensions}。"


def build_route_context(text: str, route: RouteResult | None = None) -> str:
    route = route or detect_task_route(text)
    template = get_task_template(route.task_type)
    lines = [
        f"任务路由: {route.task_label} (task_type={route.task_type}, score={route.task_score})",
        f"领域路由: {route.domain_label} (domain={route.domain}, score={route.domain_score})",
    ]
    if route.intent_frame:
        frame_context = render_intent_frame_context(route.intent_frame)
        if frame_context:
            lines.append(frame_context)
    if template:
        lines.append(f"任务模板目标: {template.goal}")
        lines.append("任务模板要求: " + "；".join(template.output_requirements))
        if template.guardrails:
            lines.append("模板约束: " + "；".join(template.guardrails))
    domain_fragment = build_domain_project_fragment(route.domain)
    if domain_fragment and route.task_type == "project_evaluation":
        lines.append(domain_fragment)
    if route.examples:
        example_text = "；".join(
            f"“{example.user_pattern}” -> {example.final_text_outline}"
            for example in route.examples
        )
        lines.append(f"示例检索方向: {example_text}")
    question_templates = retrieve_question_templates(route.task_type, route.domain, limit=3)
    if question_templates:
        question_text = "；".join(
            f"{template.question}（关注：{'、'.join(template.expected_focus)}）"
            for template in question_templates
        )
        lines.append(f"常见口述问题: {question_text}")
    return "\n".join(lines)


def required_domain_terms(domain: DomainType) -> tuple[str, ...]:
    definition = get_domain_definition(domain)
    return definition.project_evaluation_dimensions if definition else ()


def _detect_task(text: str, intent_frame: IntentFrame | None = None) -> tuple[TaskType, str, int]:
    task_text = _task_detection_text(text)
    if looks_like_product_plan_with_visual_subtask(task_text):
        return ("product_planning", "产品规划", 9)
    intent_override = _task_from_intent_frame(intent_frame)
    if intent_override:
        return intent_override
    if _looks_like_lightweight_chat(task_text):
        return ("generic_task", "通用任务", 0)
    if _looks_like_explicit_polishing_request(task_text):
        return ("text_polishing", "普通文本润色", 3)
    if _looks_like_plain_text_only_request(task_text):
        return ("generic_task", "通用任务", 0)
    if _looks_like_voice_compiler_feedback(task_text):
        return ("bug_report", "Bug 反馈", 5)
    if _looks_like_browser_annotation_feature_request(task_text):
        return ("product_planning", "产品规划", 5)

    best: tuple[TaskType, str, int] = ("generic_task", "通用任务", 0)
    for definition in TASK_DEFINITIONS:
        if definition.required_any and not any(
            _has_non_negated_match(task_text, pattern) for pattern in definition.required_any
        ):
            continue
        score = _score_rules(task_text, definition.rules)
        if definition.key == "project_evaluation" and score < 5:
            continue
        if definition.key == "bug_report" and _looks_like_ai_coding_governance_request(task_text):
            continue
        if definition.key == "bug_report" and score < 2:
            continue
        if definition.key == "code_fix" and score < 2:
            continue
        if definition.key == "test_plan" and score < 2:
            continue
        if definition.key == "product_planning" and score < 2:
            continue
        if definition.key == "product_planning" and _looks_like_ai_coding_governance_request(task_text):
            score += 4
        if definition.key == "visual_generation" and score < 2:
            continue
        if definition.key == "presentation_deck" and score < 3:
            continue
        if definition.key == "text_polishing" and score < 2:
            continue
        if score > best[2] or (
            score > 0 and score == best[2] and _task_priority(definition.key) > _task_priority(best[0])
        ):
            best = (definition.key, definition.label, score)
    return best


def _task_from_intent_frame(frame: IntentFrame | None) -> tuple[TaskType, str, int] | None:
    if not frame or frame.confidence < 0.85 or not frame.task_hint:
        return None
    if frame.task_hint in {"generic_task", "text_polishing"}:
        return None
    labels: dict[TaskType, str] = {
        "project_evaluation": "项目评估 / vibe coding",
        "code_fix": "代码修复",
        "ui_ux_design": "UI/UX 设计",
        "visual_generation": "作图 / 图片生成提示词",
        "presentation_deck": "PPT / 演示文稿",
        "bug_report": "Bug 反馈",
        "test_plan": "测试计划",
        "product_planning": "产品规划",
        "business_analysis": "商业分析",
        "text_polishing": "普通文本润色",
        "generic_task": "通用任务",
    }
    task_hint = frame.task_hint
    if task_hint not in labels:
        return None
    score = max(5, int(frame.confidence * 10))
    return (task_hint, labels[task_hint], score)  # type: ignore[return-value]


def _looks_like_ai_coding_governance_request(text: str) -> bool:
    has_ai_coder = bool(re.search(r"(大模型|Codex|codeex|cloud\s*code|claude\s*code|Claude Code|Cursor)", text, re.IGNORECASE))
    has_damage = bool(re.search(r"(改乱|覆盖|删掉|误删|回滚|冲掉|代码.{0,12}(变少|丢失)|四千行|一千多行)", text, re.IGNORECASE))
    has_governance_request = bool(re.search(r"(杜绝|规避|治理|全局|工作方式|方法|方案|解决方法|改善|维护|规范)", text))
    return has_ai_coder and has_damage and has_governance_request


def _task_priority(task_type: TaskType) -> int:
    priorities: dict[TaskType, int] = {
        "generic_task": 0,
        "text_polishing": 1,
        "business_analysis": 2,
        "product_planning": 3,
        "project_evaluation": 4,
        "ui_ux_design": 5,
        "visual_generation": 6,
        "presentation_deck": 7,
        "code_fix": 8,
        "bug_report": 9,
        "test_plan": 10,
    }
    return priorities[task_type]


def _task_detection_text(text: str) -> str:
    """Use the latest corrected clause for task intent, while domain still sees full text."""

    if not text:
        return text
    markers = tuple(re.finditer(r"(算了|不对|前面不要|不是(?:让你|要|做|诊断|操作|分析)?|不是)", text))
    for marker in reversed(markers):
        tail = text[marker.end() :].strip(" ，。,.、：:")
        if len(tail) < 4:
            continue
        if _has_actionable_task_override(tail) or _looks_like_plain_text_only_request(tail):
            return tail
    return text


def _looks_like_lightweight_chat(text: str) -> bool:
    if not text:
        return False
    if not any(re.search(pattern, text, re.IGNORECASE) for pattern in LIGHTWEIGHT_CHAT_PATTERNS):
        return False
    return not _has_actionable_task_override(text)


def _looks_like_voice_compiler_feedback(text: str) -> bool:
    if not text:
        return False
    has_context = bool(
        re.search(
            r"(咿呀喂|Yiyawei|语音界面|语音编译器|语音指令编译器|识别.*界面|目标界面|当前界面|粘贴|复制|录音|任务栏|窗口位置)",
            text,
            re.IGNORECASE,
        )
    )
    has_issue = bool(
        re.search(
            r"(弹到|跑到|跳到|任务栏|最小化|还得.*点|还要.*点|不用.*点|需要.*位置|之前|现在.*不行|问题|没有|不会|不能|粘贴过后|复制过后)",
            text,
            re.IGNORECASE,
        )
    )
    has_paste_or_window = bool(re.search(r"(粘贴|复制|任务栏|窗口|目标界面|语音界面)", text, re.IGNORECASE))
    return has_context and has_issue and has_paste_or_window


def _looks_like_browser_annotation_feature_request(text: str) -> bool:
    if not text:
        return False
    has_browser_annotation = bool(re.search(r"(右侧浏览器|浏览器|浏览器上|标注|批注|圈注)", text, re.IGNORECASE))
    has_app_surface = bool(re.search(r"(我们的这个界面|这个界面|语音界面|编译器界面|当前界面|界面)", text))
    has_feature_action = bool(
        re.search(
            r"(放到|放在|打开到|展示到|嵌入到|搬到|移到|通过.{0,12}标注|直接.{0,12}标注|标注改|批注改)",
            text,
            re.IGNORECASE,
        )
    )
    return has_browser_annotation and has_app_surface and has_feature_action


def _has_actionable_task_override(text: str) -> bool:
    for pattern in ACTIONABLE_TASK_OVERRIDE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if _is_negated_action(text, match.start()):
                continue
            return True
    return False


def _is_negated_action(text: str, start: int) -> bool:
    prefix = text[max(0, start - 8) : start]
    return bool(re.search(r"(不要|不用|别|无须|无需|不必|先别|先不要).{0,4}$", prefix))


def _detect_domain(text: str, *, task_type: TaskType = "generic_task") -> tuple[DomainType, str, int]:
    if task_type == "generic_task" and _looks_like_plain_text_only_request(text):
        return ("general", "通用", 0)
    best: tuple[DomainType, str, int] = ("general", "通用", 0)
    for definition in DOMAIN_DEFINITIONS:
        score = _score_rules(text, definition.rules)
        if definition.key == "ai_tool" and score < 2:
            if not (task_type == "test_plan" and re.search(r"(提示词模板|生成失败|复制结果)", text)):
                continue
        if score > best[2]:
            best = (definition.key, definition.label, score)
    return best


def _looks_like_plain_text_only_request(text: str) -> bool:
    if not text:
        return False
    has_light_operation = bool(
        re.search(
            r"(只|就|简单|一下|帮我|给我|请)?.{0,16}"
            r"(翻译|翻成英文|译成英文|解释|是什么意思|什么意思|润色|改顺|改错别字|压缩成一句|整理成一句|"
            r"压缩|摘要|加标点|加个句号|读一下|顺不顺|改成一句|汇报|汇报进度|列.*问题清单|列.*风险因素|确认清单)",
            text,
        )
        or re.search(r"(翻译|解释|润色|改顺|改错别字|加标点|压缩成一句|整理成一句|压缩|摘要|问题清单|风险因素|确认清单).{0,12}(就好|即可|就行|一下|简单)", text)
        or re.search(r"(整理|生成|列|列出).{0,12}(问题清单|风险因素|确认清单)", text)
        or re.search(r"(只是|只是想|我只是).{0,16}(汇报|说一下|记录).{0,16}(进度|状态|已经|完成|修好)", text)
        or re.search(r"(只是|只是想|我只是).{0,12}(问|了解).{0,12}(是什么意思|什么意思)", text)
    )
    has_visual_or_deck_term_only = bool(
        re.search(
            r"(PPT|ppt|幻灯片|presentation|deck|课件|图片|图像|作图|生图|海报|封面|提示词|prompt|image\s*2(?:\.0)?|image).{0,16}"
            r"(这个词|这几个字|这三个字|这两个字|翻译|解释|是什么意思|什么意思|加标点|改错别字|读一下)",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"(翻译|解释|是什么意思|什么意思|加标点|改错别字|读一下).{0,16}"
            r"(PPT|ppt|幻灯片|presentation|deck|课件|图片|图像|作图|生图|海报|封面|提示词|prompt|image\s*2(?:\.0)?|image)",
            text,
            re.IGNORECASE,
        )
    )
    has_negative_heavy_task = bool(
        re.search(
            r"(不要|不用|别|先别|先不要|不是).{0,18}"
            r"(做方案|方案|规划|产品规划|需求拆解|商业分析|分析|分析业务|分析规则|项目评估|"
            r"诊断流程|诊断建议|医疗结论|投资建议|买卖建议|生成测试计划|测试计划|作图|生图|生成图|做PPT|做 PPT|生成PPT|生成 PPT|幻灯片|演示文稿|安排任务|执行|直接执行|直接删除|操作资金)",
            text,
        )
    )
    has_sensitive_safety_boundary = bool(
        re.search(r"(不要|不用|别|先别|先不要).{0,18}(诊断|医疗结论|投资建议|买卖建议|执行|删除|清空|操作资金)", text)
        or re.search(r"(咨询医生|自己核对|影响范围|需要确认|确认清单|替代方案)", text)
    )
    if has_light_operation and (has_visual_or_deck_term_only or has_negative_heavy_task or has_sensitive_safety_boundary):
        return True
    return bool(
        has_light_operation
        and re.search(r"(只是|只是想|我只是).{0,8}(问|了解)", text)
        and re.search(r"(项目评估|值不值得|可不可行|商业分析|规划|方案|开发)", text)
    )


def _looks_like_explicit_polishing_request(text: str) -> bool:
    if not text:
        return False
    if re.search(r"(不要|不用|别|先别|先不要)\s*润色", text):
        return False
    if re.search(r"(只|就).{0,8}(翻译|翻成英文|译成英文|加标点|加个句号|改错别字)", text):
        return False
    has_polishing = bool(
        re.search(
            r"(只|先|帮我|给我|请)?.{0,16}(润色|改顺|改写|优化表达|写得自然|写得清楚)",
            text,
        )
    )
    has_light_constraint = bool(
        re.search(r"(不要扩写|别扩写|不要展开|不要加新信息|只润色|只改|只做表达)", text)
    )
    has_text_object = bool(
        re.search(r"(这句|这句话|这段|标题|提示词|免责声明|文案|通知|说明)", text)
    )
    return has_polishing and (has_light_constraint or has_text_object)


def _score_rules(text: str, rules: tuple[KeywordRule, ...]) -> int:
    score = 0
    for rule in rules:
        if any(_has_non_negated_match(text, pattern) for pattern in rule.patterns):
            score += rule.score
    return score


def _has_non_negated_match(text: str, pattern: str) -> bool:
    for match in re.finditer(pattern, text, re.IGNORECASE):
        if _is_negated_action(text, match.start()):
            continue
        return True
    return False


def _cleanup(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_known_terms(text or "")).strip()
