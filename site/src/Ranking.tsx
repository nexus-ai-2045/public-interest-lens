import { useLayoutEffect, useRef, useState } from 'react';
import gsap from 'gsap';
import { Flip } from 'gsap/Flip';
import { involvements, people, policies, type Direction } from './data/fiction';
import { rank, ROLE_LABEL, type DomainFilter } from './scoring';

gsap.registerPlugin(Flip);

const DOMAINS: { id: DomainFilter; label: string }[] = [
  { id: 'all', label: '総合' },
  { id: 'economy', label: '経済' },
  { id: 'technology', label: '技術' },
];

function CountUp({ value, reduce }: { value: number; reduce: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduce) {
      el.textContent = String(value);
      last.current = value;
      return;
    }
    const obj = { v: last.current };
    const tw = gsap.to(obj, { v: value, duration: 0.9, ease: 'power3.out', onUpdate: () => { el.textContent = String(Math.round(obj.v)); } });
    last.current = value;
    return () => { tw.kill(); };
  }, [value, reduce]);
  return <span ref={ref}>{value}</span>;
}

export function Ranking({ direction, reduce }: { direction: Direction; reduce: boolean }) {
  const [domain, setDomain] = useState<DomainFilter>('all');
  const [open, setOpen] = useState<string | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const flipState = useRef<Flip.FlipState | null>(null);
  const rows = rank(people, policies, involvements, direction, domain);

  const capture = () => {
    if (listRef.current && !reduce) flipState.current = Flip.getState(listRef.current.querySelectorAll('.rank-row'));
  };

  useLayoutEffect(() => {
    const state = flipState.current;
    flipState.current = null;
    if (state && !reduce) {
      Flip.from(state, {
        duration: 0.75,
        ease: 'expo.out',
        stagger: 0.025,
        absolute: true,
        onEnter: (els) => gsap.fromTo(els, { opacity: 0, x: -40 }, { opacity: 1, x: 0, duration: 0.6, ease: 'expo.out', stagger: 0.04 }),
        onLeave: (els) => gsap.to(els, { opacity: 0, x: 40, duration: 0.35 }),
      });
    }
  }, [direction, domain, reduce]);

  useLayoutEffect(() => {
    if (reduce || !listRef.current) return;
    const ctx = gsap.context(() => {
      gsap.from('.rank-bar-fill', { scaleX: 0, duration: 1.1, ease: 'expo.out', stagger: 0.05 });
    }, listRef);
    return () => ctx.revert();
  }, [direction, domain, reduce]);

  return (
    <section className="ranking" id="ranking" aria-labelledby="ranking-title">
      <div className="section-head">
        <p className="eyebrow">架空データ版・{people.length}人</p>
        <h2 id="ranking-title">{direction === 'harm' ? '国賊ランキング' : '国士ランキング'}</h2>
        <p className="lede">
          {direction === 'harm'
            ? '経済と技術の伸びを妨げた政策に、誰がどう関わったか。'
            : '経済と技術の伸びを後押しした政策に、誰がどう関わったか。'}
          点数は公開された行動だけから計算します。
        </p>
      </div>
      <div className="tabs" role="tablist" aria-label="分野">
        {DOMAINS.map((d) => (
          <button
            key={d.id}
            role="tab"
            aria-selected={domain === d.id}
            className={domain === d.id ? 'tab active' : 'tab'}
            onClick={() => { capture(); setDomain(d.id); }}
          >
            {d.label}
          </button>
        ))}
      </div>
      <ol className="rank-list" ref={listRef}>
        {rows.map((r) => {
          const isOpen = open === r.person.id;
          return (
            <li key={r.person.id} className={`rank-row${r.rank <= 3 ? ' top' : ''}${isOpen ? ' open' : ''}`} data-flip-id={r.person.id}>
              <button className="rank-main" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : r.person.id)}>
                <span className="rank-no">{String(r.rank).padStart(2, '0')}</span>
                <span className="avatar" style={{ ['--h' as string]: r.person.hue }} aria-hidden="true">{r.person.name.replace('架空議員', '').slice(0, 1)}</span>
                <span className="rank-name">
                  <strong>{r.person.name}</strong>
                  <small>{r.person.house}・{r.person.district}</small>
                </span>
                <span className="rank-bar" aria-hidden="true"><span className="rank-bar-fill" style={{ width: `${r.score}%` }} /></span>
                <span className="rank-score"><CountUp value={r.score} reduce={reduce} /><small>点</small></span>
              </button>
              {isOpen && (
                <div className="rank-detail">
                  {r.contributions.map((c) => (
                    <div key={c.policy.id} className="contrib">
                      <span className="chip">{c.policy.theme}</span>
                      <div>
                        <strong>{c.policy.title}</strong>
                        <p>{ROLE_LABEL[c.role]}・{c.date}・{c.note}</p>
                      </div>
                      <span className="contrib-pts">影響{c.policy.impact} × {c.role === 'lead' ? '1.0' : '0.5'}</span>
                    </div>
                  ))}
                  <p className="fine">同じ政策への関与は、最も強い1件だけを数えます。人物・政策・記録はすべて創作です。</p>
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {rows.length === 0 && <p className="empty">この条件で採点できる架空人物はいません。</p>}
    </section>
  );
}
