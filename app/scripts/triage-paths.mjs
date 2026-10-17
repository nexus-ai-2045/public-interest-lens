// アルゴリズム版 v1 と入力の振り分け版を別々に固定する。v1 の保存先は互換性のため維持する。
export function triagePaths(argv = process.argv.slice(2), env = process.env) {
  const index = argv.indexOf('--triage');
  const version = index >= 0 ? argv[index + 1] : env.TRIAGE_VERSION ?? 'v2';
  if (version !== 'v1' && version !== 'v2') throw new Error(`振り分けの版は v1 か v2: ${version}`);
  return {
    version,
    derived: stage => `data/derived/${stage}-v1${version === 'v2' ? '-triage-v2' : ''}/`,
  };
}
