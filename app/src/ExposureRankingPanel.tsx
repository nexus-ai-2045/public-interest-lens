import { useMemo, useState } from 'react';
import { Burst, CountUp, MOTION } from './motion';
import { formatYen } from './laws-catalog';
import { EXPOSURE_ROLES, type ExposureCell, type ExposureGroup, type ExposureRanking, type ExposureRole, type ExposureRow, type Range } from './exposure-ranking';
import './exposure.css';

/**
 * 曝露ランキング（案B）の画面部品。入力は exposure-ranking.ts の出力（people・parties・unallocated・totals）だけ。
 *
 * 見せ方の決まり：
 * 1. 最上部に「因果ではなく記述」を必ず出す（集計器の disclaimer をそのまま使う）。
 * 2. 順位は1位・2位ではなく階層で出す。幅が重なる人は同じ階層で、階層の中の並びに差の意味は無い。
 * 3. 関与した法律が下限に満たない人・会派は、額を出さない。関与した群と本数だけを出す。
 * 4. 配らなかった額（未配分）と検算を、畳んだ欄で必ず見られるようにする。
 * 5. 法律ごとの額は出さない（入力の型にも無い）。
 */

export type ExposureSide = 'loss' | 'benefit' | 'none';
export type GroupLabel = Pick<ExposureGroup, 'id' | 'industry' | 'period'>;
export type ExposureTab = 'people' | 'parties';

export const ROLE_LABEL: Readonly<Record<ExposureRole, string>> = { proposer: '発議', yes: '賛成', no: '反対（逆向き）', cabinet: '閣議決定' };
export const EXPOSURE_PAGE_SIZE = 30;

/** 正は伸び損ね（国賊側）、負は中央値を上回った（国士側）。 */
export const exposureSide = (value: number): ExposureSide => value > 0 ? 'loss' : value < 0 ? 'benefit' : 'none';
const SIDE_WORD: Readonly<Record<ExposureSide, string>> = { loss: '伸び損ね', benefit: '上回り', none: '' };

/** 向きを言葉で付けた額。符号だけに頼らない。 */
export function exposureYen(value: number): string {
  const side = exposureSide(value);
  return side === 'none' ? '0円' : `${SIDE_WORD[side]} ${formatYen(Math.abs(value))}`;
}

/** 幅の書き方。両端が同じ向きなら向きは1回、ゼロをまたぐなら両端に向きを付ける。 */
export function exposureRange(range: Range): string {
  const low = exposureSide(range.low);
  const high = exposureSide(range.high);
  if (low === high || low === 'none' || high === 'none') {
    const side = low === 'none' ? high : low;
    const [a, b] = [Math.abs(range.low), Math.abs(range.high)].sort((x, y) => x - y);
    return ['幅', SIDE_WORD[side], `${formatYen(a)}〜${formatYen(b)}`].filter(Boolean).join(' ');
  }
  return `幅 ${exposureYen(range.low)}〜${exposureYen(range.high)}`;
}

/** 階層ごとにまとめる。入力は集計器の並び（階層の昇順）のまま。階層の無い行は入れない。 */
export function groupByTier(rows: readonly ExposureRow[]): { tier: number; rows: ExposureRow[] }[] {
  const tiers: { tier: number; rows: ExposureRow[] }[] = [];
  for (const row of rows) {
    if (row.tier === null) continue;
    const last = tiers[tiers.length - 1];
    if (last && last.tier === row.tier) last.rows.push(row);
    else tiers.push({ tier: row.tier, rows: [row] });
  }
  return tiers;
}

/** 棒の物差し。ゼロを必ず含め、負の額（上回り）があればゼロより左に伸びる。 */
export function exposureScale(rows: readonly { exposureYen: Range }[]): { min: number; max: number; position: (value: number) => number } {
  const min = Math.min(0, ...rows.map(r => r.exposureYen.low));
  const max = Math.max(0, ...rows.map(r => r.exposureYen.high));
  const span = max - min || 1;
  return { min, max, position: value => Math.max(0, Math.min(100, (value - min) / span * 100)) };
}

