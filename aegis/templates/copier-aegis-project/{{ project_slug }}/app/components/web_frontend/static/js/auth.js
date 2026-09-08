// Auth plumbing for the web frontend.
//
// Session auth lives in the `aegis_session` HttpOnly cookie the server sets
// during /login and /register. The browser attaches it automatically on
// same-origin requests, so this file is mostly about handling the
// session-expired case uniformly:
//
// 1. `fetchAuth(path, opts)` - fetch() wrapper that sends credentials,
//    refreshes once on 401, and bounces to /login (or /verify-pending on an
//    email-not-verified 403).
// 2. Global htmx hook - mirrors the same 401/403 handling for hx-get/post.
// 3. The auth pages' Alpine components, registered at the bottom so the
//    pages themselves carry no inline scripts.

function _loginUrlWithNext() {
  // Preserve the current page path as ?next= so a successful sign-in returns
  // the user to where they were. Mirrors the server-side gate.
  const here = window.location.pathname;
  if (!here || here === '/login' || !here.startsWith('/')) return '/login';
  return '/login?next=' + encodeURIComponent(here);
}

// Single-flight refresh. The server rotates refresh tokens with reuse
// detection: replaying an already-revoked token revokes the whole family.
// A page can fire many authenticated requests in parallel, so when the
// access token expires they all 401 together - each calling /refresh
// independently would have call #2 replay the token call #1 just rotated
// and drop the session. One shared in-flight promise; everyone awaits it.
let _refreshInFlight = null;
function _tryRefresh() {
  if (!_refreshInFlight) {
    _refreshInFlight = fetch('/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'same-origin',
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        _refreshInFlight = null;
      });
  }
  return _refreshInFlight;
}

async function fetchAuth(path, opts = {}) {
  let resp = await fetch(path, { ...opts, credentials: 'same-origin' });
  if (resp.status === 401) {
    // Access token expired - try the refresh cookie before giving up. One
    // retry only; a second 401 means the refresh failed or the new session
    // is also rejected, so bounce to login.
    if (await _tryRefresh()) {
      resp = await fetch(path, { ...opts, credentials: 'same-origin' });
    }
  }
  if (resp.status === 401) {
    window.location = _loginUrlWithNext();
    return;
  }
  if (resp.status === 403) {
    // Peek at the body without consuming it, so callers can still read it if
    // they want to handle the error themselves.
    try {
      const clone = resp.clone();
      const body = await clone.json();
      if (body && body.detail === 'email_not_verified') {
        window.location = '/verify-pending';
        return;
      }
    } catch (_) {
      /* non-JSON body - fall through */
    }
  }
  return resp;
}

// If htmx gets a 401 from a protected endpoint, kick to /login. If it gets a
// 403 with `email_not_verified`, kick to /verify-pending so the user can
// resend the verification email.
document.addEventListener('htmx:responseError', (evt) => {
  const xhr = evt.detail.xhr;
  if (xhr.status === 401) {
    // Same refresh-first flow as fetchAuth. On success reload the page rather
    // than replaying the htmx request - the swap target may be mid-transition,
    // and a full reload re-renders the current URL with the fresh session.
    _tryRefresh().then((ok) => {
      if (ok) {
        window.location.reload();
      } else {
        window.location = _loginUrlWithNext();
      }
    });
    return;
  }
  if (xhr.status === 403) {
    try {
      const body = JSON.parse(xhr.responseText || '{}');
      if (body.detail === 'email_not_verified') {
        window.location = '/verify-pending';
      }
    } catch (_) {
      /* non-JSON body - leave as-is */
    }
  }
});

window.fetchAuth = fetchAuth;

