/**
 * 法律の目的（第1条）から便益の種類を付ける2系統（benefit-rule-v1 の流れ 1〜3。設計決定0007：AI 2系統が一致したものだけ使う）。
 * - 系統A：語の対応表（下の RULES_A）を第1条の原文に機械的に当てる。法律ごとの調整はしない。
 * - 系統B：第1条を読んで、直接の目的（「…により…を図り」）と最終の目的（「もって…目的とする」）から種類を付けた読み（下の READINGS_B）。
 *   系統Aの結果を見る前に書いた。背景として挙げる事情（「…に鑑み」）は目的に数えない、手段として税・交付金・財源を設けるなら「移転」を付ける、という方針で読んだ。
 * 2系統の種類の集合が一致しなければ保留（未測定、公開不可）。どちらの系統も同じ AI（同じセッション）が書いたもので、独立性は限られる（spec.md に記載）。
 * 数値は扱わない。人物・採決・役職のデータは読まない。
 */
import type { Row } from './impact-batch';

export type PurposeText = { targetId: string; lawName: string; version: '施行時' | '現行'; text: string; url: string };
export type LinePick = { kinds: string[]; quotes: string[]; directionConflict: boolean };

/** 他の法律の題名の引用（「…法（昭和二十九年法律第百号）」）は目的ではないので、系統Aでは当てる前に取り除く。決まり文句の「公共の福祉」も除く。 */
export function preprocessA(text: string): string {
  return text.replace(/^（[^）]*）\s*/, '').replace(/[^、。「」（）]*法(律)?（[^）]*号）/g, '').replace(/公共の福祉/g, '');
}

/** 系統Aの語の対応表。提案 2-4 の便益の種類の語彙から作った。 */
export const RULES_A: { kind: string; pattern: RegExp }[] = [
  { kind: '経済（内包）', pattern: /国民経済|我が国経済|地域経済|経済社会の(活力|発展)|資金調達|資金供給|金融の円滑|収益性|国際競争力|能率的な利用|産業の(発展|振興)/ },
  { kind: '経済（付加価値の外）', pattern: /海外において|海外における|海外の/ },
  { kind: '消費者保護', pattern: /消費者|顧客|投資者|預金者|購入者|利用者の(利益|保護)/ },
  { kind: '金融の安定', pattern: /信用の維持|信用秩序|金融システムの安定|金融機関の(破綻|健全)/ },
  { kind: '安全（事故）', pattern: /事故|災害の防止|労働災害|火災/ },
  { kind: '安全（犯罪）', pattern: /犯罪|サイバーセキュリティ|不正アクセス|治安/ },
  { kind: 'プライバシー', pattern: /個人情報|プライバシー|個人の権利利益/ },
  { kind: '環境', pattern: /環境の保全|温室効果ガス|公害|地球温暖化/ },
  { kind: '移転', pattern: /税|財政|財源|交付金|補助金/ },
  { kind: '対応表外（安全保障）', pattern: /安全保障|国際社会の平和/ },
  { kind: '対応表外（福祉）', pattern: /障害者|高齢者|福祉/ },
  { kind: '対応表外（国際交流）', pattern: /国際交流|理解の増進/ },
];
/** 系統Aの向きの矛盾：損失額の指標が貸出残高で、第1条が禁止・制限・取締りを定めるとき「抑える」。 */
const CONFLICT_A = /してはならない|の制限|取締り/;
const LENDING = '貸出残高';

const snippet = (text: string, m: RegExpExecArray) => text.slice(Math.max(0, m.index - 12), m.index + m[0].length + 12).replace(/\s+/g, '');

export function classifyA(texts: PurposeText[], indicator: string): LinePick {
  const kinds = new Set<string>(), quotes: string[] = [];
  let conflict = false;
  for (const t of texts) {
    const body = preprocessA(t.text);
    for (const r of RULES_A) {
      const m = r.pattern.exec(body);
      if (m) { kinds.add(r.kind); quotes.push(`${r.kind}←「${snippet(body, m)}」`); }
    }
    if (indicator === LENDING && CONFLICT_A.test(t.text.replace(/[^、。「」（）]*法(律)?（[^）]*号）/g, ''))) conflict = true;
  }
  return { kinds: [...kinds].sort(), quotes, directionConflict: conflict };
}

