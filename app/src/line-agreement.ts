/**
 * 設計決定0007「2系統の AI が一致したものだけ採用し、不一致は保留」を、AI の判断の段階にかける処理。
 * - 目的の分類（benefit-v1）：系統1＝`benefit-classification.ts` の classifyLaw（その中の系統A・系統Bの一致）。
 *   系統2＝`data/derived/benefit-v1-line2/labels.csv`（別のセッションが系統1を見ずに付けた）。
 * - 振り分け（bill-triage-v1）：系統1＝`data/derived/bill-triage-v1/triage.csv`。系統2＝`data/derived/bill-triage-v1-line2/labels.csv`。
 * 一致しなければ、系統2が無い場合も含めて保留にする（人へ回さない）。系統2で系統1を上書きすることはしない。
 * 数値は扱わない。人物・採決・役職のデータは読まない。
 */
import type { Row } from './impact-batch';
import type { LawResult } from './impact-batch';
import type { Classification } from './benefit-classification';
import { FIELDS, FIELD_WORDS, NO_FIELD, PICK_TABLES, findWord, firstLawTitle, pickIndicator, type Field } from './indicator-pick';

// ---- 目的の分類 ----

export type BenefitLine2 = { kinds: string[]; directionConflict: boolean };

/** labels.csv の行 → 系統2のラベル。種類は「・」区切り、空は目的の記述なし。 */
export function parseBenefitLine2(rows: Row[]): Map<string, BenefitLine2> {
  return new Map(rows.map(r => [r.id, {
    kinds: r['系統2_種類'].split('・').map(s => s.trim()).filter(Boolean),
    directionConflict: r['系統2_向きの矛盾'] === '抑える',
  }]));
}

const sameSet = (x: string[], y: string[]) => {
  const a = [...new Set(x)].sort(), b = [...new Set(y)].sort();
  return a.length === b.length && a.every((v, i) => v === b[i]);
};

export type BenefitAgreementStatus = '一致' | '不一致' | '系統1が保留' | '系統2なし';
export type BenefitAgreement = {
  status: BenefitAgreementStatus;
  /** 系統1の種類（系統1が保留なら null）。 */
  line1: string[] | null;
  line1Conflict: boolean | null;
  line2: BenefitLine2 | null;
  kindsMatch: boolean | null;
  conflictMatch: boolean | null;
  reason: string;
};

/**
 * 系統1（classifyLaw の結果）と系統2を比べる。
 * 系統1の種類は、系統A・Bが一致したときの集合（kinds）。空集合（目的の記述なし）も1つの判断として比べる。
 * 系統1の向きの矛盾は、系統A・Bが一致したときだけ値を持つ。
 */
export function compareBenefitLines(c: Classification, line2: BenefitLine2 | undefined): BenefitAgreement {
  const line1 = c.kinds;
  const line1Conflict = c.b && c.a.directionConflict === c.b.directionConflict ? c.a.directionConflict : null;
  if (!line2) return { status: '系統2なし', line1, line1Conflict, line2: null, kindsMatch: null, conflictMatch: null, reason: '系統2のラベルが無い' };
  if (line1 === null) return { status: '系統1が保留', line1, line1Conflict, line2, kindsMatch: null, conflictMatch: null, reason: `系統1が保留（${c.holdReason ?? '理由なし'}）` };
  const kindsMatch = sameSet(line1, line2.kinds);
  const conflictMatch = line1Conflict !== null && line1Conflict === line2.directionConflict;
  const agreed = kindsMatch && conflictMatch;
  const show = (k: string[]) => k.length ? [...k].sort().join('・') : 'なし';
  const reason = agreed ? '系統1と系統2が一致'
    : [!kindsMatch && `種類が一致しない（系統1：${show(line1)}、系統2：${show(line2.kinds)}）`,
      !conflictMatch && `向きの矛盾が一致しない（系統1：${line1Conflict === null ? '不定' : line1Conflict ? '抑える' : 'なし'}、系統2：${line2.directionConflict ? '抑える' : 'なし'}）`].filter(Boolean).join('／');
  return { status: agreed ? '一致' : '不一致', line1, line1Conflict, line2, kindsMatch, conflictMatch, reason };
}

/**
 * 一致したものだけ採用する。系統1が採用した種類でも、系統2と一致しない（または系統2が無い）なら保留（kinds=null）に替える。
 * 系統1が保留なら、そのまま保留（系統2で埋めない）。
 */
export function adoptAgreed(c: Classification, ag: BenefitAgreement): Classification {
  if (ag.status === '一致' || c.kinds === null) return c;
  return { ...c, kinds: null, directionConflict: false, holdReason: `2系統（設計決定0007）が一致しない：${ag.reason}` };
}

