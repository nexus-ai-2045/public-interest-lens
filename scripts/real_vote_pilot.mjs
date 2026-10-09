/** 保存済み公式投票の全行を非公開評価へ接続する有限実行入口。 */
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { readFile, realpath, lstat, mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve, isAbsolute } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { runEvidencePipeline, writeReviewPacket } from './evidence_pipeline.mjs';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const digest = value => createHash('sha256').update(value).digest('hex');
const canonical = value => Array.isArray(value)
  ? `[${value.map(canonical).join(',')}]`
  : value && typeof value === 'object'
    ? `{${Object.keys(value).filter(k => value[k] !== undefined).sort().map(k => `${JSON.stringify(k)}:${canonical(value[k])}`).join(',')}}`
    : JSON.stringify(value);
const inside = (root, file) => {
  const rel = relative(root, file);
  return rel && rel !== '..' && !rel.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) && !isAbsolute(rel);
};
const compact = value => value.replace(/\s+/gu, '');
const textOnly = value => value.replace(/<[^>]*>/gu, '');
const requireThat = (condition, reason) => { if (!condition) throw new Error(reason); };
function electionYears(history) {
  let era = '';
  return history.split('、').map(part => {
    const match = /^(平成|令和)?(元|\d+)年$/u.exec(part.trim());
    if (!match) return null;
    if (match[1]) era = match[1];
    const year = match[2] === '元' ? 1 : Number(match[2]);
    return era === '平成' ? 1988 + year : era === '令和' ? 2018 + year : null;
  });
}

async function readRegistered(recordPath, root) {
  const base = await realpath(root);
  const path = await realpath(recordPath);
  requireThat(inside(base, path) && !(await lstat(recordPath)).isSymbolicLink(), '登録原本の保存先が不正です');
  const record = JSON.parse(await readFile(path, 'utf8'));
  requireThat(record.schema_version === 'external-material/v1' && /^[a-f0-9]{64}$/.test(record.sha256)
    && /^original\.[a-z0-9]+$/.test(record.saved_filename), '登録原本のメタデータが不正です');
  const originalPath = join(dirname(path), record.saved_filename);
  requireThat(!(await lstat(originalPath)).isSymbolicLink(), '原本リンクは禁止です');
  const original = await readFile(originalPath);
  requireThat(original.length === record.bytes && digest(original) === record.sha256, '登録原本のハッシュが不一致です');
  return { record, html: original.toString('utf8') };
}

export async function readVoteMaterials(refs, materialRoot) {
  return new Promise((accept, reject) => {
    const child = spawn('python', ['-m', 'scripts.read_evidence_materials', '--material-root', materialRoot, '--include-source-record'],
      { cwd: repoRoot, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' }, stdio: ['pipe', 'pipe', 'pipe'] });
    let output = '', size = 0;
    const timer = setTimeout(() => { child.kill(); reject(new Error('原本照合が時間切れです')); }, 30_000);
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      size += Buffer.byteLength(chunk);
      if (size > 8_000_000) { child.kill(); reject(new Error('原本照合の出力上限を超えました')); }
      else output += chunk;
    });
    child.stderr.resume();
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', code => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error('登録投票原本を照合できません'));
      else { try { accept(JSON.parse(output)); } catch (error) { reject(error); } }
    });
    child.stdin.on('error', () => {});
    child.stdin.end(canonical(refs));
  });
}