// Auth page components. Each page's x-data names one of these; Alpine
// calls init() itself where a component defines one.
document.addEventListener('alpine:init', () => {
  Alpine.data('loginForm', () => ({
      loading: false,
      error: '',
      success: '',

      init() {
        // Banner text is driven by the query string: the server-side handlers
        // redirect back here with a reason rather than rendering the message
        // themselves, so a refresh never re-posts the form.
        const p = new URLSearchParams(window.location.search);
        if (p.get('registered')) this.success = 'Account created. Check your email to verify it.';
        if (p.get('verified')) this.success = 'Email verified. Sign in to continue.';
        if (p.get('reset')) this.success = 'Password updated. Sign in with your new password.';

        const err = p.get('error');
        if (err === 'invalid') {
          this.error = 'Incorrect email or password.';
        } else if (err === 'locked') {
          this.error = 'Account temporarily locked after too many failed attempts. Try again shortly.';
        }
      },
  }));

  Alpine.data('registerForm', () => ({
      loading: false,
      error: '',

      init() {
        const p = new URLSearchParams(window.location.search);
        const err = p.get('error');
        if (err === 'exists') {
          this.error = 'That email is already registered. Try signing in instead.';
        } else if (err === 'closed') {
          this.error = 'Signups are closed right now.';
        } else if (err === 'invalid') {
          this.error = 'Check the details and try again.';
        }
      },
  }));

  Alpine.data('forgotForm', () => ({
      loading: false,
      error: '',
      sent: '',

      async submit() {
        if (this.loading) return;
        this.loading = true;
        this.error = '';
        this.sent = '';
        const email = this.$el.querySelector('input[name=email]').value;
        try {
          await fetch('/api/v1/auth/password-reset/request', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email }),
          });
        } catch (_) {
          this.loading = false;
          this.error = 'Could not reach the server. Try again.';
          return;
        }
        this.loading = false;
        // Always the same answer, whether or not the address exists: telling
        // the difference would turn this form into an account-enumeration
        // oracle. The API is deliberately silent about it too.
        this.sent = 'If that email has an account, a reset link is on its way.';
      },
  }));

  Alpine.data('resetForm', () => ({
      loading: false,
      error: '',

      async submit() {
        if (this.loading) return;
        this.loading = true;
        this.error = '';
        const token = new URLSearchParams(window.location.search).get('token') || '';
        if (!token) {
          this.loading = false;
          this.error = 'This reset link is incomplete. Request a new one.';
          return;
        }
        const password = this.$el.querySelector('input[name=password]').value;
        let resp;
        try {
          resp = await fetch('/api/v1/auth/password-reset/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token, new_password: password }),
          });
        } catch (_) {
          this.loading = false;
          this.error = 'Could not reach the server. Try again.';
          return;
        }
        if (resp.ok) {
          // Land on /login with the banner rather than rendering "done" here:
          // the next thing to do is sign in, so send them there.
          window.location = '/login?reset=1';
          return;
        }
        this.loading = false;
        this.error = 'That reset link has expired or already been used. Request a new one.';
      },
  }));

  Alpine.data('verifyEmail', () => ({
      state: 'working',
      error: '',

      async verify() {
        const token = new URLSearchParams(window.location.search).get('token') || '';
        if (!token) {
          this.state = 'failed';
          this.error = 'This verification link is incomplete.';
          return;
        }
        let resp;
        try {
          resp = await fetch('/api/v1/auth/verify-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: token }),
          });
        } catch (_) {
          this.state = 'failed';
          this.error = 'Could not reach the server. Try the link again.';
          return;
        }
        if (resp.ok) {
          this.state = 'ok';
          return;
        }
        this.state = 'failed';
        this.error = 'This link has expired or already been used.';
      },
  }));

  Alpine.data('verifyPending', () => ({
      loading: false,
      error: '',
      sent: '',

      async resend() {
        this.loading = true;
        this.error = '';
        this.sent = '';
        let resp;
        try {
          resp = await fetch('/api/v1/auth/resend-verification', {
            method: 'POST',
            credentials: 'same-origin',
          });
        } catch (_) {
          this.loading = false;
          this.error = 'Could not reach the server. Try again.';
          return;
        }
        this.loading = false;
        if (resp.ok) {
          this.sent = 'Sent. Check your inbox.';
          return;
        }
        this.error = 'Could not send right now. Try again shortly.';
      },
  }));
});