export const AGREEMENT_HEADER = ['id', '題名', '系統1_種類', '系統1_向きの矛盾', '系統2_種類', '系統2_向きの矛盾', '種類の一致', '向きの矛盾の一致', '結果', '理由'];
export function agreementRow(id: string, title: string, ag: BenefitAgreement): string[] {
  const k = (x: string[] | null) => x === null ? '保留' : x.length ? [...x].sort().join('・') : 'なし';
  const yn = (b: boolean | null) => b === null ? '' : b ? '抑える' : 'なし';
  const m = (b: boolean | null) => b === null ? '' : b ? '一致' : '不一致';
  return [id, title, k(ag.line1), yn(ag.line1Conflict), ag.line2 ? k(ag.line2.kinds) : '', ag.line2 ? yn(ag.line2.directionConflict) : '',
    m(ag.kindsMatch), m(ag.conflictMatch), ag.status === '一致' ? '採用' : '保留', ag.reason];
}

// ---- 振り分け ----

export type TriageLine = { verdict: string; field: string; indicator: string; kind?: string; reason?: string; rules?: string };
export type TriageAgreement = {
  id: string; agreed: boolean; line1: TriageLine | null; line2: TriageLine | null; reason: string;
  /** 一致しなかった行の区分（解消した行も、解消前の区分を残す）。一致した行は空。 */
  category: string;
  /** v2.1 の解消規則（HR3・HR4）で採用した振り分け。解消していなければ null。 */
  resolved: TriageLine | null;
  rule: string;
};

export const HOLD_CATEGORIES = ['系統欠落', '同位置の分野競合（D5）', '入力値が未定義（D5）', '種類の食い違い（組織手続と実質改正）', '判定の食い違い（分野・指標は一致）', '対応表なしと分野の食い違い', '別々の分野の食い違い', '同じ分野で指標の食い違い', 'その他'] as const;

/** 一致しなかった2系統の振り分けの区分。 */
export function holdCategory(line1: TriageLine | null, line2: TriageLine | null): string {
  if (!line1 || !line2) return '系統欠落';
  const holds = [line1, line2].filter(l => l.verdict === '保留');
  if (holds.length) return holds.some(l => (l.reason ?? '').includes('競合')) ? '同位置の分野競合（D5）' : '入力値が未定義（D5）';
  if (line1.field === line2.field) return line1.verdict !== line2.verdict ? '判定の食い違い（分野・指標は一致）' : line1.indicator !== line2.indicator ? '同じ分野で指標の食い違い' : 'その他';
  if ([line1.field, line2.field].includes(NO_FIELD)) return '対応表なしと分野の食い違い';
  return '別々の分野の食い違い';
}

/** 各系統の振り分け（indicator-pick.ts / triage_v2_line2.py）の中で当てる v2.1 の規則。 */
const HR_TRIAGE_NOTES: Record<string, { category: string; note: string }> = {
  HR1: { category: '同位置の分野競合（D5）', note: 'HR1：同じ位置で競合した語のうち、他の語の一部でない最長の語の分野を採った' },
  HR2: { category: '種類の食い違い（組織手続と実質改正）', note: 'HR2：機構法等の一部改正を実質改正に直した' },
};

/** 分野の表の中での指標の順位（上の行ほど小さい。既定は最後）。表にない指標は null。 */
function indicatorRank(field: Field, indicator: string): number | null {
  const t = PICK_TABLES[field];
  const i = t.rules.findIndex(r => r.indicator === indicator);
  if (i >= 0) return i;
  return indicator === t.default ? t.rules.length : null;
}

export type TriageResolution = { rule: 'HR3' | 'HR4'; line: TriageLine; reason: string } | { rule: ''; reason: string };

/**
 * v2.1 の解消規則（docs は data/derived/bill-triage-v2/spec.md）。両系統とも判定が定義済み（評価対象／評価対象外）で食い違うときだけ使う。
 * HR3：同じ分野で指標だけ違う → 分野ごとの固定の優先順（分野の表の上の行ほど先、既定は最後）で先のものを採る。判定が同じときだけ。
 * HR4：片方が対応表なし、もう片方が分野Fを名指し → 種類が同じで、題名（最初の法律）にFの直接の語があるときだけFを採る。判定は種類から決め直す。
 * どちらにも当たらなければ解消せず、保留のまま理由を返す。法律ごとの人の判断は入れない。
 */
