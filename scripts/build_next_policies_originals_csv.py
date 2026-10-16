#!/usr/bin/env python3
"""取得済みの原本から originals.csv を組み立てる。引用は原本のテキストに完全一致するものだけを残す。"""
import csv, glob, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LOC = os.path.join(ROOT, ".local/next-policies-originals")
RAW, TXT = LOC + "/raw", LOC + "/text"
OUT = os.path.join(ROOT, "data/acquired/next-policies-originals/originals.csv")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
man = {}
for r in csv.DictReader(open(LOC + "/manifest.csv", encoding="utf-8")):
    if r["http"] == "200" and r["file"]:
        man[r["file"]] = r
fus = json.load(open(LOC + "/fusoku.json", encoding="utf-8"))
rows, bad = [], []


def m(fn):
    return man[fn]


def text_of(fn):
    if fn.endswith(".json"):
        return open(f"{RAW}/{fn}", encoding="utf-8").read()
    return open(f"{TXT}/{fn.rsplit('.', 1)[0]}.txt", encoding="utf-8").read()


def add(pol, kind, title, fn, pub="", enf="", who="", role="", quote="", src_text=None, url=None):
    r = m(fn)
    t = src_text if src_text is not None else text_of(fn)
    if quote and quote not in t:
        bad.append((pol, fn, quote[:40])); return
    rows.append([pol, kind, title, url or r["url"], r["sha256"], r["fetched_at"][:10], pub, enf, who, role, quote])


def find(prefix):
    g = [k for k in man if k.startswith(prefix)]
    return g[0] if g else None


# ---------- e-Gov ----------
EG = {  # 政策: (キー, 附則の施行日(附則そのものに日付があるもの), 附則抜粋)
    "科学技術基本法": "科学技術基本法", "IT基本法": "IT基本法", "知的財産基本法": "知的財産基本法",
    "国立大学法人法": "国立大学法人法", "資金決済法": "資金決済法", "FIT": "FIT", "マイナンバー法": "マイナンバー法",
    "会社法": "会社法", "民泊": "民泊"}
FUS_ENF = {"科学技術基本法": "1995-11-15", "IT基本法": "2001-01-06", "国立大学法人法": "2003-10-01", "FIT": "2012-07-01"}
FUS_Q = {"科学技術基本法": "この法律は、公布の日から施行する。", "IT基本法": "この法律は、平成十三年一月六日から施行する。",
         "国立大学法人法": "この法律は、平成十五年十月一日から施行する。", "FIT": "この法律は、平成二十四年七月一日から施行する。",
         "知的財産基本法": "この法律は、公布の日から起算して三月を超えない範囲内において政令で定める日から施行する。",
         "資金決済法": "この法律は、公布の日から起算して一年を超えない範囲内において政令で定める日から施行する。",
         "マイナンバー法": "この法律は、公布の日から起算して三年を超えない範囲内において政令で定める日から施行する。",
         "会社法": "この法律は、公布の日から起算して一年六月を超えない範囲内において政令で定める日から施行する。",
         "民泊": "この法律は、公布の日から起算して一年を超えない範囲内において政令で定める日から施行する。"}
for pol, key in EG.items():
    s = json.load(open(find("egov_%s_search" % key) and f"{RAW}/{find('egov_%s_search' % key)}", encoding="utf-8"))
    li = s["laws"][0]
    pub = li["law_info"]["promulgation_date"]
    title = li["revision_info"]["law_title"] + "（" + li["law_info"]["law_num"] + "）"
    tx = find("egov_%s_" % key + li["law_info"]["law_id"] + "_20") if False else [k for k in man if k.startswith("egov_%s_%s_" % (key, li["law_info"]["law_id"])) and k.endswith("_text.json")][0]
    enf = FUS_ENF.get(pol, "")
    add(pol, "法令(e-Gov 附則)", title + " 附則 施行期日", tx, pub, enf, quote=FUS_Q[pol], src_text=fus[key])
    rv = [k for k in man if k.startswith("egov_%s_%s_" % (key, li["law_info"]["law_id"])) and k.endswith("_revisions.json")][0]
    if pol == "民泊":
        add(pol, "法令(e-Gov 改正履歴)", title + " 改正履歴(施行日)", rv, pub, "2018-06-15", quote='"law_revision_id":"429AC0000000065_20180615_000000000000000"')
    else:
        add(pol, "法令(e-Gov 改正履歴)", title + " 公布日", rv, pub, "", quote='"promulgation_date":"%s"' % pub)
