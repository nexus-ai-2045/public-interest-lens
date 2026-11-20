---- MODULE HyokaEngine ----
(* 直したあとの評価エンジン。公開ファイルを置く遷移だけを持つ。
   資料の中身や額の計算は持たない。

   直す前は、出典チェックを通さない書き込み（WriteUnchecked）と、
   開いた瞬間に中身を空にする書き込み（CrashWrite → partial）があった。
   直したあとは、照合済みの中身を一時ファイルへ書き、rename が成功したときだけ
   公開ファイルになる。rename の前に落ちても、前のファイルは変わらない。
   公開版のビルドは、照合済みのファイルだけを配信する。
   KOKUZOKU_SKIP_GENERATE は公開版のビルドでは生成を飛ばせない。

   file の unchecked と partial は、直しの前に起きていた状態として型に残す。
   直したあとの遷移からは到達しない。到達しないことを NoUncheckedPublished と
   NoPartialRemains で確かめる。 *)

VARIABLES phase, file, published

vars == <<phase, file, published>>

Phases == {"start", "ready", "scored", "checked"}
Files == {"none", "checked", "unchecked", "partial"}
Pubs == {"none", "checked", "unchecked"}

Init ==
  /\ phase = "start"
  /\ file = "none"
  /\ published = "none"

Fetch ==
  /\ phase = "start"
  /\ phase' = "ready"
  /\ UNCHANGED <<file, published>>

Score ==
  /\ phase = "ready"
  /\ phase' = "scored"
  /\ UNCHANGED <<file, published>>

Check ==
  /\ phase = "scored"
  /\ phase' = "checked"
  /\ UNCHANGED <<file, published>>

(* 照合済みの中身を rename で置く。途中のファイルは公開の置き場に残らない。 *)
WriteChecked ==
  /\ phase = "checked"
  /\ file = "none"
  /\ file' = "checked"
  /\ UNCHANGED <<phase, published>>

(* rename の前に落ちる。公開ファイルは置き換わらない。 *)
CrashBeforeRename ==
  /\ phase = "checked"
  /\ file = "none"
  /\ UNCHANGED vars

(* 公開版のビルドは、照合済みのファイルだけを配信する。 *)
PublishChecked ==
  /\ file = "checked"
  /\ published /= "checked"
  /\ published' = "checked"
  /\ UNCHANGED <<phase, file>>

Done ==
  /\ published = "checked"
  /\ UNCHANGED vars

Next ==
  \/ Fetch
  \/ Score
  \/ Check
  \/ WriteChecked
  \/ CrashBeforeRename
  \/ PublishChecked
  \/ Done

Spec == Init /\ [][Next]_vars

TypeOK ==
  /\ phase \in Phases
  /\ file \in Files
  /\ published \in Pubs

NoUncheckedPublished == published /= "unchecked"

NoPartialRemains == file /= "partial"

NoPartialPublished == published /= "partial"

CheckedPublishHasCheckedFile == published = "checked" => file = "checked"

====
