import { AlertTriangle } from 'lucide-react';
import { INTERIM_DISPLAY, INTERIM_NOTE, type InterimDisplay } from './interim-display';
import './interim.css';

/** 振り分けの当て直し中の注記。切り替え（interim-display.ts）が切れていれば何も出さない。 */
export function InterimNotice({ display = INTERIM_DISPLAY }: { display?: InterimDisplay }) {
  if (!display.active) return null;
  return <p className="interim-notice" role="note" aria-label={display.label}>
    <AlertTriangle size={16} aria-hidden="true" />
    <span><strong>{display.label}（{display.since}から）。</strong>{INTERIM_NOTE}</span>
  </p>;
}
