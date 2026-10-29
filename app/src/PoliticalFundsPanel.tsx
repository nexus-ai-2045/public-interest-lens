import { ArrowUpRight } from 'lucide-react';
import type { PoliticalFundsGroups } from './political-funds';

/** 議員の届出団体。「無い」と「まだ結べていない」を分けて書く（団体が無いと断定しない）。 */
export function PoliticalFundsPanel({ groups, data }: { groups: PoliticalFundsGroups | null; data: string }) {
  if (!groups) return null;
  const rows = groups.members[data];
  const rosterName = (url: string) => groups.rosters.find(r => r.url === url)?.name ?? '名簿';
  return <section className="member-activity" aria-label="政治資金">
    <h5>政治資金（届出団体の一覧）・参考・点数には入れない</h5>
    {rows?.length ? <>
      <p className="fine-note">総務省の政治団体名簿に、この人の団体として載っている{rows.length}件です。</p>
      <ul className="member-evidence">{rows.map(g => <li key={g.name + g.kind + g.filedWith}>
        <span>{g.name}（{g.kind}・{g.filedWith}届出）</span>
        {g.sources.map(url => <a key={url} href={url} target="_blank" rel="noopener noreferrer">{rosterName(url)} <ArrowUpRight size={13} /></a>)}
      </li>)}</ul>
    </> : <p className="fine-note">この人を総務省の名簿の議員に結べていません（名簿に載っていない、または同姓同名などで人物を決められない）。団体が無いという意味ではありません。</p>}
    <p className="fine-note">収入・支出・寄附の金額は、収支報告書の読み取り結果がまだ配布に入っていないため出していません。名簿は{groups.rosters.map(r => r.name).join('・')}の現職の国会議員が対象で、元職や名簿の後に届け出られた団体は載りません。</p>
  </section>;
}
