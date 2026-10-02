import type { ReactNode } from 'react';

/** 架空デモと実評価の共通の製品表示。状態や公開可否の判定は呼び出し側が所有します。 */
export function ProductHeader({ title, label, children, brandHref = '#top' }: { title: string; label: string; children?: ReactNode; brandHref?: string }) {
  return <header className="topbar"><a className="brand" href={brandHref}><h1>{title}</h1><span className="prototype-label">{label}</span></a>{children}</header>;
}
