import { useEffect, useRef, type ReactNode } from 'react';
import './votes.css';

/** 複数選べるドロップダウン。1つだけ選べば単一選択と同じ。閉じるのは外を押した時・Esc。 */
export function MultiSelect<T extends string>({ label, options, selected, onChange, allLabel }: {
  label: string; options: { value: T; label: string }[]; selected: readonly T[]; onChange: (next: T[]) => void; allLabel: string;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (event: Event) => { if (ref.current?.open && !ref.current.contains(event.target as Node)) ref.current.open = false; };
    const esc = (event: KeyboardEvent) => { if (event.key === 'Escape' && ref.current) ref.current.open = false; };
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', esc); };
  }, []);
  const names = options.filter(o => selected.includes(o.value)).map(o => o.label);
  const summary = names.length === 0 ? allLabel : names.length <= 2 ? names.join('・') : `${names[0]} ほか${names.length - 1}`;
  const toggle = (value: T) => onChange(selected.includes(value) ? selected.filter(v => v !== value) : [...selected, value]);
  return <details className="lens-filter" ref={ref}>
    <summary><span className="lens-filter-label">{label}</span><span className="lens-filter-value">{summary}</span></summary>
    <div className="lens-filter-menu" role="group" aria-label={label}>
      <button type="button" className="lens-filter-clear" onClick={() => onChange([])} disabled={selected.length === 0}>選択を外す（{allLabel}）</button>
      {options.map(o => <label key={o.value}><input type="checkbox" checked={selected.includes(o.value)} onChange={() => toggle(o.value)} />{o.label}</label>)}
    </div>
  </details>;
}

/** ページ最上部の絞り込み。縦に積まず横に並べる（狭い画面でも3つが1行に収まる幅）。 */
export function LensFilterBar({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return <section className="lens-filter-bar" aria-label="絞り込み"><div className="lens-filter-row">{children}</div>{note && <p className="fine-note">{note}</p>}</section>;
}