export function resolveTriageDiff(title: string, l1: TriageLine, l2: TriageLine): TriageResolution {
  const defined = (l: TriageLine) => l.verdict === '評価対象' || l.verdict === '評価対象外';
  if (!defined(l1) || !defined(l2)) return { rule: '', reason: '片方の系統が保留（入力値が未定義、または同位置の競合）のため解消しない' };
  const isField = (f: string): f is Field => (FIELDS as readonly string[]).includes(f);
  if (l1.field === l2.field && isField(l1.field) && l1.indicator !== l2.indicator) {
    if (l1.verdict !== l2.verdict) return { rule: '', reason: 'HR3に当たらない：指標も判定も食い違う' };
    const r1 = indicatorRank(l1.field, l1.indicator), r2 = indicatorRank(l1.field, l2.indicator);
    if (r1 === null || r2 === null) return { rule: '', reason: 'HR3に当たらない：指標が分野の表にない' };
    const [win, lose, wn, ln] = r1 <= r2 ? [l1, l2, '系統1', '系統2'] as const : [l2, l1, '系統2', '系統1'] as const;
    return { rule: 'HR3', line: { ...win }, reason: `HR3：同じ分野「${win.field}」で指標が違う（${wn}：${win.indicator}、${ln}：${lose.indicator}）ため、分野の表の上の行の${win.indicator}を固定の優先順で採る` };
  }
  const one = [l1, l2].filter(l => l.field === NO_FIELD), other = [l1, l2].filter(l => l.field !== NO_FIELD);
  if (one.length === 1 && other.length === 1 && isField(other[0].field)) {
    const f = other[0].field;
    if (!l1.kind || !l2.kind || l1.kind !== l2.kind) return { rule: '', reason: 'HR4に当たらない：2系統の種類が同じと確かめられない' };
    const seg = firstLawTitle(title);
    const word = FIELD_WORDS[f].find(w => findWord(seg, w) >= 0);
    if (!word) return { rule: '', reason: `HR4に当たらない：題名に分野「${f}」の直接の語が無い` };
    const p = pickIndicator(f, seg);
    const verdict = l1.kind === '定型改正' || l1.kind === '組織手続' ? '評価対象外' : '評価対象';
    return { rule: 'HR4', line: { verdict, field: f, indicator: p.indicator, kind: l1.kind }, reason: `HR4：片方が対応表なしで、題名に分野「${f}」の直接の語「${word}」があるため分野を採り、指標は${p.rule}で${p.indicator}` };
  }
  return { rule: '', reason: 'v2.1の解消規則（HR3・HR4）に当たらない' };
}

/**
 * 系統1（triage.csv／labels-line1.csv：結果・分野・指標・種類・理由）と系統2（labels.csv／labels-line2.csv：系統2_判定・系統2_分野・系統2_指標・系統2_種類・系統2_理由）を比べる。
 * 判定・分野・指標がすべて同じときだけ一致。title を渡したとき（v2）は、食い違いに v2.1 の解消規則を当て、当たったものは採用する（resolved・rule に残す）。
 */
/**
 * 第3の判定者（R2、bill-triage-v2/tiebreak-lines.csv）の決定を当てる。2系統の出力のどちらかを選ぶだけで、新しい値は作らない。
 * 選んだ系統の判定が評価対象か評価対象外で、評価対象なら分野と指標があるときだけ採用する。それ以外（保留を選んだ・選んだ系統が保留）は採用しない。
 */
export function applyLineTiebreak(line1: TriageLine | null, line2: TriageLine | null, tb: Row | undefined): { line: TriageLine; reason: string } | null {
  // 独立した2つの判定（Haiku 2系統）が一致した決定だけを採る。Sonnet・Opus の単独の決定は保留のまま（ADR 0007）
  if (!tb || tb['決め方'] !== '一致') return null;
  const line = tb['採用'] === '系統1' ? line1 : tb['採用'] === '系統2' ? line2 : null;
  if (!line || !(line.verdict === '評価対象外' || (line.verdict === '評価対象' && line.field && line.indicator))) return null;
  return { line: { ...line }, reason: `TB2：第3の判定者が${tb['採用']}を採った（${tb['決め方']}：${tb['理由']}）` };
}

