import { useLayoutEffect, useRef, type ReactNode } from 'react';

/** 収納中は操作対象から外し、閉じる際のフォーカスを入口へ戻します。 */
export function ExpandableControls({ expanded, children }: { expanded: boolean; children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    if (!expanded && element.contains(document.activeElement)) document.getElementById('advanced-toggle')?.focus();
    element.inert = !expanded;
  }, [expanded]);
  return <div id="advanced-settings" ref={root} className="expandable-controls" data-open={expanded} aria-hidden={!expanded}>
    <div className="expandable-inner">{children}</div>
  </div>;
}
