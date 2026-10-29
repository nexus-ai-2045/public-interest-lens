/**
 * 議員ごとの届出団体（総務省「政治団体名簿」）。点数には入れない参考の表示用。
 * 出すのは団体の名前・種別・届出先と名簿の PDF だけ。収入・支出の金額は、収支報告書の読み取り結果が配布されるまで無い。
 */
export type PoliticalGroup = { name: string; kind: string; filedWith: string; sources: string[] };
export type PoliticalFundsGroups = {
  schema: 'political-funds-groups/v1';
  method: string;
  rosters: { name: string; url: string }[];
  counts: { rosterMembers: number; linkedMembers: number; unlinkedMembers: number; groups: number };
  members: Record<string, PoliticalGroup[]>;
};

export const distributionPoliticalFundsUrl = '/distribution/political-funds-groups.json';

const SOUMU_PDF = /^https:\/\/www\.soumu\.go\.jp\/main_content\/\d+\.pdf$/;

export function readPoliticalFunds(text: string): PoliticalFundsGroups {
  const data = JSON.parse(text) as PoliticalFundsGroups;
  if (data.schema !== 'political-funds-groups/v1' || typeof data.members !== 'object') throw new Error('政治資金の団体データの形式が違います');
  for (const r of data.rosters) if (!SOUMU_PDF.test(r.url)) throw new Error('総務省の名簿 PDF 以外の URL があります');
  for (const [id, groups] of Object.entries(data.members)) for (const g of groups) for (const s of g.sources) if (!SOUMU_PDF.test(s)) throw new Error(`総務省の名簿 PDF 以外の URL があります: ${id}`);
  return data;
}