/** 読めたプロフィールだけを議員IDへ結合する。名前だけの結合を禁止する。 */
export async function resolveProfiles(manifest, voteMaterials, materialRoot) {
  requireThat(manifest?.schemaVersion === 'vote-identities/v1' && Array.isArray(manifest.profiles)
    && typeof manifest.listRecordPath === 'string', '人物照合台帳が不正です');
  const list = await readRegistered(manifest.listRecordPath, materialRoot);
  requireThat(list.record.source_url === 'https://www.sangiin.go.jp/japanese/joho1/kousei/giin/221/giin.htm', '議員一覧の出典が不正です');
  const byVote = new Map(voteMaterials.map(m => [
    digest(canonical([m.sourceRecord.policyId, m.sourceRecord.date, compact(m.sourceRecord.nameText)])), m]));
  requireThat(byVote.size === voteMaterials.length, '同名の投票観測が競合しています');
  const resolved = new Map(), usedProfiles = new Set();
  const yearText = Object.fromEntries(Array.from({ length: 14 }, (_, offset) => {
    const year = 2013 + offset;
    return [year, year < 2019 ? `平成${year - 1988}年` : year === 2019 ? '令和元年' : `令和${year - 2018}年`];
  }));
  // プロフィールの当選年欄は補選年を通常選挙年と混在・省略表記する場合がある。
  // 選挙別の公式結果を接続するまで補選は自動照合しない。
  const electionText = { regular: '通常選挙' };
  for (const entry of manifest.profiles) {
    requireThat(entry && /^[a-f0-9]{64}$/.test(entry.voteKey) && /^[0-9]{7}$/.test(entry.profileId)
      && Object.hasOwn(yearText, entry.electionYear) && !resolved.has(entry.voteKey)
      && Object.hasOwn(electionText, entry.electionKind)
      && [2019, 2022, 2025].includes(entry.electionYear)
      && typeof entry.district === 'string' && /^(?:比例代表|選挙区（[^）]+）)$/.test(entry.district)
      && !usedProfiles.has(entry.profileId), '人物照合行が不正または重複しています');
    const vote = byVote.get(entry.voteKey);
    requireThat(vote?.sourceRecord._kind === 'vote', '人物照合先の投票行がありません');
    const actionYear = Number(vote.sourceRecord.date.slice(0, 4));
    const mandateYear = entry.mandateYear ?? entry.electionYear;
    // 同年の投票は正確な任期開始日が別資料で必要。年だけでは自動照合しない。
    requireThat(Object.hasOwn(yearText, mandateYear) && mandateYear < actionYear
      && actionYear < mandateYear + 6,
    '投票時の在職に対応する選挙年が確認できません');
    const profile = await readRegistered(entry.profileRecordPath, materialRoot);
    const url = `https://www.sangiin.go.jp/japanese/joho1/kousei/giin/profile/${entry.profileId}.htm`;
    const match = profile.html.match(/<h1\s+class="profile-name"[^>]*>([^<]+)<\/h1>/u);
    const memberName = match?.[1].split('（')[0] ?? '';
    const listAnchor = new RegExp(`<a\\s+href=["']\\.\\./profile/${entry.profileId}\\.htm["'][^>]*>([^<]+)<\\/a>`, 'u').exec(list.html);
    const electionLine = profile.html.match(/<dd>([^<]*(?:通常選挙|補欠選挙)[^<]*)<\/dd>/u)?.[1] ?? '';
    const history = electionLine.split('／')[2] ?? '';
    requireThat(profile.record.source_url === url && compact(memberName) === compact(vote.sourceRecord.nameText)
      && compact(textOnly(listAnchor?.[1] ?? '')) === compact(vote.sourceRecord.nameText)
      && electionLine.startsWith(`${electionText[entry.electionKind]}／${entry.district}選出／`)
      && history.includes(yearText[entry.electionYear])
      && electionYears(history).includes(mandateYear),
    '投票行・議員一覧・プロフィール・対象選挙が一致しません');
    usedProfiles.add(entry.profileId);
    resolved.set(entry.voteKey, {
      id: `sangiin-${entry.profileId}`, name: vote.sourceRecord.nameText,
      house: '参議院', district: entry.district,
      electionIds: [`sangiin-${entry.electionKind}-${entry.electionYear}-${entry.district}`],
      roleClass: '議員',
    });
  }
  return resolved;
}

