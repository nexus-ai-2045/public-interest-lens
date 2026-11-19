import { meetsCertaintyFloor } from './scoring-constants';

/** 点数設計 v2.1 §7-1 の型。群の差（記述）と法律単位の額（外部証拠つき）を型で分ける。 */
export type Range = { low: number; median: number; high: number };

/**
 * 産業×期間の群の差（OECD 同産業・同時期の中央値との差）。記述であって因果ではない。
 * 法律の額の欄（lawId・amountYen）を持たず、LawEffect に代入できない。群の差を法律へ配る経路はここに作らない。
 */
export type GroupDiff = { readonly kind: 'group-diff'; group: string; window: string; diff: Range; benchmark: string };

/** 外部証拠のはしご（上ほど強い）。 */
export type EvidenceRung = 'other-country-measured' | 'agency-estimate' | 'industry-statistics' | 'elasticity-times-scale';
export type ExternalEvidence = { rung: EvidenceRung; source: string; url?: string };

declare const lawEffectBrand: unique symbol;
/** 外部証拠つきの法律単位の額。makeLawEffect だけが作る（手書きのオブジェクトは型エラー）。 */
export type LawEffect = {
  readonly kind: 'law-effect';
  readonly lawId: string;
  readonly amountYen: Range;
  readonly certainty: string;
  readonly evidence: ExternalEvidence;
  readonly [lawEffectBrand]: true;
};

export type LawEffectInput = { lawId: string; amountYen: Range; certainty: string; evidence: ExternalEvidence | undefined };

/** 外部証拠が無い、または確かさが下限（中）未満なら作れない（null）。「測定できない」はここで表す。 */
export function makeLawEffect(input: LawEffectInput): LawEffect | null {
  const e = input.evidence;
  if (!e || typeof e.source !== 'string' || !e.source.trim()) return null;
  if (!meetsCertaintyFloor(input.certainty)) return null;
  return Object.freeze({ kind: 'law-effect', lawId: input.lawId, amountYen: Object.freeze({ ...input.amountYen }), certainty: input.certainty, evidence: Object.freeze({ ...e }) }) as unknown as LawEffect;
}
