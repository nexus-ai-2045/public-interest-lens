/** Sites向けの静的公開版では、端末内の非公開データへ接続しません。 */
export const PUBLIC_SITE = import.meta.env.VITE_PUBLIC_SITE === 'true';