export function makePilotInput(materials, profiles, asOf, policyId, period = 4, analysis = {}) {
  requireThat(analysis && Object.keys(analysis).every(k => ['assessments', 'analysisMaterials'].includes(k)), '分析入口のフィールドが不正です');
  const assessments = structuredClone(analysis.assessments ?? []);
  const analysisMaterials = analysis.analysisMaterials ?? [];
  requireThat(Array.isArray(assessments) && Array.isArray(analysisMaterials), '分析一覧が不正です');
  requireThat([4, 8].includes(period), '実評価の期間が不正です');
  requireThat(Array.isArray(materials) && materials.length > 0 && new Set(materials.map(m => m.id)).size === materials.length, '投票資料が空または重複しています');
  const people = [], actions = [], plainMaterials = [];
  const counts = { for: 0, against: 0, not_voted: 0, unknown: 0 };
  const observedNames = new Set();
  for (const material of materials) {
    const row = material.sourceRecord;
    requireThat(row?._kind === 'vote' && row.policyId === policyId && row.date <= asOf
      && row.locator.includes('allPublishedRowsConfirmed=True') && Object.hasOwn(counts, row.position)
      && typeof material.text === 'string' && material.text.length > 0, '投票行の政策・日付・完全性が不正です');
    const observedKey = canonical([policyId, row.date, compact(row.nameText)]);
    requireThat(!observedNames.has(observedKey), '同じ投票に同名の観測行があります');
    observedNames.add(observedKey);
    counts[row.position]++;
    const person = profiles.get(digest(observedKey)) ?? { id: `vote-observation-${digest(observedKey)}`, name: row.nameText };
    // 原本hash・HTML行番号・賛否は訂正で変わり得るため、行動IDから除外する。
    const identity = { namespace: 'sangiin-plenary-vote/v1', sourceActionId: `${policyId}@${row.date}`,
      sourceActorId: digest(compact(row.nameText)), policyId };
    const semantic = { ...identity, personId: person.id, policyVersion: `${policyId}@${row.date}`,
      actionDate: row.date, role: 'vote', position: row.position,
      description: `${row.date}参議院本会議の個人別投票の原表抽出結果（${row.locator}）`,
      quotes: [{ materialId: material.id, start: 0, end: material.text.length, text: material.text }] };
    people.push(person);
    actions.push({ ...semantic, actionId: digest(canonical([identity.namespace, identity.sourceActionId, identity.sourceActorId, identity.policyId])),
      revisionId: digest(canonical(semantic)) });
    plainMaterials.push({ id: material.id, url: material.url, originalHash: material.originalHash,
      contentHash: material.contentHash, observedAt: material.observedAt, publishedAt: material.publishedAt });
  }
  requireThat(new Set(people.map(p => p.id)).size === people.length, '一人に複数行が競合しています');
  for (const material of analysisMaterials) {
    requireThat(!plainMaterials.some(m => m.id === material.id), '分析資料IDが重複しています');
    plainMaterials.push({ id: material.id, url: material.url, originalHash: material.originalHash,
      contentHash: material.contentHash, observedAt: material.observedAt, publishedAt: material.publishedAt });
  }
  return { counts, input: { schemaVersion: 'evidence-evaluation/v1', mode: 'real',
    options: { domain: 'economy', direction: 'benefit', period, asOf, weights: { economy: 70, technology: 30 } },
    people, materials: plainMaterials, actions, assessments } };
}

export function verifyPilot(input, originalMaterials, profiles, inputHash, analysisMaterials = []) {
  const rebuilt = makePilotInput(originalMaterials, profiles, input.options.asOf, input.actions[0]?.policyId, input.options.period,
    { analysisMaterials }).input;
  requireThat(canonical({ ...input, assessments: [] }) === canonical(rebuilt), '独立原本と評価入力が不一致です');
  return { inputHash, verifierId: 'registered-vote-and-profile-readback', verifierVersion: '1',
    resolvedPersonIds: [...profiles.values()].map(p => p.id),
    actionRevisions: input.actions.map(a => ({ id: a.actionId, revisionId: a.revisionId })),
    assessmentRevisions: [] };
}

