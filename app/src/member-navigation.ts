import { readKnobs, writeKnobs } from './causal-allocation';

export function memberLocation(id: string, search: string, anchor = false): string {
  const current = new URLSearchParams(search);
  const params = writeKnobs(new URLSearchParams({ name: id }), readKnobs(current));
  const tone = current.get('tone');
  if (tone === 'harm' || tone === 'benefit' || tone === 'kokuzoku' || tone === 'kokushi') params.set('tone', tone);
  return `/members?${params}${anchor ? `#member-${encodeURIComponent(id)}` : ''}`;
}
