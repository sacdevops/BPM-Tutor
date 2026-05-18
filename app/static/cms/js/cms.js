/* ============================================================
   BPM-Tutor CMS — Core JavaScript
   ============================================================ */

'use strict';

// ---- Sidebar Toggle ---- //
function toggleSidebar() {
  const sidebar = document.querySelector('.cms-sidebar');
  const main = document.querySelector('.cms-main');
  const overlay = document.getElementById('sidebarOverlay');
  if (!sidebar) return;

  const isTablet = window.innerWidth < 992;
  if (isTablet) {
    sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('visible');
  } else {
    sidebar.classList.toggle('collapsed');
    if (main) main.classList.toggle('expanded');
    try {
      localStorage.setItem('cmsSidebarCollapsed', sidebar.classList.contains('collapsed') ? '1' : '0');
    } catch (_) {}
  }
}

// Restore sidebar collapse state on large screens
(function () {
  try {
    if (window.innerWidth >= 992 && localStorage.getItem('cmsSidebarCollapsed') === '1') {
      const sidebar = document.querySelector('.cms-sidebar');
      const main = document.querySelector('.cms-main');
      if (sidebar) sidebar.classList.add('collapsed');
      if (main) main.classList.add('expanded');
    }
  } catch (_) {}
})();

// Close sidebar on overlay click
document.addEventListener('DOMContentLoaded', function () {
  const overlay = document.getElementById('sidebarOverlay');
  if (overlay) {
    overlay.addEventListener('click', function () {
      document.querySelector('.cms-sidebar')?.classList.remove('open');
      overlay.classList.remove('visible');
    });
  }
  // On resize: clean up state
  window.addEventListener('resize', function () {
    if (window.innerWidth >= 992) {
      document.querySelector('.cms-sidebar')?.classList.remove('open');
      document.getElementById('sidebarOverlay')?.classList.remove('visible');
    }
  });
});

// ---- Notifications (badge update) ---- //
async function refreshNotifCount() {
  try {
    const r = await fetch('/me/notifications/count', { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    const badges = document.querySelectorAll('.cms-notif-badge');
    badges.forEach(b => {
      b.textContent = data.count;
      b.style.display = data.count > 0 ? 'inline' : 'none';
    });
  } catch (_) {}
}

// Poll notifications every 60 seconds
if (document.querySelector('.cms-notif-badge')) {
  setInterval(refreshNotifCount, 60_000);
}

// ---- Flash message auto-dismiss ---- //
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.flash-container .alert').forEach(function (el) {
    setTimeout(function () {
      el.classList.remove('show');
      el.classList.add('fade');
      setTimeout(() => el.remove(), 500);
    }, 5000);
  });
});

// ---- Confirm delete helper used by multiple pages ---- //
function cmsConfirmDelete(formId, message) {
  if (confirm(message || 'Wirklich löschen?')) {
    document.getElementById(formId)?.submit();
  }
}
