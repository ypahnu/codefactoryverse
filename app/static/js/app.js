// CodeFactory App JS

document.addEventListener('DOMContentLoaded', () => {
  // Toggle full prompt
  document.addEventListener('click', (e) => {
    if (e.target.closest('.btn-expand')) {
      const btn = e.target.closest('.btn-expand');
      const targetId = btn.dataset.target;
      const el = document.getElementById(targetId);
      if (el) {
        el.classList.toggle('visible');
        const isVisible = el.classList.contains('visible');
        btn.innerHTML = isVisible ? '− hide full prompt' : '+ show full prompt';
      }
    }
  });

  // Status changer
  const statusSelects = document.querySelectorAll('.status-changer');
  statusSelects.forEach(sel => {
    sel.addEventListener('change', async (e) => {
      const taskId = e.target.dataset.taskId;
      const teamSlug = e.target.dataset.team;
      const projectSlug = e.target.dataset.project;
      const newStatus = e.target.value;
      try {
        const res = await fetch(`/projects/team/${teamSlug}/${projectSlug}/tasks/${taskId}/status`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest' },
          body: `status=${newStatus}`
        });
        const data = await res.json();
        if (data.success) {
          location.reload();
        }
      } catch (err) {
        console.error(err);
      }
    });
  });

  // Agent clone form skills toggle
  const skillToggles = document.querySelectorAll('.skill-toggle');
  skillToggles.forEach(toggle => {
    toggle.addEventListener('change', () => {
      const count = document.querySelectorAll('.skill-toggle:checked').length;
      const counter = document.getElementById('skills-count');
      if (counter) counter.textContent = count;
    });
  });

  // Select all skills
  const selectAll = document.getElementById('select-all-skills');
  if (selectAll) {
    selectAll.addEventListener('click', (e) => {
      e.preventDefault();
      document.querySelectorAll('.skill-toggle').forEach(cb => cb.checked = true);
      const counter = document.getElementById('skills-count');
      if (counter) counter.textContent = document.querySelectorAll('.skill-toggle').length;
    });
  }

  // Auto-resize textarea
  document.querySelectorAll('textarea').forEach(ta => {
    ta.addEventListener('input', () => {
      ta.style.height = 'auto';
      ta.style.height = ta.scrollHeight + 'px';
    });
  });
});

// Clone agent modal helpers
function openCloneModal() {
  const modal = new bootstrap.Modal(document.getElementById('cloneAgentModal'));
  modal.show();
}

function showFullPrompt(id) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('visible');
}
