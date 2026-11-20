---- MODULE HyokaEngine ----
(* 評価エンジンの公開までを、コードにある遷移だけに絞ったモデル。
   資料の中身や額の計算は持たない。持つのは、公開ファイルがどの作り方で置かれたか。

   file
     none       公開ランキングがまだ無い
     checked    今の中身を出典チェックしてから書いた（source_check.generate_ranking / rebuild）
     unchecked  出典チェックを通さずに書いた（build_public_ranking.main）
     partial    書き込みの途中で切れた（Path.write_text は開いた時点で空になる）

   published は、そのファイルをビルドが配信してよいと見なしたあとの値。
   半端なファイルは laws の生成が落ちるので、配信には進まない。
   検査なしの完全なファイルは、mtime が入力より新しければ generate_artifacts が作り直さない。

   議員ページの配信はアクションにしない。MembersPage の MEMBER_RANKING_HIDDEN が真のあいだ、
   その遷移はコード上で実行されない。確かさの下限が曝露の額に掛からないことは、このモデルの外で試験する。 *)

VARIABLES phase, file, published

vars == <<phase, file, published>>

Phases == {"start", "ready", "scored", "checked"}
Files == {"none", "checked", "unchecked", "partial"}
Pubs == {"none", "checked", "unchecked"}

Init ==
  /\ phase = "start"
  /\ file = "none"
  /\ published = "none"

(* daily_update が取得のあと再計算へ進む。strict の障害で止まる枝は、このランでは ready に来ない。 *)
Fetch ==
  /\ phase = "start"
  /\ phase' = "ready"
  /\ UNCHANGED <<file, published>>

Score ==
  /\ phase = "ready"
  /\ phase' = "scored"
  /\ UNCHANGED <<file, published>>

(* メモリ上で照合し、不一致は額の外へ出す。まだファイルは書かない。 *)
Check ==
  /\ phase = "scored"
  /\ phase' = "checked"
  /\ UNCHANGED <<file, published>>

(* 照合済みの中身を、ファイルが無いときだけ書く。mtime が新しいファイルは上書きしない。 *)
WriteChecked ==
  /\ phase = "checked"
  /\ file = "none"
  /\ file' = "checked"
  /\ UNCHANGED <<phase, published>>

(* 同じ書き込みが途中で切れる。切れたファイルは mtime が新しいので、次の生成は直さない。 *)
CrashWrite ==
  /\ phase = "checked"
  /\ file = "none"
  /\ file' = "partial"
  /\ UNCHANGED <<phase, published>>

(* build_public_ranking.main。前回の heldOut を読むだけで、今の中身は照合しない。 *)
WriteUnchecked ==
  /\ phase = "ready"
  /\ file = "none"
  /\ file' = "unchecked"
  /\ UNCHANGED <<phase, published>>

(* generate_artifacts が完全なファイルを新しいと見て飛ばし、ビルドがそのファイルを配信する。 *)
SkipPublish ==
  /\ file \in {"checked", "unchecked"}
  /\ published' = file
  /\ UNCHANGED <<phase, file>>

(* 照合済みの配信だけを、正しい終わりにする。 *)
Done ==
  /\ published = "checked"
  /\ UNCHANGED vars

Next ==
  \/ Fetch
  \/ Score
  \/ Check
  \/ WriteChecked
  \/ CrashWrite
  \/ WriteUnchecked
  \/ SkipPublish
  \/ Done

Spec == Init /\ [][Next]_vars

TypeOK ==
  /\ phase \in Phases
  /\ file \in Files
  /\ published \in Pubs

(* 配信された中身は、今の出典チェックを通ったファイルだけ。 *)
NoUncheckedPublished == published /= "unchecked"

(* 公開ファイルの置き場に、途中で切れた中身が残らない。 *)
NoPartialRemains == file /= "partial"

(* 途中で切れたファイルは配信しない。laws の生成が落ちる。 *)
NoPartialPublished == published /= "partial"

(* 照合済みとして配信したなら、ファイルも照合済みのまま。 *)
CheckedPublishHasCheckedFile == published = "checked" => file = "checked"

====