# 改正法(単独の法令データがないもの)
for fn in [k for k in man if k.startswith("egov_携帯電話料金_359AC")]:
    add("携帯電話料金", "法令(e-Gov 改正履歴)", "電気通信事業法の一部を改正する法律（令和元年法律第5号）", fn, "2019-05-17", "2019-10-01",
        quote='"amendment_law_num":"令和元年法律第五号"')

# ---------- 首相官邸 歴代内閣 ----------
SEC = {81: (93, 150), 86: (91, 170), 87: (82, 143), 88: (78, 140), 92: (21, 120), 94: (149, 240), 96: (21, 103),
       97: (464, 546), 98: (278, 374), 99: (21, 110)}
PPL = [  # 政策, ページ, 氏名, 役職
    ("科学技術基本法", 81, "村山 富市", "内閣総理大臣"), ("科学技術基本法", 81, "浦野 烋興", "科学技術庁長官"),
    ("IT基本法", 86, "森 喜朗", "内閣総理大臣"),
    ("知的財産基本法", 87, "小泉 純一郎", "内閣総理大臣"),
    ("研究開発税制", 87, "塩川 正十郎", "財務大臣"), ("研究開発税制", 87, "平沼 赳夫", "経済産業大臣"),
    ("国立大学法人法", 87, "遠山 敦子", "文部科学大臣"),
    ("会社法", 88, "南野 知惠子", "法務大臣"),
    ("資金決済法", 92, "麻生 太郎", "内閣総理大臣"), ("資金決済法", 92, "与謝野 馨", "財務大臣・内閣府特命担当大臣（金融）"),
    ("FIT", 94, "菅 直人", "内閣総理大臣"), ("FIT", 94, "海江田 万里", "経済産業大臣"),
    ("マイナンバー法", 96, "安倍 晋三", "内閣総理大臣"), ("マイナンバー法", 96, "甘利 明", "内閣府特命担当大臣（経済財政政策）"),
    ("薬事法改正", 96, "田村 憲久", "厚生労働大臣"),
    ("電力小売全面自由化", 96, "茂木 敏充", "経済産業大臣"),
    ("民泊", 97, "石井 啓一", "国土交通大臣"),
    ("携帯電話料金", 98, "石田 真敏", "総務大臣"),
    ("携帯電話料金", 99, "武田　良太", "総務大臣"),
]
NAME = {81: "第81代 村山 富市（第81代内閣・改造内閣 平成7年8月8日改造）", 86: "第86代 森 喜朗（第2次森内閣 改造 平成12年12月5日）",
        87: "第87代 小泉 純一郎（第1次小泉内閣 第1次改造 平成14年9月30日）", 88: "第88代 小泉 純一郎（第2次小泉内閣 改造 平成16年9月27日）",
        92: "第92代 麻生 太郎（麻生内閣）", 94: "第94代 菅 直人（第2次改造 平成23年1月14日）", 96: "第96代 安倍 晋三（第2次安倍内閣）",
        97: "第97代 安倍 晋三（第3次安倍内閣 第2次改造）", 98: "第98代 安倍 晋三（第4次安倍内閣 改造）", 99: "第99代 菅 義偉（菅（義）内閣）"}
for pol, pg, who, role in PPL:
    lines = [l.strip() for l in open(f"{TXT}/kantei_0{pg}.txt", encoding="utf-8").read().splitlines() if l.strip()]
    a, b = SEC[pg]
    sl = "\n".join(lines[a:b])
    add(pol, "官邸ページ(閣僚名簿)", "首相官邸 歴代内閣 " + NAME[pg], f"kantei_0{pg}.html", who=who.replace("　", " "), role=role, quote=who, src_text=sl)

