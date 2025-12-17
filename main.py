from aqt import mw
from aqt.qt import *
from aqt.addcards import AddCards
from aqt.gui_hooks import add_cards_did_init, browser_menus_did_init
from aqt.utils import showInfo
import requests
from bs4 import BeautifulSoup
import os
import logging
from datetime import datetime
import random
from html import unescape
import re

# ---------- 插件配置 ----------
config = mw.addonManager.getConfig(__name__) or {}
WORD_FIELD = config.get("word_field", "Word")
IPA_FIELD = config.get("ipa_field", "IPA")
TRANS_FIELD = config.get("trans_field", "BasicTrans")
EXAMPLE_FIELD = config.get("example_field", "Example")
EXAMPLE_TRANS_FIELD = config.get("example_trans_field", "ExampleTrans")
AUDIO_FIELD = config.get("audio_field", "Audio")
IMAGE_FIELD = config.get("image_field", "Image")  # 图片字段

# 新增开关配置
AUDIO_LOCAL = config.get("audio_local", True)  # True: 下载到本地，False: 使用在线URL
IMAGE_LOCAL = config.get("image_local", True)  # True: 下载到本地，False: 使用在线URL


ADDON_DIR = os.path.dirname(__file__)
LOG_FILE = os.path.join(ADDON_DIR, "youdao_debug.log")

DEBUG = config.get("debug", False)

_logger = None

def get_logger():
    global _logger
    if _logger:
        return _logger

    logger = logging.getLogger("youdao_addon")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # ⭐ 关键：不走 Anki 的 root logger

    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    _logger = logger
    return logger


def log(msg):
    if not DEBUG:
        return
    logger = get_logger()
    logger.debug(msg)
    # 立刻 flush，方便你实时看文件
    for h in logger.handlers:
        h.flush()


USER_AGENTS = [
    # Chrome Win
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",

    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/121.0.0.0 Safari/537.36",

    # macOS Chrome
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",

    # macOS Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

ACCEPT_LANGS = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.8",
    "zh-CN,zh;q=0.9,en;q=0.8",
]

def random_headers():
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": random.choice(ACCEPT_LANGS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    return headers
  
  
def clean_word(raw):
    if not raw:
        return ""

    # 1. 去首尾空白
    word = raw.strip()

    # 2. 去 HTML 标签
    if "<" in word and ">" in word:
        word = BeautifulSoup(word, "html.parser").get_text()

    # 3. HTML 实体解码
    word = unescape(word)

    # 4. 去掉首尾非单词字符（如标点）
    word = re.sub(r"^[^\w]+|[^\w]+$", "", word)

    # 5. 多空格压缩
    word = re.sub(r"\s+", " ", word)

    return word
# ---------- 抓取新版有道网页信息 ----------
def fetch_youdao_info(word):
    url = f"https://dict.youdao.com/result?word={word}&lang=en"
 

    log(f"[INFO] fetch_youdao_info start word={word}")
    try:
        r = requests.get(url, headers=random_headers(),timeout=5)
        log(f"[INFO] status={r.status_code} url={url}")
        if r.status_code != 200:
            log(f"[ERROR] non-200 response")
            return None
        
        log(f"[DEBUG] response snippet:\n{r.text[:500]}")
        soup = BeautifulSoup(r.text, "html.parser")

        # ---------- IPA ----------
        uk_ipa, us_ipa = "", ""
        phone_con = soup.select(".phone_con .per-phone")
        for per in phone_con:
            spans = per.find_all("span")
            if len(spans) < 2:
                continue
            label = spans[0].get_text(strip=True)
            phonetic = spans[1].get_text(strip=True)
            if "英" in label:
                uk_ipa = phonetic
            elif "美" in label:
                us_ipa = phonetic

        # ---------- 基本释义 ----------
        trans_list = []
        for li in soup.select(".trans-container ul.basic li.word-exp"):
            pos_tag = li.select_one(".pos")
            trans_tag = li.select_one(".trans")
            if trans_tag:
                pos = pos_tag.get_text(strip=True) if pos_tag else ""
                trans = trans_tag.get_text(strip=True)
                trans_list.append(f"{pos} {trans}".strip())
        basic_trans = "\n".join(trans_list)

        # ---------- 例句（只取第一条） ----------
        examples_en = ""
        examples_zh = ""
        example_module = soup.select_one(".blng_sents_part.dict-module .trans-container ul li.mcols-layout")
        if example_module:
            word_exps = example_module.select(".col2 .word-exp")
            if len(word_exps) >= 2:
                sen_eng_tag = word_exps[0].select_one(".sen-eng")
                sen_ch_tag = word_exps[1].select_one(".sen-ch")
                if sen_eng_tag:
                    examples_en = sen_eng_tag.get_text(strip=False)
                if sen_ch_tag:
                    examples_zh = sen_ch_tag.get_text(strip=False)

        return {
            "uk_ipa": uk_ipa,
            "us_ipa": us_ipa,
            "basic_trans": basic_trans,
            "examples_en": examples_en,
            "examples_zh": examples_zh,
        }
    except Exception as e:
        print("fetch_youdao_info error:", e)
        return None