/** 系統Bの読み。quotes は第1条から引用した文字列。 */
export const READINGS_B: Record<string, LinePick & { note: string }> = {
  '参法-145-9': { kinds: ['経済（内包）'], quotes: ['企業の資金調達の機動性の増大を図り、もって国民経済の健全な発展に資する'], directionConflict: false, note: '融資枠の手数料の特例で資金調達を容易にする。貸出を増やす向きで、指標と矛盾しない' },
  '衆法-147-33': { kinds: ['経済（内包）', '金融の安定'], quotes: ['国民大衆のために金融の円滑を図り', '信用の維持と預金者等の保護に資する'], directionConflict: false, note: '預金者の保護は信用金庫の信用の維持（破綻の抑制）を通じた保護と読み、金融の安定に含めた' },
  '衆法-147-34': { kinds: ['消費者保護'], quotes: ['何人も、不特定且つ多数の者に対し…出資金の受入をしてはならない'], directionConflict: true, note: '第1条は目的規定ではなく出資金の受入の禁止。元本の払戻しを約束する出資の勧誘から一般の人を守る規定と読んだ。法律全体が預り金と金利を取り締まり、貸出の一部を抑える向き' },
  '閣法-147-77': { kinds: ['経済（内包）', '消費者保護'], quotes: ['有価証券の発行及び金融商品等の取引等を公正にし', 'もつて国民経済の健全な発展及び投資者の保護に資する'], directionConflict: false, note: '投資者は金融商品の買い手なので消費者保護に含めた。市場の公正・価格形成は経済の効果' },
  '閣法-147-89': { kinds: ['経済（内包）', '消費者保護'], quotes: ['金融サービスの提供等を受ける顧客等の保護', 'もって国民経済の健全な発展に資する'], directionConflict: false, note: '現行の第1条は施行後に加わった目的（金融サービス仲介業・資産形成）を含む' },
  '衆法-151-30': { kinds: ['経済（内包）'], quotes: ['企業の資金調達の機動性の増大を図り、もって国民経済の健全な発展に資する'], directionConflict: false, note: '参法-145-9 と同じ法律の改正' },
  '衆法-186-35': { kinds: ['安全（犯罪）', '対応表外（安全保障）', '経済（内包）'], quotes: ['サイバーセキュリティに対する脅威の深刻化', 'もって経済社会の活力の向上及び持続的発展並びに国民が安全で安心して暮らせる社会の実現', '国際社会の平和及び安全の確保並びに我が国の安全保障に寄与する'], directionConflict: false, note: 'サイバー攻撃の被害の抑制を安全（犯罪）とした。安全保障は対応表に無い種類' },
  '衆法-189-20': { kinds: ['移転', '経済（内包）'], quotes: ['観光及び地域経済の振興に寄与する', '財政の改善に資する'], directionConflict: false, note: '財政の改善（納付金・税収）は移転。秩序の維持・依存の防止は第1条に無い' },
  '閣法-189-27': { kinds: ['経済（付加価値の外）', '経済（内包）'], quotes: ['海外において通信・放送・郵便事業を行う者等に対し資金供給その他の支援を行う', '我が国の事業者の収益性の向上等を図り、もって我が国経済の持続的な成長に寄与する'], directionConflict: false, note: '国内の事業者の収益は付加価値に内包されるが、海外の出資先から得る所得は国内の付加価値（GDP）に入らない' },
  '閣法-196-2': { kinds: ['移転'], quotes: ['国際観光旅客税について、納税義務者、課税の対象、税率、納付の手続'], directionConflict: false, note: '税の手続を定める趣旨規定。税収は移転' },
  '閣法-196-4': { kinds: ['移転', '経済（内包）'], quotes: ['国際観光の振興に資する施策に必要な経費の財源に関する特別の措置を講ずる', 'もって我が国の観光及びその関連産業の国際競争力の強化並びに地域経済の活性化その他の地域の活力の向上に寄与する'], directionConflict: false, note: '理解の増進・国際交流の拡大は「…に鑑み」の背景で、最終の目的は観光産業と地域経済' },
  '閣法-201-24': { kinds: ['経済（内包）'], quotes: ['長期の事業資金を必要とする者に対する資金供給の円滑化及び金融機能の高度化に寄与する'], directionConflict: false, note: '資金の供給は貸出の系列に内包' },
  '閣法-201-27': { kinds: ['移転', '対応表外（福祉）'], quotes: ['電話リレーサービスの提供の業務に要する費用に充てるための交付金の交付等', '聴覚障害者等の自立した日常生活及び社会生活の確保に寄与し'], directionConflict: false, note: '障害者の社会参加は対応表に無い種類。交付金は移転' },
  '閣法-204-2': { kinds: [], quotes: ['国立研究開発法人情報通信研究機構の名称、目的、業務の範囲等に関する事項を定める'], directionConflict: false, note: '組織法の第1条で、政策の目的の記述が無い' },
  '閣法-210-20': { kinds: ['経済（内包）'], quotes: ['電波の公平且つ能率的な利用を確保することによつて'], directionConflict: false, note: '情報通信研究機構法の第1条は目的の記述が無い。電波法の能率的な利用は通信業の付加価値に内包' },
};

