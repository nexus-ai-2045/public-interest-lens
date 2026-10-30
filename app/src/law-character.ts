/** 法律の性格（規制する／既得権益・業界を守る／新しく整える／その他）を、題名と要約のことばから分ける。
 * 暫定の機械分類：AI や人の確認前。データ側（laws.json）に正式な分類が入ったら置き換える。 */

export const CHARACTERS = ['regulate', 'protect', 'improve', 'other'] as const;
export type Character = typeof CHARACTERS[number];

export const CHARACTER_LABEL: Record<Character, string> = {
  regulate: '規制する法律',
  protect: '既得権益・業界を守る法律',
  improve: '新しく整える・良くする法律',
  other: 'どれとも言えない',
};
export const CHARACTER_SHORT: Record<Character, string> = { regulate: '規制', protect: '既得権益', improve: '整備・向上', other: '分類なし' };

const REGULATE = /規制|取締|禁止|罰則|罰金|処罰|防止|義務|制限|監督|許可|免許|課徴金|是正|適正化|違反/;
const PROTECT = /特例|特別措置|優遇|補助|助成|給付金|補償|救済|保護|支援|緩和|猶予|免除|軽減|延長|存続|保全|維持|協同組合|農業|漁業|郵便|既得/;
const IMPROVE = /整備|推進|促進|創設|新設|振興|向上|充実|改革|拡充|確保|基本法|デジタル|活性化|育成/;

/** 題名と要約を一緒に見る。規制を最優先（同じ法律が「支援」と「義務」を両方含むことが多く、義務の側が実際の拘束だから）。 */
export function characterOf(text: string): Character {
  if (REGULATE.test(text)) return 'regulate';
  if (PROTECT.test(text)) return 'protect';
  if (IMPROVE.test(text)) return 'improve';
  return 'other';
}

export function matchesCharacter(text: string, wanted: ReadonlySet<Character>): boolean {
  return wanted.size === 0 || wanted.has(characterOf(text));
}