const freeze = value => { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };
/** 引用一致は影響妥当性の承認ではない。尺度・反証・代替説明の独立審査は実行側callbackの責務。 */
export async function verifyPilotAssessments(input, originalMaterials, profiles, inputHash, analysisMaterials = [], verifyAssessments) {
  const receipt = verifyPilot(input, originalMaterials, profiles, inputHash, analysisMaterials);
  if (!verifyAssessments) return receipt;
  const snapshot = freeze(structuredClone(input));
  const revisions = await verifyAssessments(snapshot, freeze(structuredClone(analysisMaterials)), inputHash);
  requireThat(Array.isArray(revisions) && new Set(revisions.map(r => r?.id)).size === revisions.length, '分析検証改訂が不正です');
  for (const revision of revisions) {
    const assessment = input.assessments.find(a => a.id === revision?.id);
    requireThat(revision && Object.keys(revision).every(k => ['id', 'revisionId'].includes(k))
      && assessment && revision.revisionId === digest(canonical(assessment)), '分析検証改訂が不一致です');
    requireThat(Array.isArray(assessment.quotes) && assessment.quotes.length > 0 && assessment.quotes.every(q => {
      const material = [...originalMaterials, ...analysisMaterials].find(m => m.id === q.materialId);
      return material && digest(material.text) === material.contentHash && Number.isSafeInteger(q.start)
        && Number.isSafeInteger(q.end) && q.start >= 0 && q.start < material.text.length
        && q.end > q.start && q.end <= material.text.length && material.text.slice(q.start, q.end) === q.text;
    }), '分析原本の引用が不一致です');
  }
  receipt.assessmentRevisions = structuredClone(revisions);
  return receipt;
}

