// Registra il Service Worker (PWA)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/serviceworker.js')
            .then(reg => console.log('SW registrato:', reg.scope))
            .catch(err => console.log('SW errore:', err));
    });
}
