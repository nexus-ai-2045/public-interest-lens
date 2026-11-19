/**
 * 曝露ランキングの群の表示名。群の ID は「産業コード|年」（未配分）、内訳（cells）は産業コードだけ（年を足した束）。
 * 産業コードは OECD 表6（ISIC Rev.4 の大分類。M+N のような節の足し算を含む）。表に無いコードはそのまま出す。
 */
export const ISIC_SECTION_NAMES: Readonly<Record<string, string>> = Object.freeze({
  A: '農林水産業',
  B: '鉱業',
  C: '製造業',
  D: '電気・ガス',
  E: '水道・廃棄物処理',
  F: '建設業',
  G: '卸売・小売業',
  H: '運輸・郵便業',
  I: '宿泊・飲食サービス業',
  J: '情報通信業',
  K: '金融・保険業',
  L: '不動産業',
  'M+N': '専門・科学技術、業務支援サービス業',
  O: '公務',
  P: '教育',
  Q: '保健衛生・社会事業',
  'R+S': '芸術・娯楽、その他のサービス',
  _T: '全産業',
});

export const industryName = (code: string): string => ISIC_SECTION_NAMES[code] ?? code;

/** 群の一覧（id・産業コード・年）から、画面部品の群ラベル（id → 産業名＋期間）を作る。産業コードだけの束（内訳）は「全期間の合計」。 */
export function exposureGroupLabels(groups: readonly { id: string; group: string; window: string }[]): { id: string; group: string; window: string }[] {
  const labels = groups.map(g => ({ id: g.id, group: industryName(g.group), window: g.window }));
  for (const code of new Set(groups.map(g => g.group))) labels.push({ id: code, group: industryName(code), window: '各年の合計' });
  return labels;
}
