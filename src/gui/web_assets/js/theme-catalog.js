const THEME_STORAGE_KEY = "voice-prompt-compiler-theme";
const THEME_STORAGE_VERSION_KEY = "voice-prompt-compiler-theme-version";
const CURRENT_THEME_STORAGE_VERSION = "3";
const AUTO_THEME_ID = "auto-random";
const AUTO_THEME_INTERVAL_MS = 30000;

const autoThemeOption = {
  id: AUTO_THEME_ID,
  label: "随机流光 · 30秒",
  swatches: ["#f8fffc", "#b5ebe0", "#ffd8d0", "#dbeafe"],
  chrome: "#eefaf6",
};

const themes = [
  {
    id: "silver-frost",
    label: "01 银白霜璃",
    swatches: ["#fbfdff", "#d3deea", "#8b9bae"],
    chrome: "#edf3f8",
  },
  {
    id: "aurora-blue",
    label: "02 极光蓝白",
    swatches: ["#f7fbff", "#b5d8fc", "#4f91d9"],
    chrome: "#e7f4ff",
  },
  {
    id: "pearl-rose",
    label: "03 珍珠玫瑰",
    swatches: ["#fffafa", "#ffd5dd", "#d8788c"],
    chrome: "#fff0f2",
  },
  {
    id: "sage-mist",
    label: "04 鼠尾草雾",
    swatches: ["#fbfefb", "#c7dfcc", "#719d7c"],
    chrome: "#edf6ee",
  },
  {
    id: "mint-glass",
    label: "05 薄荷玻璃",
    swatches: ["#f8fffc", "#b5ebe0", "#45aa9a"],
    chrome: "#e8f9f4",
  },
  {
    id: "champagne-white-gold",
    label: "06 香槟白金",
    swatches: ["#fffdf7", "#f1dab5", "#c28a45"],
    chrome: "#f8efdf",
  },
  {
    id: "lavender-haze",
    label: "07 薰衣草雾",
    swatches: ["#fbfaff", "#d9cfff", "#8d7bd7"],
    chrome: "#efebff",
  },
  {
    id: "glacier-cyan",
    label: "08 冰川青",
    swatches: ["#f7fdff", "#ace0f2", "#3b9dca"],
    chrome: "#e4f7ff",
  },
  {
    id: "warm-paper",
    label: "09 暖纸白",
    swatches: ["#fffdf8", "#eadecf", "#a87a54"],
    chrome: "#f5eee5",
  },
  {
    id: "cobalt-minimal",
    label: "10 钴蓝极简",
    swatches: ["#fbfdff", "#bed7fa", "#2f73d6"],
    chrome: "#eaf3ff",
  },
  {
    id: "forest-mist",
    label: "11 森林清雾",
    swatches: ["#fbfefa", "#bfdcc7", "#4e8a64"],
    chrome: "#e9f4eb",
  },
  {
    id: "soft-clay",
    label: "12 软陶玻璃",
    swatches: ["#fff9f5", "#e8c7b1", "#c36b52"],
    chrome: "#f4e5d8",
  },
  {
    id: "monochrome",
    label: "13 云白石墨",
    swatches: ["#ffffff", "#e4eaf2", "#7f8fa3"],
    chrome: "#eeeeef",
  },
  {
    id: "chrome-silver",
    label: "14 铬银",
    swatches: ["#fbfcfe", "#c4cfdc", "#7d8ea3"],
    chrome: "#e8edf3",
  },
  {
    id: "bento-neutral",
    label: "15 Bento 中性",
    swatches: ["#fffdfa", "#dfdad3", "#6f6255"],
    chrome: "#f0ece6",
  },
  {
    id: "spatial-glass",
    label: "16 空间玻璃",
    swatches: ["#fbfdff", "#bcd8fa", "#5e85d6"],
    chrome: "#eaf4ff",
  },
  {
    id: "quiet-luxury-taupe",
    label: "17 静奢灰褐",
    swatches: ["#fbfaf7", "#d3cac0", "#8d7965"],
    chrome: "#e9e2da",
  },
  {
    id: "tactile-paper",
    label: "18 触感纸白",
    swatches: ["#fffdf8", "#e0dace", "#9c6f5b"],
    chrome: "#f3efe6",
  },
  {
    id: "wellness-green",
    label: "19 健康绿",
    swatches: ["#fbfff8", "#cae7be", "#73a84e"],
    chrome: "#edf8e8",
  },
  {
    id: "slate-coral",
    label: "20 石板珊瑚",
    swatches: ["#f9fbfb", "#c4ced2", "#d36f5d"],
    chrome: "#e3e8e9",
  },
  {
    id: "porcelain",
    label: "21 瓷白",
    swatches: ["#ffffff", "#dae2e8", "#8399a8"],
    chrome: "#f1f5f7",
  },
  {
    id: "moonlight-indigo",
    label: "22 晨雾靛蓝",
    swatches: ["#f8fbff", "#dfeaf8", "#7898c8"],
    chrome: "#edf4ff",
  },
  {
    id: "ink-white",
    label: "23 云白银蓝",
    swatches: ["#ffffff", "#e7eef6", "#6f9ec8"],
    chrome: "#f4f5f6",
  },
  {
    id: "sand-silver",
    label: "24 沙银",
    swatches: ["#fffdfa", "#dcd3c5", "#8f887a"],
    chrome: "#eee7dc",
  },
  {
    id: "citrus-minimal",
    label: "25 柑橘极简",
    swatches: ["#fffef7", "#fae483", "#d6a824"],
    chrome: "#fff6c8",
  },
  {
    id: "ocean-mist",
    label: "26 海雾",
    swatches: ["#f8fffd", "#b7e2de", "#4a9da0"],
    chrome: "#e4f6f4",
  },
  {
    id: "obsidian-light",
    label: "27 棱镜白",
    swatches: ["#ffffff", "#e9eef7", "#8fb7e8"],
    chrome: "#f3f7fc",
  },
  {
    id: "sky-pearl",
    label: "28 天空珍珠",
    swatches: ["#f8fcff", "#b7ddf9", "#4193da"],
    chrome: "#e2f3ff",
  },
  {
    id: "cream-blue",
    label: "29 奶油蓝",
    swatches: ["#fffdf8", "#e5dbcb", "#557fa8"],
    chrome: "#f1ebdf",
  },
  {
    id: "blush-glass",
    label: "30 雾粉白",
    swatches: ["#fffafa", "#ffd2d6", "#d96f7c"],
    chrome: "#ffecec",
  },
  {
    id: "noir-aqua",
    label: "31 薄荷水光",
    swatches: ["#f7fffb", "#b8eadc", "#5dbfb4"],
    chrome: "#e8f8f3",
  },
  {
    id: "graphite-lime",
    label: "32 珊瑚晴空",
    swatches: ["#fffafa", "#ffd2c7", "#8fc8f2"],
    chrome: "#fff0ec",
  },
  {
    id: "carbon-rose",
    label: "33 蜜桃玫瑰奶",
    swatches: ["#fff8f6", "#ffd7dd", "#e58c9e"],
    chrome: "#fff0f2",
  },
  {
    id: "midnight-amber",
    label: "34 晨霜浅蓝",
    swatches: ["#fbfdff", "#d9e8f7", "#8db7df"],
    chrome: "#eff6fd",
  },
  {
    id: "ink-cyan",
    label: "35 珠光青蓝",
    swatches: ["#f7fdff", "#bcebf0", "#61b9cc"],
    chrome: "#e8f8fb",
  },
  {
    id: "plum-gold",
    label: "36 蓝莓牛奶",
    swatches: ["#fbfaff", "#dcd9ff", "#8693d8"],
    chrome: "#f0f1ff",
  },
  {
    id: "deep-teal-coral",
    label: "37 海盐银绿",
    swatches: ["#f8fffd", "#c9eadf", "#78b8a5"],
    chrome: "#edf8f4",
  },
  {
    id: "charcoal-mint",
    label: "38 银粉薄雾",
    swatches: ["#fffafa", "#eadce6", "#c58ba8"],
    chrome: "#f8eff4",
  },
  {
    id: "royal-ivory",
    label: "39 樱橙微光",
    swatches: ["#fff9f5", "#ffd8bd", "#e99772"],
    chrome: "#fff1e8",
  },
  {
    id: "black-ice-blue",
    label: "40 冰蓝珍珠",
    swatches: ["#f8fdff", "#c9e9fb", "#76b8de"],
    chrome: "#eaf8ff",
  },
  {
    id: "espresso-cream",
    label: "41 香草奶霜",
    swatches: ["#fffdf7", "#f4e6c7", "#d4a96a"],
    chrome: "#fbf1df",
  },
  {
    id: "wine-pearl",
    label: "42 草莓珍珠",
    swatches: ["#fff8fb", "#f5d2df", "#df7fa1"],
    chrome: "#fff0f6",
  },
  {
    id: "forest-neon",
    label: "43 森林晨露",
    swatches: ["#fbfff9", "#cce9c8", "#7bb987"],
    chrome: "#eff9ee",
  },
  {
    id: "slate-sunrise",
    label: "44 日出云粉",
    swatches: ["#fff9f6", "#ffd7c8", "#8fbfe8"],
    chrome: "#fff0ea",
  },
  {
    id: "violet-graphite",
    label: "45 云朵薰衣草",
    swatches: ["#fcfaff", "#e1d8ff", "#a795dc"],
    chrome: "#f3efff",
  },
  {
    id: "steel-orange",
    label: "46 杏橙银白",
    swatches: ["#fffaf5", "#f6d7bd", "#d79664"],
    chrome: "#fff1e4",
  },
  {
    id: "navy-sakura",
    label: "47 樱粉天空",
    swatches: ["#fff9fc", "#ffd6e8", "#a9cdf4"],
    chrome: "#fff0f8",
  },
  {
    id: "jade-obsidian",
    label: "48 翡翠浅雾",
    swatches: ["#f8fffb", "#c5ead9", "#6fbd9a"],
    chrome: "#ecf8f1",
  },
  {
    id: "copper-night",
    label: "49 焦糖晨白",
    swatches: ["#fffaf4", "#f2d4b7", "#c99567"],
    chrome: "#faefe2",
  },
  {
    id: "arctic-black",
    label: "50 极地珠白",
    swatches: ["#fbfeff", "#d9f1fb", "#8abfe1"],
    chrome: "#eefaff",
  },
];

const themeOptions = [autoThemeOption, ...themes];

export {
  THEME_STORAGE_KEY,
  THEME_STORAGE_VERSION_KEY,
  CURRENT_THEME_STORAGE_VERSION,
  AUTO_THEME_ID,
  AUTO_THEME_INTERVAL_MS,
  autoThemeOption,
  themes,
  themeOptions,
};
