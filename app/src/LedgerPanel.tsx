import { useEffect, useState } from 'react';

type Counts = Record<string, number>;
type Summary = {
  total: number;
  by_reach: Record<string, { 本数: number; 抜き取り: number; 合格: number; うち額あり: number }>;
  by_classification_method: Counts;
  by_field_method: Counts;
  by_amount_method: Counts;
  by_verify_state: Counts;
  sample: { n: number; pass: number; fail: number };
  angles: { [key: string]: Counts | number };
  rule: string;
};

const ledgerUrl = '/distribution/ledger-summary.json';
const percent = (n: number, total: number) => `${(n / total * 100).toFixed(1)}%`;

function CountTable({ title, counts, total }: { title: string; counts: Counts; total: number }) {
  return <table className="spec-symbols">
    <caption>{title}</caption>
    <thead><tr><th scope="col">区分</th><th scope="col">本数</th><th scope="col">割合</th></tr></thead>
    <tbody>{Object.entries(counts).map(([k, v]) => <tr key={k}><td>{k || '（空）'}</td><td>{v.toLocaleString()}</td><td>{percent(v, total)}</td></tr>)}</tbody>
  </table>;
}

export default function LedgerPanel() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(ledgerUrl, { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        setData(await response.json() as Summary);
      } catch { if (!controller.signal.aborted) setError('評価台帳の集計を読み込めませんでした。'); }
    })();
    return () => controller.abort();
  }, []);
  const angles = data?.angles;
  return <section aria-labelledby="ledger">
    <h3 id="ledger">8. 評価台帳（どこまで・どの方法で・どこまで検証したか）</h3>
    <p>成立した全法律について、評価の到達点、方法、確かさ、検証の状態を1本ずつ記録しています（<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/評価台帳.md" target="_blank" rel="noopener noreferrer">docs/評価台帳.md</a>、1本ごとの表は <a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/data/derived/evaluation-ledger-v1/ledger.csv" target="_blank" rel="noopener noreferrer">ledger.csv</a>）。</p>
    {error && <p className="empty-state">{error}</p>}
    {!data && !error && <p className="empty-state">読み込み中…</p>}
    {data && <>
      <p><strong>{data.rule}</strong></p>
      <table className="spec-symbols">
        <caption>到達点ごとの本数（全{data.total.toLocaleString()}本）</caption>
        <thead><tr><th scope="col">到達点</th><th scope="col">本数</th><th scope="col">うち額あり</th><th scope="col">抜き取り検証</th><th scope="col">合格</th></tr></thead>
        <tbody>{Object.entries(data.by_reach).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v.本数.toLocaleString()}</td><td>{v.うち額あり.toLocaleString()}</td><td>{v.抜き取り}</td><td>{v.合格}</td></tr>)}</tbody>
      </table>
      <p>独立な抜き取り検証：{data.sample.n}本のうち合格 {data.sample.pass}、不合格 {data.sample.fail}。</p>
      <CountTable title="検証の状態" counts={data.by_verify_state} total={data.total} />
      <CountTable title="分類の方法" counts={data.by_classification_method} total={data.total} />
      <CountTable title="分野の方法" counts={data.by_field_method} total={data.total} />
      <CountTable title="額の方法" counts={data.by_amount_method} total={data.total} />
      {angles && <>
        <h4>スクリプトによる全件の歯止め（参考額が対象）</h4>
        {(['③規模', '③重なり', '④頑健性'] as const).map(k => <CountTable key={k} title={k} counts={angles[k] as Counts} total={data.total} />)}
        <p>狭い題名（特例・特定など）に全産業の額が付いた、同型の誤りの候補：{String(angles['⑤同型の誤り候補'])}本。③④を両方通った参考額：{String(angles['③④の両方を通った参考額'])}本。</p>
      </>}
    </>}
  </section>;
}
