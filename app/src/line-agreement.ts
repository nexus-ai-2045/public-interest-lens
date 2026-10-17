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

export type TriageLine = { verdict: string; field: string; indicator: string };
export type TriageAgreement = { id: string; agreed: boolean; line1: TriageLine | null; line2: TriageLine | null; reason: string };

/** 系統1（triage.csv：結果・分野・指標）と系統2（labels.csv：系統2_判定・系統2_分野・系統2_指標）を比べる。判定・分野・指標がすべて同じときだけ一致。 */
export function compareTriage(id: string, line1Row: Row | undefined, line2Row: Row | undefined): TriageAgreement {
  const line1 = line1Row ? { verdict: line1Row['結果'], field: line1Row['分野'], indicator: line1Row['指標'] } : null;
  const line2 = line2Row ? { verdict: line2Row['系統2_判定'], field: line2Row['系統2_分野'], indicator: line2Row['系統2_指標'] } : null;
  if (!line1) return { id, agreed: false, line1, line2, reason: '系統1の振り分けが無い' };
  if (!line2) return { id, agreed: false, line1, line2, reason: '系統2の振り分けが無い' };
  if (![line1.verdict, line2.verdict].every(v => v === '評価対象' || v === '評価対象外')) {
    return { id, agreed: false, line1, line2, reason: '振り分けに保留または未定義の判定がある' };
  }
  const diff: string[] = [];
  if (line1.verdict !== line2.verdict) diff.push(`判定（系統1：${line1.verdict}、系統2：${line2.verdict}）`);
  if (line1.field !== line2.field) diff.push(`分野（系統1：${line1.field}、系統2：${line2.field}）`);
  if (line1.indicator !== line2.indicator) diff.push(`指標（系統1：${line1.indicator || 'なし'}、系統2：${line2.indicator || 'なし'}）`);
  return { id, agreed: diff.length === 0, line1, line2, reason: diff.length ? `一致しない：${diff.join('／')}` : '系統1と系統2が一致' };
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

export const TRIAGE_AGREEMENT_HEADER = ['id', '題名', '系統1_判定', '系統1_分野', '系統1_指標', '系統2_判定', '系統2_分野', '系統2_指標', '結果', '理由'];
export function triageAgreementRow(title: string, ag: TriageAgreement): string[] {
  return [ag.id, title, ag.line1?.verdict ?? '', ag.line1?.field ?? '', ag.line1?.indicator ?? '', ag.line2?.verdict ?? '', ag.line2?.field ?? '', ag.line2?.indicator ?? '',
    ag.agreed ? '採用' : '保留', ag.reason];
}
