// Custom Mermaid initialization for Furo theme
document.addEventListener('DOMContentLoaded', function() {
    // Check if mermaid is loaded
    if (typeof mermaid !== 'undefined') {
        // Initialize mermaid with theme-aware configuration
        const currentTheme = document.body.dataset.theme || 'auto';
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const isDark = currentTheme === 'dark' || (currentTheme === 'auto' && prefersDark);

        mermaid.initialize({
            startOnLoad: true,
            theme: isDark ? 'dark' : 'default',
            themeCSS: isDark ? `
                .edgePath .path { stroke: #8bb9fe !important; }
                .edgeLabel { background-color: #1e1e2e !important; }
                .marker { fill: #8bb9fe !important; stroke: #8bb9fe !important; }
            ` : ''
        });

        // Re-render all mermaid diagrams
        mermaid.init();
    }

    // Listen for theme changes
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                // Theme changed, reinitialize mermaid
                if (typeof mermaid !== 'undefined') {
                    const newTheme = document.body.dataset.theme;
                    const isDark = newTheme === 'dark' || (newTheme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);

                    mermaid.initialize({
                        startOnLoad: false,
                        theme: isDark ? 'dark' : 'default'
                    });

                    // Re-render diagrams
                    document.querySelectorAll('.mermaid').forEach(function(element) {
                        element.removeAttribute('data-processed');
                    });
                    mermaid.init();
                }
            }
        });
    });

    observer.observe(document.body, {
        attributes: true,
        attributeFilter: ['data-theme']
    });
});