export function compareTriage(id: string, line1Row: Row | undefined, line2Row: Row | undefined, title?: string, tiebreak?: Row): TriageAgreement {
  const line1 = line1Row ? { verdict: line1Row['結果'], field: line1Row['分野'], indicator: line1Row['指標'], kind: line1Row['種類'], reason: line1Row['理由'], rules: line1Row['規則'] } : null;
  const line2 = line2Row ? { verdict: line2Row['系統2_判定'], field: line2Row['系統2_分野'], indicator: line2Row['系統2_指標'], kind: line2Row['系統2_種類'], reason: line2Row['系統2_理由'], rules: line2Row['系統2_規則'] } : null;
  const base = { id, line1, line2, resolved: null as TriageLine | null, rule: '' };
  if (!line1) return { ...base, agreed: false, category: holdCategory(line1, line2), reason: '系統1の振り分けが無い' };
  if (!line2) return { ...base, agreed: false, category: holdCategory(line1, line2), reason: '系統2の振り分けが無い' };
  if (![line1.verdict, line2.verdict].every(v => v === '評価対象' || v === '評価対象外')) {
    const why = [line1, line2].map((l, i) => l.verdict === '保留' && l.reason ? `系統${i + 1}：${l.reason}` : '').filter(Boolean).join('／');
    const detail = `振り分けに保留または未定義の判定がある${why ? '（' + why + '）' : ''}`;
    const tb = title !== undefined ? applyLineTiebreak(line1, line2, tiebreak) : null;
    if (tb) return { ...base, agreed: true, category: holdCategory(line1, line2), resolved: tb.line, rule: 'TB2', reason: `${detail}→${tb.reason}` };
    return { ...base, agreed: false, category: holdCategory(line1, line2), reason: detail };
  }
  const diff: string[] = [];
  if (line1.verdict !== line2.verdict) diff.push(`判定（系統1：${line1.verdict}、系統2：${line2.verdict}）`);
  if (line1.field !== line2.field) diff.push(`分野（系統1：${line1.field}、系統2：${line2.field}）`);
  if (line1.indicator !== line2.indicator) diff.push(`指標（系統1：${line1.indicator || 'なし'}、系統2：${line2.indicator || 'なし'}）`);
  if (diff.length === 0) {
    // 各系統の振り分けの中で v2.1 の規則（HR1・HR2）を使って一致した行は、規則と理由を残す。
    const used = [...new Set([line1, line2].flatMap(l => (l.rules ?? '').split('／')).filter(r => r in HR_TRIAGE_NOTES))].sort();
    if (!used.length) return { ...base, agreed: true, category: '', reason: '系統1と系統2が一致' };
    return { ...base, agreed: true, category: HR_TRIAGE_NOTES[used[0]].category, rule: used.join('／'),
      reason: `系統1と系統2が一致（解消前は保留または食い違い。${used.map(r => HR_TRIAGE_NOTES[r].note).join('、')}）` };
  }
  const category = holdCategory(line1, line2);
  const detail = `一致しない：${diff.join('／')}`;
  if (title !== undefined) {
    const res = resolveTriageDiff(title, line1, line2);
    if (res.rule) return { ...base, agreed: true, category, resolved: res.line, rule: res.rule, reason: `${detail}→${res.reason}` };
    const tb = applyLineTiebreak(line1, line2, tiebreak);
    if (tb) return { ...base, agreed: true, category, resolved: tb.line, rule: 'TB2', reason: `${detail}。${res.reason}→${tb.reason}` };
    return { ...base, agreed: false, category, reason: `${detail}。${res.reason}` };
  }
  return { ...base, agreed: false, category, reason: detail };
}

export const HELD_BY_TRIAGE = '保留（2系統の振り分けが一致しない）';

/** 振り分けが一致しない法律の impact-v1 の行を保留にする。判定ルールの計算結果は理由欄に残すが、段階・向きは採用しない。 */
export function holdByTriage(r: LawResult, ag: TriageAgreement, referenceSource: '系統1' | '系統2' | '入力' = '系統1'): LawResult {
  if (ag.agreed) return r;
  const reference = referenceSource === '入力' ? '参考計算なし：両系統の分野・指標が無い'
    : `参考：${referenceSource}の分野・指標での判定は${r.verdict}${r.direction ? '・' + r.direction : ''}`;
  return { ...r, verdict: HELD_BY_TRIAGE, direction: '', cross: r.cross === '系列なし' ? r.cross : `保留（参考：${r.cross}）`,
    reason: `設計決定0007：${ag.reason}。採用しない（${reference}）／${r.reason}` };
}

export const TRIAGE_AGREEMENT_HEADER = ['id', '題名', '系統1_判定', '系統1_分野', '系統1_指標', '系統2_判定', '系統2_分野', '系統2_指標', '結果', '理由', '解消規則', '食い違いの区分'];
export function triageAgreementRow(title: string, ag: TriageAgreement): string[] {
  return [ag.id, title, ag.line1?.verdict ?? '', ag.line1?.field ?? '', ag.line1?.indicator ?? '', ag.line2?.verdict ?? '', ag.line2?.field ?? '', ag.line2?.indicator ?? '',
    ag.agreed ? '採用' : '保留', ag.reason, ag.rule, ag.category];
}
