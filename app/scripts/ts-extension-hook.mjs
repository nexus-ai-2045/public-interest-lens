// app/src の TypeScript は拡張子なしで import し合う（vite と同じ書き方）。Node で直接読むときだけ「.ts」を補う。
export async function resolve(specifier, context, next) {
  if (/^\.\.?\//.test(specifier) && !/\.[cm]?[jt]s$/.test(specifier) && context.parentURL?.endsWith('.ts')) {
    try { return await next(`${specifier}.ts`, context); } catch { /* 補えなければ元の指定で解決する */ }
  }
  return next(specifier, context);
}