# ---------- 获取图片 ----------
def fetch_youdao_image(word):
    """通过 picdict.youdao.com 接口获取图片"""
    api_url = f"https://picdict.youdao.com/search?q={word}&le=en"
    log(f"[INFO] fetch_youdao_image word={word}")
    try:
        r = requests.get(api_url, headers=random_headers(), timeout=5)
        log(f"[INFO] image api status={r.status_code}")
        if r.status_code != 200:
            log("[ERROR] image api non-200")
            return None
        log(f"[DEBUG] image api raw text={r.text}")
        
        # 尝试解析 JSON
        try:
            j = r.json()
        except Exception as e:
            log(f"[ERROR] json decode error: {e}")
            return None
        log(f"[DEBUG] image api json={j}")

        # ======== 新增：处理 code=101 / 无数据情况 ========
        # 返回格式：{"msg": "picture dict no data", "code": 101}
        if j.get("code") != 0:
            log(f"[WARN] image api code={j.get('code')} msg={j.get('msg')}")
            return None

        # 继续从 data.pic 中解析
        pics = j.get("data", {}).get("pic", [])
        if not pics or not isinstance(pics, list):
            return None

        first = pics[0] if len(pics) > 0 else {}
        img_url = first.get("image") or first.get("url")
        if not img_url:
            return None

        if IMAGE_LOCAL:  # 下载到本地
            r2 = requests.get(img_url, timeout=5)
            if r2.status_code == 200 and r2.content:
                filename = f"{word}.jpg"
                mw.col.media.write_data(filename, r2.content)
                return f"<img src='{filename}'>"
            else:
                return None
        else:  # 使用在线URL
            return f"<img src='{img_url}'>"

    except Exception as e:
        print("fetch_youdao_image error:", e)
        return None

# ---------- 下载美音 TTS ----------
def fetch_youdao_audio(word):
    url = f"https://dict.youdao.com/dictvoice?audio={word}&type=2"
    log(f"[INFO] fetch_youdao_audio word={word}")
    if AUDIO_LOCAL:  # 下载到本地
        try:
            r = requests.get(url, headers=random_headers(), timeout=5)
            log(f"[INFO] audio status={r.status_code} size={len(r.content)}")
            if r.status_code == 200 and r.content:
                log("[WARN] audio empty or non-200")
                filename = f"{word}.mp3"
                mw.col.media.write_data(filename, r.content)
                return f"[sound:{filename}]"
        except Exception as e:
            print("fetch_youdao_audio error:", e)
        return None
    else:  # 使用在线URL
        return f"[sound:{url}]"

# ---------- 插入字段 ----------
def insert_field(note, field_name, value):
    try:
        note[field_name] = value
    except KeyError:
        showInfo(f"字段 '{field_name}' 不存在")

# ---------- 更新单个 Note ----------
def update_note_fields(note):
  try:
    raw_word = note[WORD_FIELD]
    word = clean_word(raw_word)

    log(f"[WORD] raw='{raw_word}' cleaned='{word}'")

    if not word:
        showInfo("单词字段为空或无效")
        return
  except KeyError:
      showInfo(f"单词字段 '{WORD_FIELD}' 不存在")
      return

  if not word:
      showInfo("单词字段为空，请先填写单词")
      return

  info = fetch_youdao_info(word)
  if not info:
      log(f"[ERROR] fetch_youdao_info failed word={word}")
      showInfo("抓取失败，请检查网络或单词拼写")
      return

  # ---------- 插入抓取信息 ----------
  parts = []
  if info.get("uk_ipa"):
    parts.append(f"UK: {info['uk_ipa']}")
  if info.get("us_ipa"):
    parts.append(f"US: {info['us_ipa']}")
  ipa_text = "    ".join(parts)  # 用 4 个空格分隔
  insert_field(note, IPA_FIELD, ipa_text)
  insert_field(note, TRANS_FIELD, info['basic_trans'])
  insert_field(note, EXAMPLE_FIELD, info['examples_en'])
  insert_field(note, EXAMPLE_TRANS_FIELD, info['examples_zh'])

  audio_value = fetch_youdao_audio(word)
  if audio_value:
      insert_field(note, AUDIO_FIELD, audio_value)

  image_value = fetch_youdao_image(word)
  if image_value:
      insert_field(note, IMAGE_FIELD, image_value)
  else:
      insert_field(note, IMAGE_FIELD, "")
  
      
# ---------- 主逻辑 ----------
def on_generate(editor):
    note = editor.note
    update_note_fields(note)
    editor.loadNoteKeepingFocus()
    showInfo("抓取成功（有道）")

# ---------- 添加按钮 ----------
def setup_addcards_button(addcards: AddCards):
    btn = QPushButton("有道")  # 按钮文字优化
    btn.clicked.connect(lambda: on_generate(addcards.editor))
    addcards.form.buttonBox.layout().addWidget(btn)
    
add_cards_did_init.append(setup_addcards_button)

def setup_browser_menu(browser):
    # 使用 Notes 菜单
    notes_menu = browser.form.menu_Notes

    action = QAction("有道抓取", browser)

    def on_click():
        notes = browser.selected_notes()
        if not notes:
          showInfo("未选中任何卡片")
        for nid in notes:
            note = mw.col.get_note(nid)
            update_note_fields(note)  # 你之前定义的抓取函数
            mw.col.update_note(note)
        browser.onSearchActivated()
        showInfo(f"更新完成，共 {len(notes)} 张卡片")
       

    action.triggered.connect(on_click)
    notes_menu.addAction(action)
   

browser_menus_did_init.append(setup_browser_menu)