/** 検算：人＋会派＋未配分が、配る額の合計と合うか。 */
export function totalsCheck(totals: ExposureRanking['totals']): { sum: Range; ok: boolean } {
  const keys = ['low', 'median', 'high'] as const;
  const sum = Object.fromEntries(keys.map(k => [k, totals.people[k] + totals.parties[k] + totals.unallocated[k]])) as Range;
  const ok = keys.every(k => Math.abs(sum[k] - totals.expected[k]) <= 1e-6 * Math.max(1, Math.abs(totals.expected[k])));
  return { sum, ok };
}

/** 群ごとに、役割と本数（と額）をまとめる。 */
function cellsByGroup(cells: readonly ExposureCell[]): { groupId: string; cells: ExposureCell[] }[] {
  const map = new Map<string, ExposureCell[]>();
  for (const cell of cells) map.set(cell.groupId, [...(map.get(cell.groupId) ?? []), cell]);
  return [...map].map(([groupId, list]) => ({ groupId, cells: list }));
}

type Labels = { group: (id: string) => string; actor: (row: ExposureRow) => string };

function CellList({ row, labels, withAmount }: { row: ExposureRow; labels: Labels; withAmount: boolean }) {
  return <ul className="xr-cells">
    {cellsByGroup(row.cells).map(group => <li key={group.groupId}>
      <span className="xr-cell-group">{labels.group(group.groupId)}</span>
      <span className="xr-cell-roles">{group.cells.map(cell => <span key={cell.role} className={`xr-chip ${withAmount ? exposureSide(cell.exposureYen.median) : 'none'}`}>
        <b>{ROLE_LABEL[cell.role]}</b> {cell.laws}本{withAmount && <> ・ {exposureYen(cell.exposureYen.median)}<small>（{exposureRange(cell.exposureYen)}）</small></>}
      </span>)}</span>
    </li>)}
  </ul>;
}

function RankedRow({ row, index, labels, scale, flair }: { row: ExposureRow; index: number; labels: Labels; scale: ReturnType<typeof exposureScale>; flair: boolean }) {
  const side = exposureSide(row.exposureYen.median);
  const zero = scale.position(0);
  const median = scale.position(row.exposureYen.median);
  const low = scale.position(row.exposureYen.low);
  const high = scale.position(row.exposureYen.high);
  const delay = `${Math.min(index * MOTION.stagger, MOTION.maxStagger)}ms`;
  const name = labels.actor(row);
  return <li className={`xr-row ${side}`} style={{ animationDelay: delay }}>
    <details>
      <summary aria-label={`${name}、${exposureYen(row.exposureYen.median)}、${exposureRange(row.exposureYen)}、関与した法律${row.laws}本・${row.groups}群`}>
        <span className="xr-name">{name}{flair && <Burst tone={side === 'benefit' ? 'benefit' : 'loss'} />}</span>
        <span className="xr-amount" aria-hidden="true">
          <span className="xr-side">{side === 'loss' ? '国賊側・伸び損ね' : side === 'benefit' ? '国士側・上回り' : '差なし'}</span>
          <strong><CountUp value={Math.abs(row.exposureYen.median)} format={formatYen} /></strong>
          <small>{exposureRange(row.exposureYen)}</small>
        </span>
        <span className="xr-track" aria-hidden="true">
          {scale.min < 0 && <span className="xr-zero" style={{ left: `${zero}%` }} />}
          <span className="xr-fill" style={{ left: `${Math.min(zero, median)}%`, width: `${Math.abs(median - zero)}%`, transitionDelay: delay }} />
          <span className="xr-range" style={{ left: `${low}%`, width: `${high - low}%` }} />
        </span>
        <span className="xr-meta">関与した法律 {row.laws}本・{row.groups}群<span className="xr-open-hint">内訳を開く</span></span>
      </summary>
      <div className="xr-detail">
        <p className="fine-note">群（産業×期間）と役割ごとの内訳です。法律1本ごとの額は出しません（識別できるのは群までです）。</p>
        <CellList row={row} labels={labels} withAmount />
      </div>
    </details>
  </li>;
}

