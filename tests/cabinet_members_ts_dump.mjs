// tests/test_auto_involvements.py が使う補助：app/src/cabinet-members.ts の cabinetForBill を成立法の全閣法に当て、法律ID→閣僚の氏名を JSON で返す。
// TS は vite で読む（拡張子なしの import を解くため）。入力はリポジトリ内の enacted.csv と cabinet.csv。
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const app = join(root, 'app');
const { createServer } = await import(join(app, 'node_modules/vite/dist/node/index.js'));
const server = await createServer({ root: app, logLevel: 'silent', server: { middlewareMode: true }, appType: 'custom' });
try {
  const { parseCsv } = await server.ssrLoadModule('/src/impact-batch.ts');
  const { cabinetForBill } = await server.ssrLoadModule('/src/cabinet-members.ts');
  const read = path => parseCsv(readFileSync(join(root, path), 'utf8'));
  const enacted = read('data/acquired/bill-census-full/enacted.csv');
  const lookup = cabinetForBill(enacted, read('data/acquired/office-holders/cabinet.csv'));
  const out = {};
  for (const bill of enacted) if (bill['種別'] === '閣法') out[`${bill['種別']}-${bill['提出回次']}-${bill['番号']}`] = lookup(bill).names;
  process.stdout.write(JSON.stringify(out));
} finally {
  await server.close();
}
