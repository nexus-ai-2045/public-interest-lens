/**
 * 議員ごとの国会での活動（公開記録）。点数には入れない参考の表示用。
 * 発言の数は国会会議録検索システムの API の件数そのまま。役職は公的機関・政党の公式ページで確かめられたものだけ。
 */
export type DietSpeech = { date: string; house: string; meeting: string; issue: string; position: string; group: string; url: string };
export type DietActivity = {
  speeches: number; shugiin: number; sangiin: number; asMinister: number; asChair: number; meetings: number; first: string;
  recent: DietSpeech[];
};
export type PublicRole = { category: string; title: string; period: string; url: string; source: string };
export type MemberActivityEntry = { diet?: DietActivity; roles?: PublicRole[] };
export type MemberActivity = {
  schema: 'member-activity/v1';
  fetchedAt: string;
  method: { diet: string; roles: string };
  members: Record<string, MemberActivityEntry>;
};

export const distributionActivityUrl = '/distribution/member-activity.json';

const KOKKAI = /^https:\/\/kokkai\.ndl\.go\.jp\//;
const OFFICIAL = /^https:\/\/([a-z0-9-]+\.)*(go\.jp|lg\.jp|jimin\.jp|komei\.or\.jp|cdp-japan\.jp|dpfp\.or\.jp|o-ishin\.jp|jcp\.or\.jp|sdp\.or\.jp)\//;

export function readActivity(text: string): MemberActivity {
  const data = JSON.parse(text) as MemberActivity;
  if (data.schema !== 'member-activity/v1' || typeof data.members !== 'object') throw new Error('活動データの形式が違います');
  for (const [name, entry] of Object.entries(data.members)) {
    for (const s of entry.diet?.recent ?? []) if (!KOKKAI.test(s.url)) throw new Error(`会議録以外の URL があります: ${name}`);
    for (const r of entry.roles ?? []) if (!OFFICIAL.test(r.url)) throw new Error(`公式ページ以外の URL があります: ${name}`);
  }
  return data;
}