function UnrankedRow({ row, labels }: { row: ExposureRow; labels: Labels }) {
  return <li className="xr-unranked-row">
    <span className="xr-name">{labels.actor(row)}</span>
    <span className="xr-meta">関与した法律 {row.laws}本・{row.groups}群（額は出しません）</span>
    <CellList row={row} labels={labels} withAmount={false} />
  </li>;
}

export type ExposureRankingPanelProps = {
  ranking: ExposureRanking;
  /** 群の表示名（産業と期間）。無い群は ID をそのまま出す。 */
  groups?: readonly GroupLabel[];
  /** ID → 表示名。無ければ ID をそのまま出す。 */
  personNames?: Readonly<Record<string, string>>;
  partyNames?: Readonly<Record<string, string>>;
  initialTab?: ExposureTab;
};

export function ExposureRankingPanel({ ranking, groups = [], personNames = {}, partyNames = {}, initialTab = 'people' }: ExposureRankingPanelProps) {
  const [tab, setTab] = useState<ExposureTab>(initialTab);
  const [limit, setLimit] = useState(EXPOSURE_PAGE_SIZE);
  const [unrankedLimit, setUnrankedLimit] = useState(EXPOSURE_PAGE_SIZE);
  const switchTab = (next: ExposureTab) => { setTab(next); setLimit(EXPOSURE_PAGE_SIZE); setUnrankedLimit(EXPOSURE_PAGE_SIZE); };
  const labels = useMemo<Labels>(() => {
    const byId = new Map(groups.map(g => [g.id, `${g.industry}（${g.period}）`]));
    return {
      group: id => byId.get(id) ?? id,
      actor: row => (row.actorKind === 'person' ? personNames : partyNames)[row.actorId] ?? row.actorId,
    };
  }, [groups, personNames, partyNames]);
  const rows = tab === 'people' ? ranking.people : ranking.parties;
  const ranked = useMemo(() => rows.filter(r => r.tier !== null), [rows]);
  const unranked = useMemo(() => rows.filter(r => r.tier === null), [rows]);
  const scale = useMemo(() => exposureScale(ranked), [ranked]);
  const tiers = useMemo(() => groupByTier(ranked.slice(0, limit)), [ranked, limit]);
  const check = totalsCheck(ranking.totals);
  const unit = tab === 'people' ? '人' : '会派';
  const { roleRatio, minLaws } = ranking.params;
  let index = 0;
  return <section className="exposure-panel" aria-labelledby="exposure-title">
    <h2 id="exposure-title">曝露ランキング <span className="xr-claim">因果ではなく記述</span></h2>
    <p className="xr-disclaimer" role="note"><strong>これは「関与していた産業群がどれだけ伸び損ねたか」の記述です。</strong>{ranking.disclaimer}</p>
    <details className="xr-rules">
      <summary>配り方と階層の読み方</summary>
      <ul>
        <li>伸び損ね額は、産業×期間の群ごとに、OECD の同じ産業・同じ時期の中央値との差です。</li>
        <li>群の額を役割ごとの固定比率（取り決め）で配ります：{EXPOSURE_ROLES.map(role => `${ROLE_LABEL[role]} ${roleRatio[role]}`).join('・')}。反対は逆向きに配ります。</li>
        <li>幅が重なる{unit}は同じ階層です。同じ階層の中の並び順に、差の意味はありません。統計的な信頼集合ではなく、記述の階層です。</li>
        <li>関与した法律が{minLaws}本に満たない{unit}は、額を出さず、関与した群と本数だけを出します。</li>
      </ul>
    </details>
    <div className="xr-tabs" role="group" aria-label="表示を切り替える">
      <button type="button" aria-pressed={tab === 'people'} onClick={() => switchTab('people')}>議員（{ranking.people.length}人）</button>
      <button type="button" aria-pressed={tab === 'parties'} onClick={() => switchTab('parties')}>会派（{ranking.parties.length}）</button>
    </div>
    {ranked.length === 0
      ? <p className="empty-state" role="note">階層に入る{unit}がまだいません（関与した法律が{minLaws}本以上の{unit}がいません）。</p>
      : <>
        <p className="xr-legend" aria-hidden="true">
          <span><i className="xr-key-fill" />太い棒＝中央値</span>
          <span><i className="xr-key-range" />細い線＝幅（低い値〜高い値）</span>
          {scale.min < 0 && <span><i className="xr-key-zero" />縦線＝0（左は中央値を上回った側）</span>}
        </p>
        <p className="fine-note" role="status">階層に入る{unit}は{ranked.length}{tab === 'people' ? '人' : '会派'}{limit < ranked.length && `（上から${limit}を表示）`}</p>
        {tiers.map(tier => <section key={tier.tier} className={`xr-tier ${tier.tier === 1 ? 'top' : ''}`} aria-label={`第${tier.tier}階層`}>
          <h3><span className="xr-tier-no">第{tier.tier}階層</span><small>幅が重なる{tier.rows.length}{tab === 'people' ? '人' : '会派'}（並び順に差の意味なし）</small></h3>
          <ol className="xr-rows">{tier.rows.map(row => {
            const i = index++;
            return <RankedRow key={row.actorId} row={row} index={i} labels={labels} scale={scale} flair={i === 0} />;
          })}</ol>
        </section>)}
        {limit < ranked.length && <p className="xr-more"><button type="button" onClick={() => setLimit(n => n + EXPOSURE_PAGE_SIZE)}>さらに表示（残り{ranked.length - limit}）</button></p>}
      </>}
    {unranked.length > 0 && <details className="xr-unranked">
      <summary>額を出さない{unit}（関与した法律が{minLaws}本未満）：{unranked.length}{tab === 'people' ? '人' : '会派'}</summary>
      <p className="fine-note">関与した法律が少ないと、1本の法律で額が決まってしまうため、額も階層も出しません。関与した群と本数だけを出します。</p>
      <ul className="xr-unranked-list">{unranked.slice(0, unrankedLimit).map(row => <UnrankedRow key={row.actorId} row={row} labels={labels} />)}</ul>
      {unrankedLimit < unranked.length && <p className="xr-more"><button type="button" onClick={() => setUnrankedLimit(n => n + EXPOSURE_PAGE_SIZE)}>さらに表示（残り{unranked.length - unrankedLimit}）</button></p>}
    </details>}
    <details className="xr-unallocated">
      <summary>配らなかった額（未配分）：{exposureYen(ranking.totals.unallocated.median)}</summary>
      {ranking.unallocated.length === 0
        ? <p className="fine-note">未配分はありません。</p>
        : <ul className="xr-unallocated-list">{ranking.unallocated.map((u, i) => <li key={`${u.groupId}-${u.role ?? 'all'}-${i}`}>
          <span className="xr-cell-group">{labels.group(u.groupId)}</span>
          <span>{u.role ? ROLE_LABEL[u.role] : '全役割'}{u.laws > 0 && `・${u.laws}本ぶんの枠`}：{exposureYen(u.exposureYen.median)}<small>（{exposureRange(u.exposureYen)}）</small></span>
          <small className="xr-reason">理由：{u.reason}</small>
        </li>)}</ul>}
    </details>
    <details className="xr-totals">
      <summary>検算（配った額と配らなかった額の合計）{check.ok ? '：一致' : '：不一致'}</summary>
      {!check.ok && <p className="state-banner" role="alert">検算が合いません。人＋会派＋未配分が、配る額の合計と一致していません。</p>}
      <dl>
        <div><dt>議員</dt><dd>{exposureYen(ranking.totals.people.median)}</dd></div>
        <div><dt>会派</dt><dd>{exposureYen(ranking.totals.parties.median)}</dd></div>
        <div><dt>未配分</dt><dd>{exposureYen(ranking.totals.unallocated.median)}</dd></div>
        <div className="xr-total"><dt>合計</dt><dd>{exposureYen(check.sum.median)}<small>（{exposureRange(check.sum)}）</small></dd></div>
        <div className="xr-total"><dt>配る額の合計（群の額×役割比率）</dt><dd>{exposureYen(ranking.totals.expected.median)}<small>（{exposureRange(ranking.totals.expected)}）</small></dd></div>
      </dl>
      <p className="fine-note">議員の合計には、額を出さない{minLaws}本未満の人の分も含みます（黙って消さないため）。</p>
    </details>
  </section>;
}
