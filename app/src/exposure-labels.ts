/**
 * 曝露ランキングの画面に渡す表示用の名前と読み。額・人物ID・階層の決め方には使わない（並びと表示だけ）。
 *
 * - 産業名：群の産業は OECD 表6（ISIC Rev.4 の節）の記号（data/derived/exposure-v1/industry-year.csv の「産業」列）。
 *   ここで日本語の名前にする。表に無い記号はそのまま出す。
 * - 読み（作るのは exposure-inputs.ts の personReadingsOf）：人物台帳 data/derived/person-ids/persons.csv の読み（現職の名簿由来）を先に使い、空なら
 *   国会会議録の発言者の読み data/acquired/diet-roster/readings-kokkai.csv（scripts/fetch_person_readings.py）で埋める。
 *   どちらにも無い人は読みなし（画面では読みのある人の後に名前の文字の順）。
 */

/** ISIC Rev.4 の節（OECD 表6の産業）→ 日本語の名前。足した節（M+N、R+S）と全産業（_T）を含む。 */
export const INDUSTRY_NAMES: Readonly<Record<string, string>> = {
  A: '農林水産業',
  B: '鉱業',
  C: '製造業',
  D: '電気・ガス・蒸気・空調',
  F: '建設業',
  G: '卸売・小売業',
  H: '運輸・保管',
  I: '宿泊・飲食サービス',
  J: '情報通信',
  K: '金融・保険',
  L: '不動産業',
  'M+N': '専門・科学技術、業務支援サービス',
  P: '教育',
  Q: '保健衛生・社会事業',
  'R+S': 'その他のサービス',
  _T: '全産業',
};

export const industryName = (code: string): string => INDUSTRY_NAMES[code] ?? code;

/**
 * 群の ID → 表示名。内訳（cells）の ID は産業の記号（例：A）で「農林水産業」、
 * 未配分の ID は産業×年（例：A|1998）で「農林水産業（1998年）」にする。
 */
export function exposureGroupNames(groups: readonly { id: string; group: string; window: string }[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const g of groups) {
    out[g.group] = industryName(g.group);
    out[g.id] = `${industryName(g.group)}（${g.window}）`;
  }
  return out;
}

const KANA = /^[ぁ-ゖ゛゜ー]+$/;
/** 読みの表記をそろえる：空白を除く。ひらがな（と長音・濁点の記号）だけでなければ読みなしとする。 */
export const normalizeReading = (reading: string): string => {
  const r = (reading ?? '').replace(/\s+/g, '');
  return KANA.test(r) ? r : '';
};
