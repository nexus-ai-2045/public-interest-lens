import { useMemo, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Database,
  FileSearch,
  Info,
  Scale,
  SlidersHorizontal,
  Sparkles,
} from "lucide-react";
import { entities, evidence } from "./data";
import {
  calculateReferenceScore,
  evidenceLabel,
  type AxisKey,
  type AxisValues,
  type EvidenceKind,
} from "./scoring";

const axisMeta: Record<AxisKey, { label: string; description: string }> = {
  deliberation: { label: "審議への参加", description: "公開された出席・発言記録" },
  proposals: { label: "政策提案", description: "提案数と論点の公開状況" },
  transparency: { label: "情報の透明性", description: "出典・更新履歴の充足度" },
};

const kindIcon: Record<EvidenceKind, typeof CheckCircle2> = {
  verified: CheckCircle2,
  computed: Database,
  ai: Sparkles,
  unknown: CircleHelp,
};

function App() {
  const [selectedEntityId, setSelectedEntityId] = useState(entities[0].id);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState(evidence[0].id);
  const [activeKinds, setActiveKinds] = useState<Set<EvidenceKind>>(
    new Set(["verified", "computed", "ai", "unknown"]),
  );
  const [weights, setWeights] = useState<AxisValues>({
    deliberation: 40,
    proposals: 35,
    transparency: 25,
  });

  const selectedEntity =
    entities.find((entity) => entity.id === selectedEntityId) ?? entities[0];
  const scores = useMemo(
    () =>
      Object.fromEntries(
        entities.map((entity) => [
          entity.id,
          calculateReferenceScore(entity.values, weights),
        ]),
      ),
    [weights],
  );
  const visibleEvidence = evidence.filter((item) => activeKinds.has(item.kind));
  const selectedEvidence =
    visibleEvidence.find((item) => item.id === selectedEvidenceId) ??
    visibleEvidence[0];

  function toggleKind(kind: EvidenceKind) {
    setActiveKinds((current) => {
      const next = new Set(current);
      if (next.has(kind)) {
        if (next.size > 1) next.delete(kind);
      } else {
        next.add(kind);
      }
      return next;
    });
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="公益レンズ ホーム">
          <span className="brand-mark"><Scale size={19} /></span>
          <span>公益レンズ</span>
          <span className="prototype-label">PROTOTYPE</span>
        </a>
        <nav aria-label="主要ナビゲーション">
          <a className="active" href="#compare">比較</a>
          <a href="#timeline">時系列</a>
          <a href="#axes">評価軸</a>
          <a href="#evidence">根拠</a>
        </nav>
        <button className="outline-button"><Info size={16} /> この画面について</button>
      </header>

      <main id="top">
        <section className="hero">
          <div>
            <p className="eyebrow">PUBLIC EVIDENCE EXPLORER</p>
            <h1>公開事実から、<br />判断材料をひらく。</h1>
          </div>
          <div className="hero-note">
            <Info size={18} />
            <p>
              これは人物や団体の優劣を決めるランキングではありません。
              公開された根拠、計算方法、不確実性を並べて確認するための試作です。
            </p>
          </div>
        </section>

        <section id="compare" className="dashboard-grid">
          <aside className="panel entity-panel">
            <div className="panel-heading">
              <div><p className="section-kicker">対象</p><h2>比較する主体</h2></div>
              <span className="count">{entities.length}</span>
            </div>
            <div className="entity-list">
              {entities.map((entity) => (
                <button
                  key={entity.id}
                  className={`entity-button ${selectedEntityId === entity.id ? "selected" : ""}`}
                  onClick={() => setSelectedEntityId(entity.id)}
                >
                  <span className="avatar">{entity.name.slice(0, 1)}</span>
                  <span><strong>{entity.name}</strong><small>{entity.type}</small></span>
                  <ChevronRight size={17} />
                </button>
              ))}
            </div>
            <div className="entity-context">
              <FileSearch size={18} />
              <p>{selectedEntity.note}</p>
            </div>
          </aside>

          <section className="panel comparison-panel">
            <div className="panel-heading">
              <div><p className="section-kicker">比較ビュー</p><h2>参考スコアと内訳</h2></div>
              <span className="updated">架空データ・2026年7月</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>主体</th>
                    {(Object.keys(axisMeta) as AxisKey[]).map((key) => <th key={key}>{axisMeta[key].label}</th>)}
                    <th>参考スコア</th>
                  </tr>
                </thead>
                <tbody>
                  {entities.map((entity) => (
                    <tr
                      key={entity.id}
                      className={selectedEntityId === entity.id ? "selected-row" : ""}
                      onClick={() => setSelectedEntityId(entity.id)}
                    >
                      <td><strong>{entity.name}</strong><small>{entity.type}</small></td>
                      {(Object.keys(axisMeta) as AxisKey[]).map((key) => (
                        <td key={key}>
                          <span className="value">{entity.values[key]}</span>
                          <span className="microbar"><i style={{ width: `${entity.values[key]}%` }} /></span>
                        </td>
                      ))}
                      <td><span className="score">{scores[entity.id]}</span><small>/ 100</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="method-note">
              <Scale size={17} />
              <span>スコアは下の重みから機械的に算出。順位や推奨を表しません。</span>
              <a href="#axes">計算方法を見る <ArrowUpRight size={14} /></a>
            </div>
          </section>

          <aside id="axes" className="panel weights-panel">
            <div className="panel-heading">
              <div><p className="section-kicker">評価軸</p><h2>重みを調整</h2></div>
              <SlidersHorizontal size={19} />
            </div>
            <p className="panel-description">重みを変えると、同じ公開事実でも参考値がどう変化するか確認できます。</p>
            {(Object.keys(axisMeta) as AxisKey[]).map((key) => (
              <label className="weight-control" key={key}>
                <span><strong>{axisMeta[key].label}</strong><output>{weights[key]}%</output></span>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={weights[key]}
                  onChange={(event) =>
                    setWeights({ ...weights, [key]: Number(event.target.value) })
                  }
                />
                <small>{axisMeta[key].description}</small>
              </label>
            ))}
            <div className="selected-score">
              <span>{selectedEntity.name}の参考値</span>
              <strong>{scores[selectedEntity.id]}</strong>
            </div>
          </aside>
        </section>

        <section id="evidence" className="evidence-section">
          <div className="section-title-row">
            <div><p className="section-kicker">EVIDENCE TRAIL</p><h2>根拠をたどる</h2></div>
            <div className="filter-row">
              {(["verified", "computed", "ai", "unknown"] as EvidenceKind[]).map((kind) => {
                const Icon = kindIcon[kind];
                return (
                  <button
                    key={kind}
                    className={`filter-chip ${kind} ${activeKinds.has(kind) ? "on" : ""}`}
                    onClick={() => toggleKind(kind)}
                    aria-pressed={activeKinds.has(kind)}
                  >
                    <Icon size={15} /> {evidenceLabel(kind)}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="evidence-grid">
            <div className="panel evidence-list">
              {visibleEvidence.map((item) => {
                const Icon = kindIcon[item.kind];
                return (
                  <button
                    key={item.id}
                    className={selectedEvidence?.id === item.id ? "selected" : ""}
                    onClick={() => {
                      setSelectedEvidenceId(item.id);
                      setSelectedEntityId(item.entityId);
                    }}
                  >
                    <span className={`kind-icon ${item.kind}`}><Icon size={17} /></span>
                    <span className="evidence-copy">
                      <small>{item.date} · {evidenceLabel(item.kind)}</small>
                      <strong>{item.title}</strong>
                      <span>{item.summary}</span>
                    </span>
                    <ChevronRight size={17} />
                  </button>
                );
              })}
            </div>

            <article className="panel evidence-detail">
              {selectedEvidence ? (
                <>
                  <div className="detail-meta">
                    <span className={`status-badge ${selectedEvidence.kind}`}>{evidenceLabel(selectedEvidence.kind)}</span>
                    <span>{selectedEvidence.date}</span>
                  </div>
                  <h3>{selectedEvidence.title}</h3>
                  <p>{selectedEvidence.summary}</p>
                  {selectedEvidence.kind === "ai" && (
                    <div className="ai-warning"><Sparkles size={17} /> AIによる整理は誤り得ます。原資料と照合してください。</div>
                  )}
                  <div className="source-card">
                    <span><BookOpen size={17} /> 出典プレビュー</span>
                    <strong>{selectedEvidence.source}</strong>
                    <blockquote>{selectedEvidence.excerpt}</blockquote>
                    <button>原資料の位置を確認 <ArrowUpRight size={14} /></button>
                  </div>
                </>
              ) : <p>表示できる根拠がありません。</p>}
            </article>

            <aside id="timeline" className="panel timeline-panel">
              <p className="section-kicker">時系列</p>
              <h3>更新の流れ</h3>
              {[...evidence].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 4).map((item) => (
                <div className="timeline-item" key={item.id}>
                  <i />
                  <span><small>{item.date}</small><strong>{item.title}</strong></span>
                </div>
              ))}
              <p className="timeline-note">版の差分や訂正履歴を同じ軸で追加する想定です。</p>
            </aside>
          </div>
        </section>
      </main>

      <footer>
        <span><Scale size={16} /> 公益レンズ — 判断を代替せず、根拠を見えるようにする。</span>
        <span>架空データによるローカル MVP</span>
      </footer>
    </div>
  );
}

export default App;
