// Stay-informed widget — handles expand → submit → success/error states.
// Stores emails via /api/subscribe (Vercel serverless → Upstash Redis).
(function () {
  function track(name, params) {
    if (typeof window.gtag === 'function') window.gtag('event', name, params || {});
  }

  function init() {
    const w = document.querySelector('.si-widget');
    if (!w) return;
    const pill = w.querySelector('.si-pill');
    const closeBtn = w.querySelector('.si-close');
    const form = w.querySelector('.si-form form');
    const input = w.querySelector('input[type="email"]');
    const submit = w.querySelector('.si-submit');
    const errorEl = w.querySelector('.si-error');
    const successCount = w.querySelector('.si-count');

    function expand() {
      if (w.classList.contains('expanded')) return;
      w.classList.add('expanded');
      setTimeout(() => input?.focus(), 50);
      track('email_modal_shown', { from_page: w.dataset.fromPage || 'unknown' });
    }
    function collapse() {
      w.classList.remove('expanded', 'success', 'error');
    }

    pill?.addEventListener('click', expand);
    closeBtn?.addEventListener('click', e => { e.stopPropagation(); collapse(); });

    form?.addEventListener('submit', async e => {
      e.preventDefault();
      const email = (input?.value || '').trim();
      if (!email) return;
      submit.disabled = true;
      submit.textContent = 'Saving…';
      w.classList.remove('error');
      try {
        const r = await fetch('/api/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        });
        const data = await r.json().catch(() => ({}));
        if (r.ok && data.ok) {
          if (successCount && data.total) successCount.textContent = data.total;
          w.classList.add('success');
          track('email_signup_submitted', { from_page: w.dataset.fromPage || 'unknown' });
        } else {
          throw new Error(data.error || 'unknown');
        }
      } catch (err) {
        const code = String(err.message || 'unknown');
        errorEl.textContent =
          code === 'invalid_email' ? "That email doesn't look right." :
          code === 'rate_limited'  ? "Slow down a sec — try again in a minute." :
                                     "Couldn't save right now. Try again in a moment.";
        w.classList.add('error');
      } finally {
        submit.disabled = false;
        submit.textContent = 'Subscribe';
      }
    });

    // Click-outside collapses (but not when clicking inside the widget)
    document.addEventListener('click', e => {
      if (!w.classList.contains('expanded')) return;
      if (!w.contains(e.target)) collapse();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
