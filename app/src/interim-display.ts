/**
 * 振り分けの当て直しが済むまでの暫定表示の切り替え（正本はここ1か所）。
 *
 * 2回目の抜き取り検証（2026-11-19）で、法律の振り分け（類型・経済に効くか・分野）の誤りが推定約958本残り、
 * 個別の額7本中4本が不合格と分かった。全件を一次資料で当て直すまで、
 *   - 個別の額の順位（棒・確かな額の上位）を止める
 *   - 参考の額（産業の差の参考・共有額の参考）を既定で畳み、注記を出す
 * データは消さず、表示を切り替えるだけ。当て直しと新しい抜き取りが済んだら active を false にすれば元の表示に戻る。
 * 曝露ランキング（議員の側）は、この切り替えとは別に公開データへ載せていない（scripts/generate_artifacts.py、設計決定0008）。
 */
export type InterimDisplay = {
  /** 暫定表示を使うか。false で元の表示に戻る。 */
  active: boolean;
  /** 画面に出す状態の名前。 */
  label: string;
  /** 暫定表示に切り替えた日。 */
  since: string;
};

export const INTERIM_DISPLAY: InterimDisplay = {
  active: true,
  label: '振り分けの当て直し中',
  since: '2026-11-19',
};

/** 個別の額の順位（棒・確かな額の上位・「明らかに悪い」の印）を止めているか。 */
export const rankingPaused = (display: InterimDisplay = INTERIM_DISPLAY) => display.active;

/** 参考の額（産業の差の参考・共有額の参考）を、産業ごとの分も含めて既定で畳むか。 */
export const foldAllReference = (display: InterimDisplay = INTERIM_DISPLAY) => display.active;

/** 画面に出す注記の本文。数は 2回目の抜き取りの推定（95%区間 約770〜1,360本）。 */
export const INTERIM_NOTE = '2回目の抜き取り検証で、法律の振り分け（類型・経済に効くか・分野）の誤りが、全体でまだ約960本（推定）残っていると分かりました。全件を一次資料で当て直すまで、法律の額の順位を止め、参考の額を畳んでいます。額と根拠は消さずに残しているので、開けば見られます。議員の順位も出していません。';