# ---------- 省庁・その他公式ページ ----------
P = [
    ("携帯電話料金", "総務省 報道資料 モバイル市場の公正な競争環境の整備に向けたアクション・プラン（2020-10-27 公表）", "soumu_actionplan.html", "", "2019-10-01",
     "武田", "総務大臣", "「武田総務大臣と携帯電話利用者との意見交換会」"),
    ("携帯電話料金", "総務省 報道資料 同上（本文）", "soumu_actionplan.html", "", "", "", "", "電気通信事業法の一部を改正する法律（令和元年法律第5号。以下「改正法」という。）"),
    ("携帯電話料金", "総務省 中国総合通信局 電気通信事業法改正の施行のお知らせ", "soumu_kaisei_chugoku.html", "2019-05-17", "2019-10-01", "", "",
     "電気通信事業法が令和元年5月17日に改正され、10月1日から施行"),
    ("民泊", "観光庁 民泊制度ポータルサイト 住宅宿泊事業法の施行状況", "mlit_minpaku_situation.html", "", "", "", "", "住宅宿泊事業法の施行状況"),
    ("科学技術基本法", "内閣府 科学技術政策 科学技術基本法制定に至る経緯", "cao_kihonhou_keii.html", "1995-11-15", "1995-11-15", "", "", "公布、施行（法律第１３０号）"),
    ("研究開発税制", "財務省 所得税法等の一部を改正する法律案要綱（第156回国会）", "mof_156diet_youkou.html", "", "", "", "", "試験研究費の総額に係る特別税額控除制度の創設"),
    ("国立大学法人法", "文部科学省 国立大学法人法の概要", "mext_houjin_gaiyou.html", "", "2004-04-01", "", "", "国立大学法人の設立は、平成16年4月1日"),
    ("国立大学法人法", "文部科学省 国立大学法人法の概要（法律の施行日）", "mext_houjin_gaiyou.html", "", "2003-10-01", "", "", "法律の施行日は、平成15年10月1日"),
    ("資金決済法", "金融庁 資金決済に関する法律の施行に伴う政令案等の結果について", "fsa_20100223.html", "2009-06-24", "2010-04-01", "", "",
     "具体的には、平成22年４月１日（木）です"),
    ("マイナンバー法", "総務省 マイナンバー制度とマイナンバーカード", "soumu_kojinbango03.html", "", "2016-01", "", "", "平成28年1月から、マイナンバーカードの交付が開始されています"),
    ("マイナンバー法", "総務省 平成26年版 情報通信白書 マイナンバー制度の導入に向けて", "soumu_wp_h26_myn.html", "2013-05", "", "", "",
     "平成25年5月に「行政手続における特定の個人を識別するための番号の利用等に関する法律」、いわゆる番号法とその関連法案が成立、公布された"),
    ("会社法", "法務省 会社法の施行に伴う会社登記についてのQ&A", "moj_kaishaho.html", "", "2006-05-01", "", "", "平成１８年５月１日から会社法が施行されました"),
    ("薬事法改正", "厚生労働省 一般用医薬品のインターネット販売について（平成26年7月）", "mhlw_netsales.pdf", "", "2014-06-12", "", "",
     "公布日から６か月以内の政令で定める日（１：平成26年6月12日、２：平成26年4月1日）"),
    ("薬事法改正", "最高裁判所 平成24年(行ヒ)第279号 医薬品ネット販売の権利確認等請求事件 判決", "courts_82895_pdf.pdf", "", "", "", "", "平成２５年１月１１日"),
]
for pol, title, fn, pub, enf, who, role, q in P:
    fn = fn if fn in man else find(fn.rsplit(".", 1)[0] + ".")
    if fn is None:
        bad.append((pol, title, "no file")); continue
    add(pol, "公式ページ", title, fn, pub, enf, who, role, q)

