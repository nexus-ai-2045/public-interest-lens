import { useEffect, useRef, useState, type ReactNode } from 'react';
import { PUBLIC_SITE } from './site-mode';
import { toneTitle, useTone, type Tone } from './site-tone';
import { usePrefersReducedMotion } from './motion';

/**
 * ナビの並び。結論（誰が・何が）→ 根拠（比べる相手と推移）→ 事例 → 手順。テスト用の仮データの画面（/demo）は公開サイトにリンクしない。
 * 先頭は向きに合わせて「国賊ランキング」「国士ランキング」と名前が変わる。
 */
export const SITE_LINKS: { href: string; label: string | ((tone: Tone) => string) }[] = [
  { href: '/members', label: toneTitle },
  { href: '/ranking', label: '法律ランキング' },
  { href: '/numbers', label: '数字で見る' },
  { href: '/world', label: '世界のGDP' },
  { href: '/history', label: '長期推移' },
  { href: '/policies', label: '政策と結果' },
  { href: '/actors', label: '人物・団体' },
  { href: '/methodology', label: '計算方法' },
];

export function SiteNav({ active, extra }: { active: string; extra?: ReactNode }) {
  const [tone] = useTone();
  return <nav className="site-nav" aria-label="主なページ">
    {SITE_LINKS.map(({ href, label }, index) => <a key={href} href={href} className={[index === 0 ? 'nav-primary' : '', href === active ? 'nav-active' : ''].filter(Boolean).join(' ') || undefined} aria-current={href === active ? 'page' : undefined}>{typeof label === 'function' ? label(tone) : label}</a>)}
    {!PUBLIC_SITE && <a href="/evaluation" className={active === '/evaluation' ? 'nav-active' : undefined}>保存評価版</a>}
    {extra}
  </nav>;
}

/** 国賊／国士の切り替え。押すと全ページの色・動き・並びが変わる。 */
export function ToneSwitch() {
  const [tone, setTone] = useTone();
  return <div className={`tone-switch ${tone}`} role="group" aria-label="国賊と国士の切り替え">
    <span className="tone-thumb" aria-hidden="true" />
    <button type="button" aria-pressed={tone === 'harm'} onClick={() => setTone('harm')}>国賊</button>
    <button type="button" aria-pressed={tone === 'benefit'} onClick={() => setTone('benefit')}>国士</button>
  </div>;
}

/** 切り替えた瞬間だけの全画面演出。国賊は黒い破片が降って画面が沈み、国士は金の粒が舞い上がる。 */
function ToneFx({ tone }: { tone: Tone }) {
  const reduced = usePrefersReducedMotion();
  const previous = useRef(tone);
  const [run, setRun] = useState(0);
  useEffect(() => {
    if (previous.current === tone) return;
    previous.current = tone;
    if (reduced) return;
    setRun(n => n + 1);
    const timer = setTimeout(() => setRun(0), 1300);
    return () => clearTimeout(timer);
  }, [tone, reduced]);
  if (!run) return null;
  const count = tone === 'harm' ? 34 : 40;
  return <div key={run} className={`tone-fx tone-fx-${tone}`} aria-hidden="true">
    <span className="tone-fx-flash" />
    {Array.from({ length: count }, (_, i) => <i key={i} style={{ '--x': `${(i * 37) % 100}%`, '--d': `${(i * 23) % 260}ms`, '--r': `${(i * 47) % 360}deg`, '--s': `${0.6 + ((i * 13) % 10) / 10}`, '--dx': `${((i * 29) % 60) - 30}px` } as React.CSSProperties} />)}
  </div>;
}

/** 公開ページ共通の外枠。向きで色（暗い／明るい）と入場の動きが切り替わる。 */
export function SiteShell({ active, label, className = '', children, extra }: { active: string; label: string; className?: string; children: ReactNode; extra?: ReactNode }) {
  const [tone] = useTone();
  return <div className={`app-shell research-page site-tone ${className}`.trim()} data-theme={tone === 'harm' ? 'dark' : 'light'} data-tone={tone}>
    <SiteHeader active={active} label={label} extra={extra} />
    {children}
  </div>;
}

export function SiteHeader({ active, label, extra }: { active: string; label: string; extra?: ReactNode }) {
  const [tone] = useTone();
  return <header className="topbar site-header">
    <a className="brand" href="/"><h1>{toneTitle(tone)}</h1><span className="prototype-label">{label}</span></a>
    <ToneSwitch />
    <SiteNav active={active} extra={extra} />
    <ToneFx tone={tone} />
  </header>;
}
