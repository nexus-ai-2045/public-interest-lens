import { useState } from 'react';
import { Share2 } from 'lucide-react';

/** 端末の共有を使い、無ければリンクをコピーする。押した手ごたえ（弾む）を返す。 */
export function ShareButton({ title, text, url, label = 'シェアする' }: { title: string; text: string; url: string; label?: string }) {
  const [message, setMessage] = useState('');
  const [pop, setPop] = useState(0);
  const share = async () => {
    setPop(value => value + 1);
    try {
      if (navigator.share) { await navigator.share({ title, text, url }); setMessage('共有しました'); return; }
      await navigator.clipboard.writeText(`${text} ${url}`);
      setMessage('リンクをコピーしました');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      setMessage(`コピーできませんでした：${url}`);
    }
  };
  return <span className="m-share"><button type="button" key={pop} className={`m-share-button ${pop ? 'is-pop' : ''}`} onClick={() => void share()}><Share2 size={16} />{label}</button><span className="m-share-message" role="status">{message}</span></span>;
}
