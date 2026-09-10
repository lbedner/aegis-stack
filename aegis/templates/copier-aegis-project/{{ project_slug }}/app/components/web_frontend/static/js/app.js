/* htmx lifecycle hooks and the toast component.

   Fragments carry no inline scripts, so nothing here re-executes swapped
   <script> tags. Behaviour that needs JS is registered once, on this
   file's load, and keyed off DOM events. */

// Toasts. A route sets `HX-Trigger: {"toast": {"text", "tone"}}` (see
// with_toast() in rendering.py); htmx raises a `toast` DOM event; the
// region in base.html pushes it here.
document.addEventListener('alpine:init', () => {
  Alpine.data('toasts', () => ({
    items: [],
    _seq: 0,
    push(detail) {
      const id = ++this._seq;
      const tone = detail.tone || 'ok';
      this.items.push({ id, text: detail.text, tone });
      // Errors linger; confirmations get out of the way.
      setTimeout(() => this.dismiss(id), tone === 'error' ? 8000 : 4000);
    },
    dismiss(id) {
      this.items = this.items.filter((item) => item.id !== id);
    },
  }));
});

function toast(text, tone) {
  window.dispatchEvent(new CustomEvent('toast', { detail: { text, tone } }));
}

// Server and network failures never swap (see the htmx-config
// responseHandling rules in base.html); they surface here as one error
// toast instead of a silently unchanged page.
document.body.addEventListener('htmx:responseError', (event) => {
  toast(`Request failed (${event.detail.xhr.status})`, 'error');
});
document.body.addEventListener('htmx:sendError', () => {
  toast('Network error. Check the connection and try again.', 'error');
});

// The one modal. Any swap into #dialog-body opens the native <dialog>;
// closing it clears the body (see the dialog macro in macros/layout.html).
document.body.addEventListener('htmx:afterSwap', (event) => {
  if (event.detail.target.id === 'dialog-body') {
    const dialog = document.getElementById('dialog');
    if (dialog && !dialog.open) dialog.showModal();
  }
});
// Sent as HX-Trigger-After-Settle (rendering.close_dialog), so it lands
// after the response's own swap has finished with #dialog-body.
document.body.addEventListener('dialog:close', () => {
  const dialog = document.getElementById('dialog');
  if (dialog && dialog.open) dialog.close();
});