# ---------- 国会会議録: 会議一覧 ----------
kr = json.load(open(LOC + "/kokkai_rows.json", encoding="utf-8"))
for row in kr:
    key, sess, date, house, mtg, issue, murl, pos, _q, apiurl = row
    fn = "kokkai_%s_s%s.json" % (key, sess)
    d = json.load(open(f"{RAW}/{fn}", encoding="utf-8"))
    sp = next((r["speech"] for r in d["speechRecord"] if r["meetingURL"] == murl and r["date"] == date and "議題" in r["speech"]), None)
    q = ""
    if sp:
        i = sp.find("議題")
        seg = sp[max(0, i - 40):i + 3].split("\n")[-1].split("\r")[-1]
        q = seg.lstrip("　")
    add(key, "国会会議録(審議した会議)", "第%s回国会 %s %s %s" % (sess, house, mtg, issue), fn, enf="", pub=date, quote=q, src_text=json.dumps(d, ensure_ascii=False) if False else (sp or ""), url=murl)

# ---------- 国会会議録: 趣旨説明 ----------
SP = [  # 政策, 国会回, speechURL, 引用
    ("携帯電話料金", 198, "119805254X01720190411/41", "電気通信事業法の一部を改正する法律案を提出した趣旨"),
    ("民泊", 193, "119304319X02020170526/167", "住宅宿泊事業法案の提案理由につきまして御説明申し上げます"),
    ("電力小売全面自由化", 186, "118605254X01720140411/7", "電気事業法等の一部を改正する法律案につきまして、その趣旨を御説明申し上げます"),
    ("科学技術基本法", 134, "113403911X00219951031/2", "科学技術基本法案につきまして、その提案理由及び要旨を御説明いたします"),
    ("IT基本法", 150, "115005254X00620001024/14", "高度情報通信ネットワーク社会形成基本法案の趣旨を御説明申し上げます"),
    ("知的財産基本法", 155, "115505254X00520021101/18", "知的財産基本法案につきまして、その趣旨を御説明申し上げます"),
    ("研究開発税制", 156, "115605254X00820030214/3", "所得税法等の一部を改正する法律案の趣旨を御"),
    ("国立大学法人法", 156, "115605254X02020030403/28", "国立大学法人法案"),
    ("資金決済法", 171, "117105254X02120090407/23", "資金決済に関する法律案の趣旨を御説明申し上げます"),
    ("FIT", 177, "117705254X03220110714/14", "電気事業者による再生可能エネルギー電気の調達に関する特別措置法案"),
    ("マイナンバー法", 183, "118305254X01220130322/59", "行政手続における特定の個人を識別するための番号の利用等に関する法律案"),
    ("薬事法改正", 185, "118504260X00820131120/229", "薬事法及び薬剤師法の一部を改正する法律案について、その提案の理由及び内容の概要を説明いたします"),
]
for pol, sess, tail, q in SP:
    url = "https://kokkai.ndl.go.jp/txt/" + tail
    hit = None
    for fn in [k for k in man if k.startswith("kokkai_speaker_%s_s%s_" % (pol, sess))] + [k for k in man if k.startswith("kokkai_%s_s%s" % (pol, sess)) and "speaker" not in k]:
        d = json.load(open(f"{RAW}/{fn}", encoding="utf-8"))
        for r in d.get("speechRecord", []):
            if r["speechURL"] == url:
                hit = (fn, r); break
        if hit: break
    if not hit:
        bad.append((pol, "speech", tail)); continue
    fn, r = hit
    add(pol, "国会会議録(趣旨説明・答弁)", "第%s回国会 %s %s" % (sess, r["nameOfHouse"], r["nameOfMeeting"]), fn, pub=r["date"], who=r["speaker"],
        role=r.get("speakerPosition") or "議員(提出者)", quote=q, src_text=r["speech"], url=url)

hdr = ["政策", "資料の種類", "題名", "URL", "sha256", "取得日", "公布日", "施行日", "人物", "役職", "引用"]
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
print("rows", len(rows))
print("DROPPED(引用不一致/ファイル無し):")
for b in bad: print("  ", b)
