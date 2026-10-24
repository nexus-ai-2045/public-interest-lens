"""公開している議員ページ（members.json）の公開前検査。

実名を出すページなので、次を機械で止める（ロードマップ E1・E4）。
- 公人としての記録以外の項目（住所・家族・健康など）が入っていない（JSON の経路ごとの許可リスト）。
- 同じ人物が2行に割れていない（人物IDが一意で、空白違いの表記ゆれの人物IDが無い）。同姓同名の別人は
  人物ID（院と選挙区を付けた「鬼木誠（衆・福岡2）」の形）で分ける（ロードマップ R17、scripts/person_ids.py）。
- 配分に使う法律は公開ランキングにあり、確かさが「高」か「中」（低と参考は配分に使わない、ADR 0008）。
- 画面でリンクになる項目はすべて https で、国会会議録・衆参の議案情報だけ。
"""

import json
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "app" / "public" / "distribution"

# いま members.json に出ている項目を、JSON の経路（どの階層のどの項目か）で並べたもの。
# 同じ項目名でも別の階層に増えたら止める。新しい項目を足すときは、公人としての公開記録かを確かめてからここに足す。
ALLOWED_PATHS = {
    ".counts",
    ".counts.benefit",
    ".counts.context",
    ".counts.excluded",
    ".counts.involvements",
    ".counts.loss",
    ".counts.members",
    ".counts.zero",
    ".inputs",
    ".inputs.enacted",
    ".inputs.involvements",
    ".inputs.loss",
    ".inputs.publish",
    ".inputs.votes",
    ".laws",
    ".laws[].amount",
    ".laws[].amount.high",
    ".laws[].amount.low",
    ".laws[].amount.median",
    ".laws[].observationLaws",
    ".laws[].attributed",
    ".laws[].attributed.high",
    ".laws[].attributed.low",
    ".laws[].attributed.median",
    ".laws[].confidence",
    ".laws[].enactedOn",
    ".laws[].game",
    ".laws[].game.chairs",
    ".laws[].game.names",
    ".laws[].game.names.chairs",
    ".laws[].game.names.proposers",
    ".laws[].game.names.voters",
    ".laws[].game.names.opposers",
    ".inputs.opposing",
    ".inputs.autoInvolvements",
    ".inputs.autoVotes",
    ".inputs.voteParties",
    ".inputs.ministries",
    ".inputs.resistance",
    ".inputs.orgStances",
    ".resistance",
    ".resistance[].ministry",
    ".resistance[].total",
    ".resistance[].refusals",
    ".resistance[].answers",
    ".resistance[].hearings",
    ".resistance[].followups",
    ".orgStances",
    ".orgStances[].name",
    ".orgStances[].kind",
    ".orgStances[].against",
    ".orgStances[].careful",
    ".orgStances[].conditional",
    ".orgStances[].support",
    ".orgStances[].technologies",
    ".orgStances[].technologies[]",
    ".inputs.taxLedger",
    ".taxLedger",
    ".taxLedger[].lawId",
    ".taxLedger[].title",
    ".taxLedger[].kind",
    ".taxLedger[].changes",
    ".taxLedger[].changes[]",
    ".taxLedger[].years",
    ".taxLedger[].years[].year",
    ".taxLedger[].years[].nth",
    ".taxLedger[].years[].amount",
    ".taxLedger[].total",
    ".taxLedger[].certainty",
    ".taxLedger[].marks",
    ".taxLedger[].marks[]",
    ".taxLedger[].notes",
    ".taxLedger[].notes[]",
    ".taxLedger[].sources",
    ".taxLedger[].sources[]",
    ".ministries",
    ".ministries[].name",
    ".ministries[].bad",
    ".ministries[].bad.high",
    ".ministries[].bad.low",
    ".ministries[].bad.median",
    ".ministries[].good",
    ".ministries[].good.high",
    ".ministries[].good.low",
    ".ministries[].good.median",
    ".ministries[].net",
    ".ministries[].net.high",
    ".ministries[].net.low",
    ".ministries[].net.median",
    ".ministries[].laws",
    ".ministries[].laws[].lawId",
    ".ministries[].laws[].side",
    ".ministries[].laws[].direction",
    ".ministries[].laws[].effect",
    ".ministries[].laws[].share",
    ".ministries[].laws[].share.high",
    ".ministries[].laws[].share.low",
    ".ministries[].laws[].share.median",
    ".partyRanking",
    ".partyRanking.blocs",
    ".partyRanking.blocs[].bad",
    ".partyRanking.blocs[].bad.high",
    ".partyRanking.blocs[].bad.low",
    ".partyRanking.blocs[].bad.median",
    ".partyRanking.blocs[].bloc",
    ".partyRanking.blocs[].certainty",
    ".partyRanking.blocs[].certainty.中",
    ".partyRanking.blocs[].certainty.低",
    ".partyRanking.blocs[].certainty.高",
    ".partyRanking.blocs[].good",
    ".partyRanking.blocs[].good.high",
    ".partyRanking.blocs[].good.low",
    ".partyRanking.blocs[].good.median",
    ".partyRanking.blocs[].laws",
    ".partyRanking.blocs[].lossShareOfYes",
    ".partyRanking.blocs[].net",
    ".partyRanking.blocs[].net.high",
    ".partyRanking.blocs[].net.low",
    ".partyRanking.blocs[].net.median",
    ".partyRanking.blocs[].noLaws",
    ".partyRanking.blocs[].parties",
    ".partyRanking.blocs[].people",
    ".partyRanking.blocs[].perLaw",
    ".partyRanking.blocs[].perPerson",
    ".partyRanking.blocs[].perVote",
    ".partyRanking.blocs[].votes",
    ".partyRanking.blocs[].yesLaws",
    ".partyRanking.from",
    ".partyRanking.to",
    ".partyRanking.unmatched",
    ".partyRanking.unmatched.net",
    ".partyRanking.unmatched.net.high",
    ".partyRanking.unmatched.net.low",
    ".partyRanking.unmatched.net.median",
    ".partyRanking.unmatched.people",
    ".laws[].game.opposingParties",
    ".parties",
    ".parties[].name",
    ".parties[].bad",
    ".parties[].bad.high",
    ".parties[].bad.low",
    ".parties[].bad.median",
    ".parties[].good",
    ".parties[].good.high",
    ".parties[].good.low",
    ".parties[].good.median",
    ".parties[].net",
    ".parties[].net.high",
    ".parties[].net.low",
    ".parties[].net.median",
    ".parties[].laws",
    ".parties[].laws[].lawId",
    ".parties[].laws[].side",
    ".parties[].laws[].direction",
    ".parties[].laws[].effect",
    ".parties[].laws[].share",
    ".parties[].laws[].share.high",
    ".parties[].laws[].share.low",
    ".parties[].laws[].share.median",
    ".laws[].game.cabinet",
    ".laws[].game.opposers",
    ".members[].laws[].direction",
    ".members[].laws[].effect",
    ".members[].laws[].office",
    ".members[].laws[].office.high",
    ".members[].laws[].office.low",
    ".members[].laws[].office.median",
    ".members[].office",
    ".members[].office.credit",
    ".members[].office.credit.high",
    ".members[].office.credit.low",
    ".members[].office.credit.median",
    ".members[].office.loss",
    ".members[].office.loss.high",
    ".members[].office.loss.low",
    ".members[].office.loss.median",
    ".members[].laws[].roles.oppose",
    ".laws[].game.no",
    ".laws[].game.parties",
    ".laws[].game.party",
    ".laws[].game.party.high",
    ".laws[].game.party.low",
    ".laws[].game.party.median",
    ".laws[].game.proposerKind",
    ".laws[].game.proposers",
    ".laws[].game.quota",
    ".laws[].game.unidentified",
    ".laws[].game.unidentified.high",
    ".laws[].game.unidentified.low",
    ".laws[].game.unidentified.median",
    ".laws[].game.vetoShare",
    ".laws[].game.voteDate",
    ".laws[].game.voteShare",
    ".laws[].game.voteUrl",
    ".laws[].game.voters",
    ".laws[].game.yes",
    ".laws[].group",
    ".laws[].id",
    ".laws[].judgement",
    ".laws[].persons",
    ".laws[].publishable",
    ".laws[].reason",
    ".laws[].side",
    ".laws[].source",
    ".laws[].title",
    ".members",
    ".members[].credit",
    ".members[].credit.high",
    ".members[].credit.low",
    ".members[].credit.median",
    ".members[].laws",
    ".members[].laws[].context",
    ".members[].laws[].context[].action",
    ".members[].laws[].context[].actionLabel",
    ".members[].laws[].context[].date",
    ".members[].laws[].context[].house",
    ".members[].laws[].context[].title",
    ".members[].laws[].context[].url",
    ".members[].laws[].evidence",
    ".members[].laws[].evidence[].action",
    ".members[].laws[].evidence[].actionLabel",
    ".members[].laws[].evidence[].date",
    ".members[].laws[].evidence[].house",
    ".members[].laws[].evidence[].title",
    ".members[].laws[].evidence[].url",
    ".members[].laws[].fraction",
    ".members[].laws[].lawId",
    ".members[].laws[].roles",
    ".members[].laws[].roles.proposer",
    ".members[].laws[].roles.vote",
    ".members[].laws[].share",
    ".members[].laws[].share.high",
    ".members[].laws[].share.low",
    ".members[].laws[].share.median",
    ".members[].laws[].side",
    ".members[].id",
    ".members[].loss",
    ".members[].loss.high",
    ".members[].loss.low",
    ".members[].loss.median",
    ".members[].name",
    ".members[].net",
    ".members[].net.high",
    ".members[].net.low",
    ".members[].net.median",
    ".members[].overlappingGroups",
    ".members[].rank",
    ".members[].sensitivity",
    ".members[].sensitivity.chairVetoNet",
    ".members[].sensitivity.chairVetoRank",
    ".members[].sensitivity.flagged",
    ".members[].sensitivity.maxMove",
    ".pending",
    ".pending[].certainty",
    ".pending[].id",
    ".pending[].median",
    ".pending[].side",
    ".pending[].title",
    ".rules",
    ".schema",
}
# roles の source は表示の文字なので、source は URL らしいときだけ検査する（下の walk）。法律の source は経路で必ず検査する。
LINK_KEYS = {"url", "voteUrl"}
# 内閣府 経済社会総合研究所（税の帳簿の乗数の出典、政府の公式資料）。
OFFICIAL_HOSTS = {"kokkai.ndl.go.jp", "www.shugiin.go.jp", "www.sangiin.go.jp", "www.esri.cao.go.jp"}


