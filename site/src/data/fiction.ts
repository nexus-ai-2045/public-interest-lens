/**
 * デモ専用の創作データ。人物・政策・記録はすべて架空で、実在の議員・法令・統計とは無関係です。
 * 実在データ（GDP）は economy-jpn.json に分けて置き、この配列とは混ぜません。
 */
export type Domain = 'economy' | 'technology';
export type Direction = 'harm' | 'benefit';
export type Role = 'lead' | 'vote' | 'context';

export interface FictionPerson {
  id: string;
  name: string;
  house: '衆議院' | '参議院';
  district: string;
  hue: number;
}

export interface FictionPolicy {
  id: string;
  title: string;
  domain: Domain;
  direction: Direction;
  /** 創作上の影響段階（1〜3）。因果確率や損失額ではありません。 */
  impact: 1 | 2 | 3;
  theme: string;
}

export interface FictionInvolvement {
  personId: string;
  policyId: string;
  role: Role;
  date: string;
  note: string;
}

export const FICTIONAL = true as const;
export const AS_OF = '2026-10-11';

export const people: FictionPerson[] = [
  { id: 'p01', name: '架空議員あおい', house: '衆議院', district: '架空第1区', hue: 210 },
  { id: 'p02', name: '架空議員べに', house: '参議院', district: '架空選挙区A', hue: 350 },
  { id: 'p03', name: '架空議員こはく', house: '衆議院', district: '架空第2区', hue: 35 },
  { id: 'p04', name: '架空議員すみれ', house: '参議院', district: '架空選挙区B', hue: 270 },
  { id: 'p05', name: '架空議員ひすい', house: '衆議院', district: '架空第3区', hue: 150 },
  { id: 'p06', name: '架空議員るり', house: '衆議院', district: '架空第4区', hue: 225 },
  { id: 'p07', name: '架空議員さんご', house: '参議院', district: '架空選挙区C', hue: 10 },
  { id: 'p08', name: '架空議員こがね', house: '衆議院', district: '架空第5区', hue: 48 },
  { id: 'p09', name: '架空議員しろがね', house: '参議院', district: '架空選挙区D', hue: 190 },
  { id: 'p10', name: '架空議員くろがね', house: '衆議院', district: '架空第6区', hue: 0 },
  { id: 'p11', name: '架空議員もえぎ', house: '衆議院', district: '架空第7区', hue: 95 },
  { id: 'p12', name: '架空議員あかね', house: '参議院', district: '架空選挙区E', hue: 330 },
];

export const policies: FictionPolicy[] = [
  { id: 'x-drone', title: '架空の無人機飛行一律禁止法', domain: 'technology', direction: 'harm', impact: 3, theme: '無人機' },
  { id: 'x-share', title: '架空の相乗り配車全面規制', domain: 'technology', direction: 'harm', impact: 3, theme: '配車' },
  { id: 'x-stay', title: '架空の短期宿泊届出過重化', domain: 'economy', direction: 'harm', impact: 2, theme: '宿泊' },
  { id: 'x-net', title: '架空の通信回線参入制限', domain: 'technology', direction: 'harm', impact: 2, theme: '通信' },
  { id: 'x-chip', title: '架空の半導体投資抑制策', domain: 'economy', direction: 'harm', impact: 3, theme: '半導体' },
  { id: 'x-startup', title: '架空の新規参入手続き簡素化', domain: 'economy', direction: 'benefit', impact: 2, theme: '起業' },
  { id: 'x-sandbox', title: '架空の実証特区創設', domain: 'technology', direction: 'benefit', impact: 3, theme: '実証' },
  { id: 'x-rnd', title: '架空の研究開発税額控除拡大', domain: 'economy', direction: 'benefit', impact: 2, theme: '研究開発' },
  { id: 'x-open', title: '架空の行政データ公開義務化', domain: 'technology', direction: 'benefit', impact: 1, theme: 'データ' },
];

export const involvements: FictionInvolvement[] = [
  { personId: 'p10', policyId: 'x-drone', role: 'lead', date: '2024-03-12', note: '架空法案を主導して提出した設定' },
  { personId: 'p10', policyId: 'x-share', role: 'vote', date: '2024-06-20', note: '架空の個人採決で賛成した設定' },
  { personId: 'p10', policyId: 'x-chip', role: 'vote', date: '2025-02-14', note: '架空の個人採決で賛成した設定' },
  { personId: 'p02', policyId: 'x-share', role: 'lead', date: '2024-05-30', note: '架空の規制案を取りまとめた設定' },
  { personId: 'p02', policyId: 'x-stay', role: 'vote', date: '2024-11-08', note: '架空の個人採決で賛成した設定' },
  { personId: 'p07', policyId: 'x-chip', role: 'lead', date: '2025-01-22', note: '架空の抑制策を主導した設定' },
  { personId: 'p07', policyId: 'x-net', role: 'context', date: '2025-04-02', note: '架空団体の所属のみ。採点しない設定' },
  { personId: 'p04', policyId: 'x-net', role: 'lead', date: '2024-09-17', note: '架空の参入制限を主導した設定' },
  { personId: 'p04', policyId: 'x-open', role: 'vote', date: '2025-03-03', note: '架空の個人採決で賛成した設定' },
  { personId: 'p08', policyId: 'x-stay', role: 'lead', date: '2024-07-04', note: '架空の届出強化を主導した設定' },
  { personId: 'p08', policyId: 'x-drone', role: 'vote', date: '2024-03-28', note: '架空の個人採決で賛成した設定' },
  { personId: 'p12', policyId: 'x-drone', role: 'vote', date: '2024-03-28', note: '架空の個人採決で賛成した設定' },
  { personId: 'p12', policyId: 'x-rnd', role: 'vote', date: '2025-05-19', note: '架空の個人採決で賛成した設定' },
  { personId: 'p01', policyId: 'x-sandbox', role: 'lead', date: '2024-10-10', note: '架空の特区創設を主導した設定' },
  { personId: 'p01', policyId: 'x-startup', role: 'vote', date: '2025-01-30', note: '架空の個人採決で賛成した設定' },
  { personId: 'p05', policyId: 'x-rnd', role: 'lead', date: '2025-05-02', note: '架空の税額控除拡大を主導した設定' },
  { personId: 'p05', policyId: 'x-open', role: 'lead', date: '2025-02-11', note: '架空の公開義務化を主導した設定' },
  { personId: 'p06', policyId: 'x-startup', role: 'lead', date: '2024-12-01', note: '架空の手続き簡素化を主導した設定' },
  { personId: 'p06', policyId: 'x-share', role: 'vote', date: '2024-06-20', note: '架空の個人採決で賛成した設定' },
  { personId: 'p09', policyId: 'x-sandbox', role: 'vote', date: '2024-11-21', note: '架空の個人採決で賛成した設定' },
  { personId: 'p09', policyId: 'x-chip', role: 'vote', date: '2025-02-14', note: '架空の個人採決で賛成した設定' },
  { personId: 'p11', policyId: 'x-open', role: 'vote', date: '2025-03-03', note: '架空の個人採決で賛成した設定' },
  { personId: 'p03', policyId: 'x-stay', role: 'context', date: '2024-08-15', note: '架空団体の所属のみ。採点しない設定' },
];
