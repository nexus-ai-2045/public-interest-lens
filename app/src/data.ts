import type { AxisValues, EvidenceKind } from "./scoring";

export type Entity = {
  id: string;
  name: string;
  type: string;
  values: AxisValues;
  note: string;
};

export type Evidence = {
  id: string;
  entityId: string;
  date: string;
  title: string;
  kind: EvidenceKind;
  summary: string;
  source: string;
  excerpt: string;
};

export const entities: Entity[] = [
  {
    id: "aoba",
    name: "青葉 未来",
    type: "架空の議員",
    values: { deliberation: 84, proposals: 71, transparency: 92 },
    note: "審議参加と情報公開の公開記録が比較的多い例",
  },
  {
    id: "hokuto",
    name: "北斗 政策会",
    type: "架空の会派",
    values: { deliberation: 68, proposals: 90, transparency: 63 },
    note: "政策提案数が多い一方、公開粒度に未確認が残る例",
  },
  {
    id: "shimin",
    name: "市民連携ラボ",
    type: "架空の団体",
    values: { deliberation: 76, proposals: 78, transparency: 81 },
    note: "複数軸が近い値になる中立的な検証例",
  },
];

export const evidence: Evidence[] = [
  {
    id: "e1",
    entityId: "aoba",
    date: "2026-06-18",
    title: "委員会の出席記録",
    kind: "verified",
    summary: "公開された会議録の出席者欄に記載がある。",
    source: "架空議会 会議録 第18号",
    excerpt: "出席委員として氏名が掲載されている（MVP用の架空引用）。",
  },
  {
    id: "e2",
    entityId: "aoba",
    date: "2026-06-20",
    title: "審議参加率",
    kind: "computed",
    summary: "対象期間の公開出席記録を分母・分子にして算出。",
    source: "公開記録 25件から機械計算",
    excerpt: "出席 21件 ÷ 対象 25件 = 84%。",
  },
  {
    id: "e3",
    entityId: "hokuto",
    date: "2026-05-09",
    title: "政策提案の論点整理",
    kind: "ai",
    summary: "公開提案文から主要論点をAIが整理したもの。内容は誤り得る。",
    source: "架空の政策提案書 4件",
    excerpt: "生活支援と行政効率の両立を重視している可能性がある。",
  },
  {
    id: "e4",
    entityId: "hokuto",
    date: "2026-05-12",
    title: "所属情報の更新日",
    kind: "unknown",
    summary: "掲載ページに更新日の明記がなく、現在状態は確認できない。",
    source: "架空の公開プロフィール",
    excerpt: "次の確認: 公式名簿または管理者への照会。",
  },
  {
    id: "e5",
    entityId: "shimin",
    date: "2026-04-24",
    title: "資料公開の有無",
    kind: "verified",
    summary: "会議ごとの配布資料と更新履歴が公開されている。",
    source: "架空団体 オープンデータ一覧",
    excerpt: "資料、更新日、変更理由が同一ページに掲載されている。",
  },
  {
    id: "e6",
    entityId: "shimin",
    date: "2026-04-25",
    title: "透明性指標",
    kind: "computed",
    summary: "出典、更新日、変更履歴の充足率を同一規則で算出。",
    source: "公開ページ 16件から機械計算",
    excerpt: "必須項目の充足 13件 ÷ 対象 16件 = 81%。",
  },
];
