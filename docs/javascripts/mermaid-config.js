// Mermaid configuration for dark/light mode support
document.addEventListener("DOMContentLoaded", function() {
    // Function to get current theme
    function getCurrentTheme() {
        return document.querySelector('[data-md-color-scheme]').getAttribute('data-md-color-scheme');
    }
    
    // Function to configure Mermaid theme
    function configureMermaid() {
        const theme = getCurrentTheme();
        const mermaidTheme = theme === 'slate' ? 'dark' : 'default';
        
        mermaid.initialize({
            startOnLoad: true,
            theme: mermaidTheme,
            themeVariables: {
                // Light mode colors
                primaryColor: theme === 'default' ? '#1976d2' : '#64b5f6',
                primaryTextColor: theme === 'default' ? '#000000' : '#ffffff',
                primaryBorderColor: theme === 'default' ? '#1976d2' : '#64b5f6',
                lineColor: theme === 'default' ? '#333333' : '#ffffff',
                secondaryColor: theme === 'default' ? '#e3f2fd' : '#1e1e1e',
                tertiaryColor: theme === 'default' ? '#f5f5f5' : '#2d2d2d',
                background: theme === 'default' ? '#ffffff' : '#1e1e1e',
                mainBkg: theme === 'default' ? '#ffffff' : '#1e1e1e',
                secondBkg: theme === 'default' ? '#f8f9fa' : '#2d2d2d',
                tertiaryBkg: theme === 'default' ? '#e9ecef' : '#404040'
            }
        });
        
        // Re-render all mermaid diagrams
        if (typeof mermaid !== 'undefined') {
            const mermaidElements = document.querySelectorAll('.mermaid');
            mermaidElements.forEach((element, index) => {
                element.removeAttribute('data-processed');
                element.innerHTML = element.getAttribute('data-original') || element.innerHTML;
                if (!element.getAttribute('data-original')) {
                    element.setAttribute('data-original', element.innerHTML);
                }
            });
            mermaid.init();
        }
    }
    
    // Initial configuration
    configureMermaid();
    
    // Listen for theme changes
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'data-md-color-scheme') {
                setTimeout(configureMermaid, 100); // Small delay to ensure theme is applied
            }
        });
    });
    
    // Start observing theme changes
    const target = document.querySelector('[data-md-color-scheme]');
    if (target) {
        observer.observe(target, { attributes: true });
    }
});