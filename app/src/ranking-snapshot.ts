import { RANKING_VERSION, type RankingDataset } from './ranking';
import { rankingDataset } from './ranking-data';

/** 架空データ全文と算定契約のSHA-256。変更時はactionRevisionによるテストで再生成を要求します。 */
export const RANKING_CONTENT_SHA256 = '3a23649e21f5c6779f846883bf2f81790569e87f21be6b76fdd8520da9f6850a';
export const rankingSnapshotContent = (data: RankingDataset) => ({ criterion: RANKING_VERSION, data });

/** actionRevisionと同じキー順・UTF-8化前の正規化表現です。ハッシュ処理は実装しません。 */
export function serializeRankingSnapshot(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(serializeRankingSnapshot).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).filter(([, item]) => item !== undefined).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${serializeRankingSnapshot(item)}`).join(',')}}`;
  return JSON.stringify(value);
}

// 現在の正本をモジュール初期化時に文字列へ固定し、後続の参照・clone・mutable objectと区別します。
const registeredSnapshot = serializeRankingSnapshot(rankingSnapshotContent(rankingDataset));
export function registeredRankingVersion(data: RankingDataset): string {
  if (serializeRankingSnapshot(rankingSnapshotContent(data)) !== registeredSnapshot) throw new Error('指定された評価版のデータ内容が登録済みの版と一致しません。');
  return `${RANKING_VERSION}:${RANKING_CONTENT_SHA256}`;
}
