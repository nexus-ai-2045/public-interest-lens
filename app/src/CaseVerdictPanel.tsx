import { useEffect, useState } from 'react';
import { FINANCIAL_REVIVAL_DRAFT, TABLE1_NPL_RATIO } from './case-evaluation';
import type { CaseVerdict } from './case-verdict';

const STAGE_LABEL: Record<1 | 2 | 3, string> = { 1: '限定的', 2: '中程度', 3: '大きい' };
const signed = (n: number, digits: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(digits)}`;
const HOLD_NOTE: Record<string, string> = { '人物照合が未検証です': '在職記録が未確認のため保留。2002年の副大臣と2005年の大臣が同一人物かを、公式の在職記録で確かめられていません。', '行動または引用が未検証です': '役割が背景（context）のため点数にしません。' };

/** 判定結果の表示。数値はすべて CaseVerdict（判定ルールと根拠評価の計算結果）から出し、ここには直書きしない。 */
export function CaseVerdictView({ verdict }: { verdict: CaseVerdict }) {
  const { judgement: j, persons, table1: t, series } = verdict;
  const spec = FINANCIAL_REVIVAL_DRAFT;
  const a = spec.assessments[0];
  const f = TABLE1_NPL_RATIO;
  return <section className="case-verdict lower-panel" aria-labelledby="case-verdict-title">
    <h4 id="case-verdict-title">判定結果{j.stage !== null ? `：影響段階 ${j.stage}（${STAGE_LABEL[j.stage]}）` : '：保留'}</h4>
    <p>判定ルールの版：{j.ruleVersion}。段階は人や AI の裁量ではなく、公的統計の実測値から機械的に決めています。{j.stage === 1 && '段階1は、狙った指標では差が確認できたが、経済全体の指標では確認できていない、という意味です。'}</p>
    <h5>人物ごとの結果</h5>
    <ul>{persons.map(p => <li key={p.personId}><strong>{p.name}</strong>：{p.status === 'scored' && p.score !== null
      ? <>{signed(p.score, 0)}点（{p.direction === 'benefit' ? '貢献' : '悪影響'}）</>
      : <>保留（{HOLD_NOTE[p.heldReason ?? ''] ?? p.heldReason}）</>}</li>)}</ul>
    <p className="fine-note">この点数は、この1事例だけの集計です。未評価は0点にしていません。点数は人格評価や責任割合の認定ではなく、資料に記された行動と、観測された指標の変化との関係に限ります。</p>
    <h5>計算の根拠</h5>
    <ul>
      <li>差の差の式：（主要行の{f.from}→{f.to}の変化）−（地域銀行の同じ期間の変化）。</li>
      <li>{f.source}の公表値で、主要行 {f.major.from.toFixed(1)}%→{f.major.to.toFixed(1)}%（{signed(t.majorChange, 1)}pt）、地域銀行 {f.regional.from.toFixed(1)}%→{f.regional.to.toFixed(1)}%（{signed(t.regionalChange, 1)}pt）、差の差は {signed(t.diffInDiff, 1)}pt。</li>
      <li>判定ルールが使う系列は別の表で、リスク管理債権÷貸出金（金融庁「（表６）リスク管理債権額等の推移」）です。効果＝開始後2〜5年目の差の平均−開始前{series.preYears}年の差の平均＝{j.effect !== null ? signed(j.effect, 2) : '算出不能'}pt。開始前のばらつき（差の標本標準偏差）は{j.spread !== null ? j.spread.toFixed(2) : '算出不能'}pt。効果がばらつきの2倍を超えて2年以上続いたため、段階1です。</li>
      <li>判定理由（ルールの出力）：{j.reason}</li>
    </ul>
    <h5>限界</h5>
    <ul>
      <li>帳簿上の不良債権比率の変化です。経済全体（GDP・貸出・雇用）への効果は確立していません。経済全体の指標で同じ向きの差が確認できないため、段階2以上にはなりません。</li>
      <li>開始前の差が{signed(series.preGapMin, 2)}〜{signed(series.preGapMax, 2)}ptと揺れており、開始前に悪化した分の戻りが、差の一部を占める可能性があります。</li>
      <li>{a.counterEvidence}</li>
      <li>{a.alternativeExplanation}</li>
      <li>数値は作業者による確認までで、独立検証と原本の読み戻しは未実施です。比較群の地域銀行も、プログラムの対象外とは言い切れません。</li>
    </ul>
    <p className="fine-note">計算の出どころ：{f.report}、app/src/impact-rule.ts、app/src/case-evaluation.ts。</p>
  </section>;
}

export function CaseVerdictPanel() {
  const [verdict, setVerdict] = useState<CaseVerdict | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    import('./case-verdict').then(module => module.computeCaseVerdict()).then(value => { if (live) setVerdict(value); }, () => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);
  if (failed) return <p role="alert">判定結果を計算できませんでした。点数は表示しません。</p>;
  if (!verdict) return <p>判定結果を計算しています。</p>;
  return <CaseVerdictView verdict={verdict} />;
}
