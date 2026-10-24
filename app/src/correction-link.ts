/** 反論・訂正の窓口。対象と画面の出典を入れた GitHub Issue の作成画面を開く。 */
export const SITE_ORIGIN = 'https://kokuzoku.nexusai2045.com';
const NEW_ISSUE = 'https://github.com/nexus-ai-2045/public-interest-lens/issues/new';
const MAX_SOURCES = 12;
const MAX_URL = 7000;
const MAX_MAIL = 1900;

/** GitHub アカウントの無い人向けの受付アドレス。公開ビルドの環境変数 VITE_CORRECTION_EMAIL で入れる。空ならメールの窓口は出さない。 */
export const CORRECTION_EMAIL = (import.meta.env.VITE_CORRECTION_EMAIL ?? '').trim();

export type CorrectionTarget = { title: string; page: string; sources: { label: string; url: string }[] };

/** Issue テンプレート（correction.yml）の欄 id に合わせて値を入れる。長すぎる時は出典を減らす。 */
export function correctionIssueUrl({ title, page, sources }: CorrectionTarget): string {
  const seen = new Set<string>();
  const unique = sources.filter(s => s.url && !seen.has(s.url) && seen.add(s.url));
  for (let n = Math.min(unique.length, MAX_SOURCES); n >= 0; n--) {
    const listed = unique.slice(0, n).map(s => `- ${s.label}：${s.url}`);
    if (unique.length > n) listed.push(`- ほか${unique.length - n}件は画面を参照`);
    const params = new URLSearchParams({
      template: 'correction.yml',
      title: `[訂正] ${title}`,
      target: `${title}（${SITE_ORIGIN}${page}）`,
      cited: listed.join('\n') || '（この画面に出典の記載なし）',
    });
    const url = `${NEW_ISSUE}?${params.toString()}`;
    if (url.length <= MAX_URL || n === 0) return url;
  }
  return `${NEW_ISSUE}?template=correction.yml`;
}

/** その項目に寄せられた反論・訂正（受付中と処理済み）を GitHub で一覧する。 */
export function correctionListUrl(title: string): string {
  const q = `is:issue label:correction in:title "${title.replace(/"/g, '')}"`;
  return `https://github.com/nexus-ai-2045/public-interest-lens/issues?${new URLSearchParams({ q }).toString()}`;
}

/** メールの下書き。件名と本文に、対象・画面の出典・書いてほしい欄を入れる。メールソフトが受けられる長さに出典を減らす。 */
export function correctionMailUrl({ title, page, sources }: CorrectionTarget, email: string): string {
  const seen = new Set<string>();
  const unique = sources.filter(s => s.url && !seen.has(s.url) && seen.add(s.url));
  for (let n = Math.min(unique.length, MAX_SOURCES); ; n--) {
    const listed = unique.slice(0, n).map(s => `- ${s.label}：${s.url}`);
    if (unique.length > n) listed.push(`- ほか${unique.length - n}件は画面を参照`);
    const body = [
      `対象：${title}（${SITE_ORIGIN}${page}）`, '',
      '画面が使った出典：', ...(listed.length ? listed : ['（この画面に出典の記載なし）']), '',
      '立場（本人・関係者・第三者・答えない）：', '',
      'どこが、どう違うか：', '', '',
      '根拠となる公開資料（URL と該当箇所）：', '', '',
      '※ 内容は GitHub の公開 Issue に転記します。連絡先・住所などの個人情報や非公開資料の本文は書かないでください。',
    ].join('\n');
    const url = `mailto:${email}?subject=${encodeURIComponent(`[訂正] ${title}`)}&body=${encodeURIComponent(body)}`;
    if (url.length <= MAX_MAIL || n === 0) return url;
  }
}
