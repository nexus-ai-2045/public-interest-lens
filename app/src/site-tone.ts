import { useEffect, useState } from 'react';

/** サイト全体の向き。国賊（harm）は暗く沈み、国士（benefit）は明るく浮く。どのページでも同じ値を使う。 */
export type Tone = 'harm' | 'benefit';

const KEY = 'lens-tone';
const EVENT = 'lens-tone-change';

function parseTone(value: string | null): Tone | null {
  if (value === 'harm' || value === 'kokuzoku') return 'harm';
  if (value === 'benefit' || value === 'kokushi') return 'benefit';
  return null;
}

/** URL の ?tone= を最優先し、次に前回の選択、どちらも無ければ国賊。 */
export function readTone(search = typeof window === 'undefined' ? '' : window.location.search): Tone {
  const fromUrl = parseTone(new URLSearchParams(search).get('tone'));
  if (fromUrl) {
    // URL で指定された向きは、そのあと開くページでも続ける。
    try { window.localStorage.setItem(KEY, fromUrl); } catch { /* 保存できなくても表示はする */ }
    return fromUrl;
  }
  try { return parseTone(window.localStorage.getItem(KEY)) ?? 'harm'; } catch { return 'harm'; }
}

export function writeTone(tone: Tone): void {
  try { window.localStorage.setItem(KEY, tone); } catch { /* 保存できなくても画面は切り替える */ }
  const params = new URLSearchParams(window.location.search);
  if (params.has('tone')) {
    params.set('tone', tone === 'harm' ? 'kokuzoku' : 'kokushi');
    window.history.replaceState(window.history.state, '', `${window.location.pathname}?${params}${window.location.hash}`);
  }
  window.dispatchEvent(new CustomEvent<Tone>(EVENT, { detail: tone }));
}

export const toneTitle = (tone: Tone) => tone === 'harm' ? '国賊ランキング' : '国士ランキング';

/** どの部品から呼んでも同じ向きを返し、切り替えるとすべての画面が追従する。 */
export function useTone(): [Tone, (tone: Tone) => void] {
  const [tone, setTone] = useState<Tone>(() => readTone());
  useEffect(() => {
    const change = (event: Event) => setTone((event as CustomEvent<Tone>).detail);
    const storage = (event: StorageEvent) => { if (event.key === KEY) setTone(parseTone(event.newValue) ?? 'harm'); };
    window.addEventListener(EVENT, change);
    window.addEventListener('storage', storage);
    return () => { window.removeEventListener(EVENT, change); window.removeEventListener('storage', storage); };
  }, []);
  return [tone, writeTone];
}