export type Classification = {
  texts: PurposeText[];
  flags: string[];
  a: LinePick;
  b: (LinePick & { note: string }) | null;
  agreed: boolean;
  /** 一致したときの種類。不一致・原文なしは null。 */
  kinds: string[] | null;
  directionConflict: boolean;
  /** kinds が null か空のときの理由。 */
  holdReason: string | null;
};

const sameSet = (x: string[], y: string[]) => x.length === y.length && [...x].sort().every((v, i) => v === [...y].sort()[i]);

/**
 * purposes.csv の行から1法律の第1条を選ぶ。改正対象ごとに施行時の版を優先し、無ければ現行の版を使って印を付ける。
 */
export function pickPurposes(rows: Row[], id: string, title: string): { texts: PurposeText[]; flags: string[] } {
  const mine = rows.filter(r => r.id === id);
  const targets = [...new Set(mine.map(r => r['対象法令ID']))].sort();
  const texts: PurposeText[] = [], flags: string[] = [];
  for (const t of targets) {
    const at = mine.find(r => r['対象法令ID'] === t && r['版'] === '施行時' && r['取得状況'] === '取得' && r['第1条の原文'].trim());
    const now = mine.find(r => r['対象法令ID'] === t && r['版'] === '現行' && r['取得状況'] === '取得' && r['第1条の原文'].trim());
    const use = at ?? now;
    if (!use) { flags.push(`${mine.find(r => r['対象法令ID'] === t)?.['対象法令名'] ?? t}の第1条が取得できず`); continue; }
    if (!at) flags.push(`${use['対象法令名']}：施行時の版が無いため現行の版を使用（施行後の改正を含みうる）`);
    const heading = /^（([^）]*)）/.exec(use['第1条の原文'])?.[1] ?? '';
    if (!/目的|趣旨/.test(heading)) flags.push(`${use['対象法令名']}：第1条が目的規定でない（見出し「${heading}」）`);
    texts.push({ targetId: t, lawName: use['対象法令名'], version: at ? '施行時' : '現行', text: use['第1条の原文'], url: use['出典URL'] });
  }
  const amended = (title.match(/の一部を改正する法律/g) ?? []).length;
  if (amended > targets.length) flags.push(`題名の改正対象${amended}本のうち、第1条があるのは${targets.length}本`);
  return { texts, flags };
}

export function classifyLaw(rows: Row[], law: { id: string; title: string; indicator: string }, readings: Record<string, LinePick & { note: string }> = READINGS_B): Classification {
  const { texts, flags } = pickPurposes(rows, law.id, law.title);
  const a = classifyA(texts, law.indicator);
  const b = readings[law.id] ?? null;
  if (!texts.length) return { texts, flags, a, b, agreed: false, kinds: null, directionConflict: false, holdReason: '第1条の原文が無い' };
  if (!b) return { texts, flags, a, b, agreed: false, kinds: null, directionConflict: false, holdReason: '系統Bの読みが無い' };
  const agreed = sameSet(a.kinds, b.kinds);
  const conflictAgreed = a.directionConflict === b.directionConflict;
  if (!agreed) return { texts, flags, a, b, agreed, kinds: null, directionConflict: false, holdReason: `2系統の種類が一致しない（A：${a.kinds.join('・') || 'なし'}、B：${b.kinds.join('・') || 'なし'}）` };
  if (!a.kinds.length) return { texts, flags, a, b, agreed, kinds: [], directionConflict: false, holdReason: '第1条に便益にあたる目的の記述が無い' };
  return { texts, flags, a, b, agreed, kinds: [...a.kinds].sort(), directionConflict: conflictAgreed && a.directionConflict, holdReason: conflictAgreed ? null : '向きの矛盾の判定が2系統で一致しない' };
}