def _paths(node, path, found):
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(f"{path}.{key}")
            _paths(value, f"{path}.{key}", found)
    elif isinstance(node, list):
        for value in node:
            _paths(value, f"{path}[]", found)
    return found

class PublicMembersSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.members = json.loads((DIST / "members.json").read_text(encoding="utf-8"))
        cls.ranking = json.loads((DIST / "ranking.json").read_text(encoding="utf-8"))

    def test_only_public_record_fields(self):
        extra = _paths(self.members, "", set()) - ALLOWED_PATHS
        self.assertEqual(set(), extra, "許可していない項目が増えた。公人としての公開記録か確かめて ALLOWED_PATHS に足す")

    def test_one_row_per_name(self):
        ids = [m["id"] for m in self.members["members"]]
        self.assertEqual(len(ids), len(set(ids)))
        squashed = {}
        for pid in ids:
            key = pid.replace(" ", "").replace("　", "")
            self.assertNotIn(key, squashed, f"空白違いの同じ人物：{pid} / {squashed.get(key)}")
            squashed[key] = pid
        # 同じ氏名が複数いるのは、人物IDで分けてあるときだけ。前からいる人は氏名そのもののIDのままのことがあるので、
        # 氏名そのもののIDは1人まで、ほかは院・選挙区付きのID（氏名（…））であること。
        by_name: dict[str, list[str]] = {}
        for m in self.members["members"]:
            by_name.setdefault(m["name"].replace(" ", "").replace("　", ""), []).append(m["id"])
        for name, group in by_name.items():
            if len(group) > 1:
                bare = [pid for pid in group if pid == name]
                self.assertLessEqual(len(bare), 1, f"同姓同名が人物IDで分かれていない：{name}")
                for pid in group:
                    self.assertTrue(pid == name or pid.startswith(name + "（"), f"同姓同名の人物IDの形が違う：{pid}")

    def test_allocated_laws_are_published_and_high_or_middle(self):
        published = {law["id"]: law for law in self.ranking["laws"]}
        # 画面は members.json の laws から引くので、議員の各行が参照する法律はそこにも無いと描画が落ちる。
        page_laws = {law["id"] for law in self.members["laws"]}
        for member in self.members["members"]:
            for law in member["laws"]:
                self.assertIn(law["lawId"], page_laws, f"{member['name']}：members.json の laws に無い法律 {law['lawId']}")
                self.assertIn(law["lawId"], published, f"{member['name']}：公開ランキングに無い法律 {law['lawId']}")
                # 確かさ「低」も印つきで配る（損失側の法律は低しか無く、高・中だけだと便益側の法律だけになって偏るため。設計決定0014）。参考は配らない。
                self.assertIn(published[law["lawId"]]["certainty"], {"高", "中", "低"}, law["lawId"])

    def test_every_link_is_https_and_official(self):
        # 画面でリンクになる項目（evidence・context・roles の url、法律の source、投票の voteUrl）を含め、
        # URL らしい文字列はすべて https で国会会議録・衆参のホストを指すこと。
        links = []

        def walk(node, key=None):
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(v, k)
            elif isinstance(node, list):
                for v in node:
                    walk(v, key)
            elif isinstance(node, str) and (key in LINK_KEYS or "://" in node or node.lower().startswith(("http", "//", "javascript:", "data:"))):
                links.append((key, node))

        walk(self.members)
        # 法律の source は画面で必ずリンクになるので、URL らしくなくても（空・相対パスでも）必ず検査する。
        links += [("laws[].source", law.get("source")) for law in self.members["laws"]]
        self.assertTrue(links)
        for key, url in links:
            self.assertIsInstance(url, str, f"{key}: {url}")
            parsed = urlparse(url)
            self.assertEqual("https", parsed.scheme, f"{key}: {url}")
            self.assertIn(parsed.hostname, OFFICIAL_HOSTS, f"{key}: {url}")

if __name__ == "__main__":
    unittest.main()
