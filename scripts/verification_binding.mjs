/** evidence_pipeline の受領書検査のうち、ファイルシステムに依存しない部分。画面も同じ関数を使う。 */

export function canonical(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && Object.getPrototypeOf(value) === Object.prototype) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  throw new Error('JSON値が不正です');
}

export function fields(value, allowed) {
  if (!value || Array.isArray(value) || typeof value !== 'object' || Object.keys(value).some(k => !allowed.includes(k))) throw new Error('未許可の入力フィールドです');
}

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);
const rotr = (x, n) => (x >>> n) | (x << (32 - n));

/** Node の crypto を画面束ねに入れないための SHA-256。結果は createHash('sha256') と一致させる。 */
export function sha256Hex(message) {
  const data = new TextEncoder().encode(message);
  const bitLen = data.length * 8;
  const withOne = data.length + 1;
  const mod = withOne % 64;
  const padLen = mod <= 56 ? 56 - mod : 56 + 64 - mod;
  const buf = new Uint8Array(withOne + padLen + 8);
  buf.set(data);
  buf[data.length] = 0x80;
  const view = new DataView(buf.buffer);
  view.setUint32(buf.length - 8, Math.floor(bitLen / 0x100000000));
  view.setUint32(buf.length - 4, bitLen >>> 0);
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
  const w = new Uint32Array(64);
  for (let i = 0; i < buf.length; i += 64) {
    for (let t = 0; t < 16; t++) w[t] = view.getUint32(i + t * 4);
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3);
      const s1 = rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10);
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) >>> 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let t = 0; t < 64; t++) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = ((e & f) ^ (~e & g)) >>> 0;
      const temp1 = (h + s1 + ch + K[t] + w[t]) >>> 0;
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = ((a & b) ^ (a & c) ^ (b & c)) >>> 0;
      const temp2 = (s0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0; d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map(v => v.toString(16).padStart(8, '0')).join('');
}

export function validateVerification(input, receipt, inputHash, hash) {
  fields(receipt, ['inputHash', 'verifierId', 'verifierVersion', 'resolvedPersonIds', 'actionRevisions', 'assessmentRevisions']);
  if (receipt.inputHash !== inputHash || !['verifierId', 'verifierVersion'].every(k => typeof receipt[k] === 'string' && receipt[k].trim())) throw new Error('独立検証の入力束縛が不一致です');
  if (!Array.isArray(receipt.resolvedPersonIds) || new Set(receipt.resolvedPersonIds).size !== receipt.resolvedPersonIds.length
    || receipt.resolvedPersonIds.some(id => typeof id !== 'string' || !input.people.some(p => p.id === id))) throw new Error('人物検証の参照が不正です');
  for (const [key, source, idKey] of [['actionRevisions', 'actions', 'actionId'], ['assessmentRevisions', 'assessments', 'id']]) {
    const entries = receipt[key];
    if (!Array.isArray(entries) || new Set(entries.map(e => e?.id)).size !== entries.length) throw new Error('改訂検証が重複または不正です');
    for (const entry of entries) {
      fields(entry, ['id', 'revisionId']);
      const target = input[source].find(a => a[idKey] === entry.id);
      const revision = source === 'actions' ? target?.revisionId : target && hash(canonical(target));
      if (!target || typeof entry.revisionId !== 'string' || !/^[a-f0-9]{64}$/.test(entry.revisionId) || revision !== entry.revisionId) throw new Error('検証した改訂が入力と不一致です');
    }
  }
  receipt.resolvedPersonIds.sort();
  receipt.actionRevisions.sort((a, b) => a.id.localeCompare(b.id));
  receipt.assessmentRevisions.sort((a, b) => a.id.localeCompare(b.id));
  return receipt;
}
