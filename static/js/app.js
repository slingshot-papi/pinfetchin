/**
 * PinFetch Frontend Application Logic
 * Touch-optimized for mobile, tablet, and desktop
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const downloadForm = document.getElementById('downloadForm');
    const pinUrlInput = document.getElementById('pinUrlInput');
    const clearBtn = document.getElementById('clearBtn');
    const pasteBtn = document.getElementById('pasteBtn');
    const fetchBtn = document.getElementById('fetchBtn');
    const loadingBox = document.getElementById('loadingBox');
    const loadingStepTitle = document.getElementById('loadingStepTitle');
    const loadingStepDesc = document.getElementById('loadingStepDesc');
    const errorBox = document.getElementById('errorBox');
    const errorMessage = document.getElementById('errorMessage');
    
    // Result elements
    const resultSection = document.getElementById('resultSection');
    const videoPreview = document.getElementById('videoPreview');
    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    const resultTitle = document.getElementById('resultTitle');
    const creatorLink = document.getElementById('creatorLink');
    const badgeDuration = document.getElementById('badgeDuration');
    const badgeQuality = document.getElementById('badgeQuality');
    const badgeType = document.getElementById('badgeType');
    
    const btnPrimaryDownload = document.getElementById('btnPrimaryDownload');
    const primaryDlSubtext = document.getElementById('primaryDlSubtext');
    const formatsListContainer = document.getElementById('formatsListContainer');
    const btnDownloadAudio = document.getElementById('btnDownloadAudio');
    const btnDownloadThumbnail = document.getElementById('btnDownloadThumbnail');
    const btnCopyLink = document.getElementById('btnCopyLink');
    const copyLinkText = document.getElementById('copyLinkText');
    
    // Theme toggle
    const themeToggleBtn = document.getElementById('themeToggleBtn');
    const themeIconSun = document.getElementById('themeIconSun');
    const themeIconMoon = document.getElementById('themeIconMoon');
    
    // History
    const historySection = document.getElementById('historySection');
    const historyGrid = document.getElementById('historyGrid');
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');

    let currentMediaData = null;

    // -------------------------------------------------------------------------
    // 1. Theme Toggle (Dark / Light) with localStorage & System Preference
    // -------------------------------------------------------------------------
    const initTheme = () => {
        const savedTheme = localStorage.getItem('pinfetch_theme');
        if (savedTheme) {
            setTheme(savedTheme);
        } else {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            setTheme(prefersDark ? 'dark' : 'light');
        }
    };

    const setTheme = (theme) => {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('pinfetch_theme', theme);
        if (theme === 'dark') {
            themeIconSun.style.display = 'block';
            themeIconMoon.style.display = 'none';
        } else {
            themeIconSun.style.display = 'none';
            themeIconMoon.style.display = 'block';
        }
    };

    themeToggleBtn.addEventListener('click', () => {
        const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
        setTheme(currentTheme === 'dark' ? 'light' : 'dark');
    });

    initTheme();

    // -------------------------------------------------------------------------
    // 2. Input Handling (Clear & Clipboard Paste)
    // -------------------------------------------------------------------------
    const updateInputState = () => {
        clearBtn.style.display = pinUrlInput.value.trim().length > 0 ? 'flex' : 'none';
    };

    pinUrlInput.addEventListener('input', updateInputState);

    clearBtn.addEventListener('click', () => {
        pinUrlInput.value = '';
        updateInputState();
        pinUrlInput.focus();
    });

    pasteBtn.addEventListener('click', async () => {
        try {
            if (navigator.clipboard && navigator.clipboard.readText) {
                const text = await navigator.clipboard.readText();
                if (text && text.trim()) {
                    pinUrlInput.value = text.trim();
                    updateInputState();
                    showToast('Link pasted from clipboard!');
                    handleFetch();
                } else {
                    showToast('Clipboard is empty');
                }
            } else {
                pinUrlInput.focus();
                showToast('Please paste the URL manually');
            }
        } catch (err) {
            pinUrlInput.focus();
            showToast('Permission to access clipboard denied');
        }
    });

    // -------------------------------------------------------------------------
    // 3. Sample Links Handler
    // -------------------------------------------------------------------------
    document.querySelectorAll('.sample-pill').forEach(pill => {
        pill.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const sampleUrl = pill.getAttribute('data-url');
            if (sampleUrl) {
                pinUrlInput.value = sampleUrl;
                updateInputState();
                handleFetch();
            }
        });
    });

    // -------------------------------------------------------------------------
    // 4. Guide Tabs Switcher
    // -------------------------------------------------------------------------
    const tabButtons = document.querySelectorAll('.guide-tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const targetId = btn.getAttribute('data-tab');
            const targetContent = document.getElementById(targetId);
            if (targetContent) {
                targetContent.classList.add('active');
            }
        });
    });

    // -------------------------------------------------------------------------
    // 5. Main Fetch & Extraction Execution
    // -------------------------------------------------------------------------
    downloadForm.addEventListener('submit', (e) => {
        e.preventDefault();
        handleFetch();
    });

    const handleFetch = async () => {
        const rawUrl = pinUrlInput.value.trim();
        if (!rawUrl) {
            showError('Please enter or paste a Pinterest URL.');
            pinUrlInput.focus();
            return;
        }

        // Reset UI
        hideError();
        resultSection.style.display = 'none';
        videoPreview.pause();
        videoPreview.removeAttribute('src');
        videoPreview.load();

        // Show loading state with animated progress steps
        loadingBox.style.display = 'flex';
        fetchBtn.disabled = true;
        fetchBtn.style.opacity = '0.7';

        loadingStepTitle.textContent = 'Resolving Pinterest Link...';
        loadingStepDesc.textContent = 'Contacting Pinterest CDN and verifying media...';

        const stepTimer1 = setTimeout(() => {
            loadingStepTitle.textContent = 'Extracting Video Streams...';
            loadingStepDesc.textContent = 'Parsing HD resolutions and direct video formats...';
        }, 1200);

        try {
            const response = await fetch('/api/extract', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                body: JSON.stringify({ url: rawUrl })
            });

            clearTimeout(stepTimer1);

            const result = await response.json();

            if (!response.ok || !result.success) {
                throw new Error(result.error || 'Failed to extract video from this pin.');
            }

            currentMediaData = result;
            renderResult(result);
            saveToHistory(result);
        } catch (err) {
            clearTimeout(stepTimer1);
            showError(err.message || 'An unexpected error occurred. Please try again.');
        } finally {
            loadingBox.style.display = 'none';
            fetchBtn.disabled = false;
            fetchBtn.style.opacity = '1';
        }
    };

    // -------------------------------------------------------------------------
    // 6. Render Extracted Media & Formats
    // -------------------------------------------------------------------------
    const renderResult = (data) => {
        // Set metadata
        resultTitle.textContent = data.title || 'Pinterest Media';
        
        if (data.uploader) {
            creatorLink.textContent = data.uploader;
            creatorLink.href = data.uploader_url || data.webpage_url || '#';
        } else {
            creatorLink.textContent = 'Pinterest Creator';
            creatorLink.href = '#';
        }

        // Tags
        if (data.duration_str) {
            badgeDuration.textContent = `⏱ ${data.duration_str}`;
            badgeDuration.style.display = 'inline-block';
        } else {
            badgeDuration.style.display = 'none';
        }

        if (data.type === 'image') {
            badgeType.textContent = (data.is_carousel && data.images) ? `📸 Gallery (${data.images.length} Photos)` : '🖼 HD Image';
            badgeType.style.background = 'rgba(230, 0, 35, 0.15)';
            badgeType.style.color = '#FF5A79';
            badgeType.style.borderColor = 'rgba(230, 0, 35, 0.3)';
        } else {
            badgeType.textContent = '🎬 MP4 Video';
            badgeType.style.background = 'var(--bg-surface)';
            badgeType.style.color = 'var(--text-secondary)';
            badgeType.style.borderColor = 'var(--border-subtle)';
        }

        // Media Player vs Image
        if (data.type === 'video' && data.preview_url) {
            imagePreviewContainer.style.display = 'none';
            videoPreview.style.display = 'block';
            videoPreview.src = data.preview_url;
            if (data.thumbnail) {
                videoPreview.poster = data.thumbnail;
            }
            videoPreview.onerror = () => {
                if (bestFormat && bestFormat.url && !videoPreview.src.includes('/api/download')) {
                    videoPreview.src = `/api/download?url=${encodeURIComponent(bestFormat.url)}&title=${encodeURIComponent(data.title)}&type=video`;
                }
            };
        } else if (data.thumbnail || data.preview_url) {
            videoPreview.style.display = 'none';
            imagePreviewContainer.style.display = 'flex';
            imagePreview.src = data.preview_url || data.thumbnail;
        }

        // Best format for primary download
        const bestFormat = (data.formats && data.formats.length > 0) ? data.formats[0] : null;

        if (bestFormat) {
            badgeQuality.textContent = bestFormat.quality || (data.type === 'image' ? 'Original Max-Res' : 'HD');
            badgeQuality.style.display = 'inline-block';

            // Configure Primary Download Button
            const isImage = (data.type === 'image' || bestFormat.is_image);
            const primaryExt = isImage ? (bestFormat.ext || 'jpg') : 'mp4';
            const downloadProxyUrl = `/api/download?url=${encodeURIComponent(bestFormat.url)}&title=${encodeURIComponent(data.title)}&type=${data.type}`;
            
            btnPrimaryDownload.href = downloadProxyUrl;
            btnPrimaryDownload.setAttribute('download', `${sanitizeTitle(data.title)}.${primaryExt}`);
            
            const dlMainText = btnPrimaryDownload.querySelector('.dl-main-text');
            if (isImage) {
                dlMainText.textContent = 'Download Original Image';
                primaryDlSubtext.textContent = `${bestFormat.quality} (Uncompressed .${primaryExt.toUpperCase()})`;
            } else {
                dlMainText.textContent = 'Download Best Quality MP4';
                primaryDlSubtext.textContent = `${bestFormat.quality} (${bestFormat.resolution || 'HD'} • .MP4)`;
            }
        }

        // Render Formats Table
        formatsListContainer.innerHTML = '';
        if (data.formats && data.formats.length > 0) {
            data.formats.forEach((fmt) => {
                const row = document.createElement('div');
                row.className = 'format-row';

                const isHD = fmt.height >= 720 || (fmt.quality && fmt.quality.includes('HD')) || (fmt.quality && fmt.quality.includes('Original'));
                const fileExt = (data.type === 'image' || fmt.is_image) ? (fmt.ext || 'jpg') : 'mp4';
                const dlUrl = `/api/download?url=${encodeURIComponent(fmt.url)}&title=${encodeURIComponent(data.title)}&type=${data.type}`;

                row.innerHTML = `
                    <div class="format-title-wrap">
                        <span class="badge-res ${isHD ? 'hd' : ''}">${fmt.quality || 'Standard'}</span>
                        <span class="format-meta-text">${fmt.resolution || ''} • ${fileExt.toUpperCase()}</span>
                    </div>
                    <a href="${dlUrl}" class="btn-format-dl" download="${sanitizeTitle(data.title)}.${fileExt}">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                        </svg>
                        <span>Download .${fileExt.toUpperCase()}</span>
                    </a>
                `;
                formatsListContainer.appendChild(row);
            });
        }

        // Multi-Image Carousel rendering (for Carousel / Multi-Photo Pins)
        const carouselSection = document.getElementById('carouselSection');
        const carouselGrid = document.getElementById('carouselGrid');
        const carouselCount = document.getElementById('carouselCount');

        if (data.is_carousel && data.images && data.images.length > 1) {
            carouselCount.textContent = data.images.length;
            carouselGrid.innerHTML = '';

            data.images.forEach((img, idx) => {
                const card = document.createElement('div');
                card.className = 'carousel-card';
                const dlUrl = `/api/download?url=${encodeURIComponent(img.original_url)}&title=${encodeURIComponent(data.title + '_photo_' + (idx + 1))}&type=image`;
                const thumbUrl = (img.resolutions && img.resolutions[2]) ? img.resolutions[2].url : img.original_url;

                card.innerHTML = `
                    <div class="carousel-img-wrap">
                        <img class="carousel-thumb" src="${thumbUrl}" alt="Pin photo ${idx + 1}" loading="lazy">
                        <span class="carousel-photo-num">#${idx + 1}</span>
                    </div>
                    <div class="carousel-body">
                        <a href="${dlUrl}" class="carousel-btn-dl" download="${sanitizeTitle(data.title)}_photo_${idx + 1}.${img.ext}">
                            <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.5">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                <polyline points="7 10 12 15 17 10"></polyline>
                                <line x1="12" y1="15" x2="12" y2="3"></line>
                            </svg>
                            <span>Download HD</span>
                        </a>
                    </div>
                `;
                carouselGrid.appendChild(card);
            });

            carouselSection.style.display = 'block';
        } else if (carouselSection) {
            carouselSection.style.display = 'none';
        }

        // Audio extraction button
        if (bestFormat && data.type === 'video') {
            btnDownloadAudio.style.display = 'inline-flex';
            btnDownloadAudio.href = `/api/audio?url=${encodeURIComponent(bestFormat.url)}&title=${encodeURIComponent(data.title)}`;
            btnDownloadAudio.setAttribute('download', `${sanitizeTitle(data.title)}.mp3`);
        } else {
            btnDownloadAudio.style.display = 'none';
        }

        // Thumbnail button
        if (data.thumbnail) {
            btnDownloadThumbnail.style.display = 'inline-flex';
            btnDownloadThumbnail.href = `/api/download?url=${encodeURIComponent(data.thumbnail)}&title=${encodeURIComponent(data.title)}&type=image&ext=jpg`;
            btnDownloadThumbnail.setAttribute('download', `${sanitizeTitle(data.title)}_cover.jpg`);
        } else {
            btnDownloadThumbnail.style.display = 'none';
        }

        // Copy direct link button
        const linkLabel = data.type === 'image' ? 'Image Link' : 'Video Link';
        copyLinkText.textContent = `Copy ${linkLabel}`;

        btnCopyLink.onclick = () => {
            if (bestFormat && bestFormat.url) {
                navigator.clipboard.writeText(bestFormat.url).then(() => {
                    copyLinkText.textContent = 'Link Copied!';
                    showToast(`Direct ${linkLabel.toLowerCase()} copied to clipboard!`);
                    setTimeout(() => {
                        copyLinkText.textContent = `Copy ${linkLabel}`;
                    }, 2500);
                }).catch(() => {
                    showToast('Failed to copy link.');
                });
            }
        };

        // Reveal card and scroll smoothly
        resultSection.style.display = 'block';
        resultSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    const sanitizeTitle = (str) => {
        return (str || 'pinterest_video').replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 50);
    };

    // -------------------------------------------------------------------------
    // 7. Error & Toast Utilities
    // -------------------------------------------------------------------------
    const showError = (msg) => {
        errorMessage.textContent = msg;
        errorBox.style.display = 'flex';
        errorBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    const hideError = () => {
        errorBox.style.display = 'none';
    };

    const showToast = (message) => {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.classList.add('show');
        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    };

    // -------------------------------------------------------------------------
    // 8. Download History Storage in localStorage
    // -------------------------------------------------------------------------
    const HISTORY_KEY = 'pinfetch_recent_downloads';

    const saveToHistory = (item) => {
        try {
            let list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
            // Filter out duplicate if same ID
            list = list.filter(x => x.id !== item.id);
            list.unshift({
                id: item.id,
                title: item.title,
                thumbnail: item.thumbnail,
                url: item.webpage_url,
                date: new Date().toLocaleDateString()
            });
            // Keep max 6 items
            list = list.slice(0, 6);
            localStorage.setItem(HISTORY_KEY, JSON.stringify(list));
            renderHistory();
        } catch (e) {
            // localStorage might be disabled
        }
    };

    const renderHistory = () => {
        try {
            const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
            if (list.length === 0) {
                historySection.style.display = 'none';
                return;
            }

            historyGrid.innerHTML = '';
            list.forEach(item => {
                const card = document.createElement('div');
                card.className = 'history-card';
                card.innerHTML = `
                    <img class="history-thumb" src="${item.thumbnail || '/static/icons/favicon.svg'}" alt="Pin thumbnail" loading="lazy">
                    <div class="history-details">
                        <div class="history-title" title="${item.title}">${item.title || 'Pinterest Video'}</div>
                        <button class="history-btn-reload" data-url="${item.url}">Load Pin &rarr;</button>
                    </div>
                `;
                card.querySelector('.history-btn-reload').addEventListener('click', () => {
                    pinUrlInput.value = item.url;
                    updateInputState();
                    handleFetch();
                });
                historyGrid.appendChild(card);
            });

            historySection.style.display = 'block';
        } catch (e) {
            historySection.style.display = 'none';
        }
    };

    clearHistoryBtn.addEventListener('click', () => {
        localStorage.removeItem(HISTORY_KEY);
        renderHistory();
        showToast('Download history cleared');
    });

    renderHistory();
});
