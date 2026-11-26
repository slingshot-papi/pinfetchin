/**
 * Progressive Web App (PWA) Registration and Installation Prompt
 * Enables users on Android/Chrome, iPhone/Safari, and Desktop to install as an app
 */

let deferredPrompt = null;

// Register Service Worker
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js', { scope: '/' })
            .then((reg) => {
                console.log('[PWA] Service Worker registered successfully with scope:', reg.scope);
            })
            .catch((err) => {
                console.warn('[PWA] Service Worker registration failed:', err);
            });
    });
}

// Handle BeforeInstallPrompt event (Android Chrome, Edge, Desktop Chrome)
window.addEventListener('beforeinstallprompt', (e) => {
    // Prevent default browser mini-infobar
    e.preventDefault();
    deferredPrompt = e;

    // Show Install App button in header
    const pwaBtn = document.getElementById('pwaInstallBtn');
    if (pwaBtn) {
        pwaBtn.style.display = 'inline-flex';
        pwaBtn.addEventListener('click', async () => {
            if (!deferredPrompt) return;
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            console.log(`[PWA] User response to install prompt: ${outcome}`);
            deferredPrompt = null;
            pwaBtn.style.display = 'none';
        });
    }
});

// Hide button once app is installed
window.addEventListener('appinstalled', () => {
    console.log('[PWA] PinFetch was installed successfully!');
    const pwaBtn = document.getElementById('pwaInstallBtn');
    if (pwaBtn) {
        pwaBtn.style.display = 'none';
    }
});