/** verifierのCLI importやJSON自己承認は許さず、programmatic呼出だけで独立能力を渡す。 */
export async function runRealVotePilot({ args = process.argv.slice(2), verifyAssessments } = {}) {
  const required = ['--source', '--material-root', '--identities', '--identity-root', '--output-dir', '--policy-id'];
  requireThat([12, 14].includes(args.length) && required.every(k => args.includes(k))
    && args.filter((_, i) => i % 2 === 0).every(k => [...required, '--analysis'].includes(k))
    && new Set(args.filter((_, i) => i % 2 === 0)).size === args.length / 2,
    '必要な引数: --source --material-root --identities --identity-root --output-dir --policy-id');
  const values = Object.fromEntries(Array.from({ length: args.length / 2 }, (_, i) => args.slice(i * 2, i * 2 + 2)));
  const source = JSON.parse(await readFile(resolve(values['--source']), 'utf8'));
  requireThat(source.schemaVersion === 'ranking-dataset/v1' && source.fictional === false
    && source.evidenceEvaluation?.mode === 'real' && source.evidenceEvaluation.actions.length === 0
    && source.evidenceEvaluation.options?.asOf === source.asOf
    && [4, 8].includes(source.evidenceEvaluation.options?.period)
    && Array.isArray(source.readableEvidence?.votes), '保存済み閲覧入力の版が不正です');
  const voteRefs = source.materialRefs.filter(ref => ref.selector?.kind === 'vote-row' && ref.selector.billId === values['--policy-id']);
  requireThat(voteRefs.length === source.readableEvidence.votes.length && voteRefs.length > 0, '投票行の全件入力が揃いません');
  const analysis = values['--analysis'] ? JSON.parse(await readFile(resolve(values['--analysis']), 'utf8'))
    : { assessments: source.evidenceEvaluation.assessments ?? [], materialRefs: [] };
  requireThat(analysis && Object.keys(analysis).every(k => ['assessments', 'materialRefs'].includes(k))
    && Array.isArray(analysis.assessments) && Array.isArray(analysis.materialRefs), '分析入力が不正です');
  const refs = [...voteRefs, ...source.materialRefs.filter(ref => ref.selector?.kind !== 'vote-row'), ...analysis.materialRefs];
  const materialRoot = resolve(values['--material-root']), identityRoot = resolve(values['--identity-root']),
    outputDir = resolve(values['--output-dir']);
  const firstMaterials = await readVoteMaterials(refs, materialRoot);
  const firstRead = firstMaterials.slice(0, voteRefs.length);
  const analysisMaterials = firstMaterials.slice(voteRefs.length);
  const identityManifest = JSON.parse(await readFile(resolve(values['--identities']), 'utf8'));
  const profiles = await resolveProfiles(identityManifest, firstRead, identityRoot);
  const { input, counts } = makePilotInput(firstRead, profiles, source.asOf, values['--policy-id'],
    source.evidenceEvaluation.options.period, { assessments: analysis.assessments, analysisMaterials });
  const identityAudit = firstRead.map(material => {
    const row = material.sourceRecord;
    const voteKey = digest(canonical([row.policyId, row.date, compact(row.nameText)]));
    const resolved = profiles.get(voteKey);
    return { voteKey, sourceRowId: row.id, materialId: material.id, nameText: row.nameText,
      position: row.position, status: resolved ? 'resolved' : 'not_reviewed',
      ...(resolved ? { personId: resolved.id } : { reason: '公式プロフィールと対象選挙の照合は未着手' }) };
  });
  requireThat(identityAudit.length === voteRefs.length && new Set(identityAudit.map(row => row.voteKey)).size === voteRefs.length,
    '人物照合の全行台帳が不正です');
  requireThat(source.readableEvidence.votes.every(row => firstRead.some(m => m.sourceRecord.id === row.id
    && m.text === row.text && m.sourceRecord.position === row.position)), '閲覧行と原本の一致が崩れています');
  const vite = await import(pathToFileURL(join(repoRoot, 'app/node_modules/vite/dist/node/index.js')).href);
  const built = await vite.build({ configFile: false, root: join(repoRoot, 'app'), logLevel: 'silent',
    build: { write: false, minify: false, target: 'esnext', lib: { entry: join(repoRoot, 'app/src/evidence-evaluation.ts'), formats: ['es'] } } });
  const chunks = (Array.isArray(built) ? built : [built]).flatMap(bundle => bundle.output);
  const chunk = chunks.find(item => item.type === 'chunk' && item.isEntry);
  requireThat(chunk && chunk.imports.length === 0, '算定bundleが不正です');
  const evaluator = await import(`data:text/javascript;base64,${Buffer.from(chunk.code).toString('base64')}`);
  const release = await runEvidencePipeline({ materialRefs: refs, evidenceEvaluation: input }, {
    repoRoot, outputDir, engineHash: digest(chunk.code), evaluate: evaluator.evaluateEvidence,
    readMaterials: async () => (await readVoteMaterials(refs, materialRoot)).map(({ sourceRecord: _sourceRecord, ...material }) => material),
    verifyEvidence: async (snapshot, _stored, inputHash) => {
      const independentMaterials = await readVoteMaterials(refs, materialRoot);
      const independentlyRead = independentMaterials.slice(0, voteRefs.length);
      const independentlyResolved = await resolveProfiles(identityManifest, independentlyRead, identityRoot);
      return verifyPilotAssessments(snapshot, independentlyRead, independentlyResolved, inputHash,
        independentMaterials.slice(voteRefs.length), verifyAssessments);
    },
  });
  const review = await writeReviewPacket(release, { repoRoot, outputDir });
  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, 'candidate-input.json'), canonical({ materialRefs: refs, evidenceEvaluation: input }) + '\n', { flag: 'w', mode: 0o600 });
  await writeFile(join(outputDir, 'identity-audit.json'), canonical({ schemaVersion: 'vote-identity-audit/v1',
    policyId: values['--policy-id'], rows: identityAudit }) + '\n', { flag: 'w', mode: 0o600 });
  const summary = { releaseId: release.releaseId, voteRows: voteRefs.length, counts,
    inputAssessments: input.assessments.length, verifiedAssessments: release.verification.assessmentRevisions.length,
    period: input.options.period, asOf: input.options.asOf, policyId: values['--policy-id'],
    resolvedPeople: profiles.size, identityNotReviewed: identityAudit.filter(row => row.status === 'not_reviewed').length,
    verifiedActions: release.verification.actionRevisions.length,
    assessedActions: release.result.coverage.assessedActions, held: release.result.held.length,
    m2Status: review.m2Status, publicationStatus: review.publicationStatus };
  await writeFile(join(outputDir, 'run-summary.json'), canonical(summary) + '\n', { flag: 'w', mode: 0o600 });
  console.log(JSON.stringify(summary));
  return { release, review, summary };
}
if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url)
  runRealVotePilot().catch(error => { console.error(error.message); process.exitCode = 1; });
