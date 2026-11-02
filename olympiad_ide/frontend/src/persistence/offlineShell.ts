export function registerOfflineShell() {
  if (import.meta.env.PROD && 'serviceWorker' in navigator) {
    const base = import.meta.env.BASE_URL
    void navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).catch(() => {
      console.warn('Offline application cache could not be installed.')
    })
  }
}
