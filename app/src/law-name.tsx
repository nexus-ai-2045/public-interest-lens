import { useEffect, useState } from 'react';

/**
 * 法律の呼び方。正式名（「…法律案」）だけでは何の法律かわからないので、
 * 「何をする」の一文（会議録の提案理由の説明の AI 要約。別の読み手で照合済み、laws.json の what と同じ文）を先に出し、正式名をかっこで後に置く。
 * 一文が無い法律は題名から作らず、正式名だけを理由つきで出す。
 */

/** 一文が無い理由。shared・unread・other・unchecked は概要の withheld と同じ。none＝提案理由の説明が見つからなかった。 */
export type WhatWithheld = 'shared' | 'unread' | 'other' | 'unchecked' | 'none';

export const WITHHELD_REASON: Record<WhatWithheld, string> = {
  shared: 'ほかの法案とまとめた説明で、この法律の部分を一文にできなかった',
  unread: '提案理由の説明から中身を一文にできなかった',
  other: '見つかった説明がこの法律のものと確かめられなかった',
  unchecked: '見つかった説明がこの法律のものか、まだ確かめていない',
  none: '会議録に提案理由の説明が見つからなかった',
};

/** 「…を…する」の一文を「…を…する法律」にする（一文は全部、動詞の終止形で終わる）。 */
export function plainLawName(what: string): string {
  return `${what.trim().replace(/[。．]+$/u, '')}法律`;
}

// 一文は会議録の AI 要約なので、確かめた事実（正式名）と分けて「AI要約」の印を必ず付ける。
/** 文字だけの場面（共有の文、棒グラフの名前、読み上げ）で使う呼び方。 */
export function lawNameText(title: string, what?: string): string {
  return what ? `${plainLawName(what)}（AI要約／正式名：${title}）` : title;
}

/** 画面の呼び方。compact は一文が無いときの理由を省く（一覧の小さな行など）。 */
export function LawName({ title, what, withheld, compact = false }: { title: string; what?: string; withheld?: WhatWithheld; compact?: boolean }) {
  if (what) return <span className="law-name"><span className="law-name-plain">{plainLawName(what)}</span><span className="law-name-formal"><span className="law-name-tag">AI要約</span>（正式名：{title}）</span></span>;
  return <span className="law-name"><span className="law-name-plain is-formal">{title}</span>{withheld && !compact && <span className="law-name-none">何をする法律かの一文なし：{WITHHELD_REASON[withheld]}</span>}</span>;
}

/** laws.json を読まない画面（議員ページ）のための表。scripts/build_laws_catalog.py が作る。 */
export const lawNamesUrl = '/distribution/law-names.json';
export type LawNames = { what: Record<string, string>; withheld: Record<string, WhatWithheld> };

let namesCache: Promise<LawNames> | null = null;
function loadLawNames(): Promise<LawNames> {
  namesCache ??= fetch(lawNamesUrl).then(r => {
    if (!r.ok) throw new Error(String(r.status));
    return r.json() as Promise<{ schema: string } & LawNames>;
  }).then(data => {
    if (data.schema !== 'public-law-names/v1' || typeof data.what !== 'object' || typeof data.withheld !== 'object') throw new Error('law-names.json の形が違います');
    return { what: data.what, withheld: data.withheld };
  }).catch(error => { namesCache = null; throw error; });
  return namesCache;
}

/** 読めるまで・読めなかったときは null（呼び方は正式名だけになる）。 */
export function useLawNames(): LawNames | null {
  const [names, setNames] = useState<LawNames | null>(null);
  useEffect(() => {
    let alive = true;
    loadLawNames().then(value => { if (alive) setNames(value); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);
  return names;
}

/** 表から1本の呼び方の材料を引く。 */
export function namingOf(names: LawNames | null, id: string): { what?: string; withheld?: WhatWithheld } {
  return names ? { what: names.what[id], withheld: names.withheld[id] } : {};
}
