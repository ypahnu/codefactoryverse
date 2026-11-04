// @ Mention Autocomplete - Generic for any bot, not just Joana
// Shows list of agents in current task, agents in project, and people (team members)
// If already in task -> answers automatically, if not -> cloned/added to task/channel

document.addEventListener('DOMContentLoaded', () => {
  const textarea = document.getElementById('chat-content-input');
  const dropdown = document.getElementById('mention-dropdown');
  const mentionDataEl = document.getElementById('mention-data');

  if (!textarea || !dropdown || !mentionDataEl) return;

  let mentionData;
  try {
    mentionData = JSON.parse(mentionDataEl.textContent);
  } catch (e) {
    console.warn('Failed to parse mention data', e);
    return;
  }

  let activeIndex = -1;
  let filtered = { inTask: [], inProject: [], people: [] };
  let atStart = -1;
  let currentQuery = '';

  function getAtQuery() {
    const cursor = textarea.selectionStart;
    const textBefore = textarea.value.substring(0, cursor);
    const atMatch = textBefore.match(/@([\w\- ]*)$/);
    if (!atMatch) return null;
    const atPos = textBefore.lastIndexOf('@');
    // Check if @ is at start or preceded by space/newline
    if (atPos > 0) {
      const charBefore = textBefore[atPos - 1];
      if (/[A-Za-z0-9]/.test(charBefore)) return null; // @ in middle of word, ignore
    }
    return {
      query: atMatch[1],
      start: atPos,
      end: cursor
    };
  }

  function filterCandidates(query) {
    const q = query.toLowerCase().trim();
    const filterFn = (item) => {
      if (!q) return true;
      const name = (item.name || item.username || '').toLowerCase();
      const role = (item.role || '').toLowerCase();
      const display = (item.display_name || '').toLowerCase();
      return name.includes(q) || role.includes(q) || display.includes(q);
    };

    filtered.inTask = mentionData.inTask.filter(filterFn);
    filtered.inProject = mentionData.inProject.filter(filterFn);
    filtered.people = mentionData.people.filter(filterFn);

    // Limit each section to 5 for UI
    filtered.inTask = filtered.inTask.slice(0, 5);
    filtered.inProject = filtered.inProject.slice(0, 5);
    filtered.people = filtered.people.slice(0, 5);
  }

  function renderDropdown() {
    const total = filtered.inTask.length + filtered.inProject.length + filtered.people.length;
    if (total === 0) {
      dropdown.classList.add('d-none');
      return;
    }

    let html = '';
    let idx = 0;

    function renderSection(title, items, icon, badgeClass, desc) {
      if (items.length === 0) return '';
      let sectionHtml = `<div class="mention-section">${icon} ${title} (${items.length}) <small style="font-size:9px;">${desc}</small></div>`;
      items.forEach(item => {
        const isActive = idx === activeIndex;
        const name = item.name || item.username || 'Unknown';
        const role = item.role || item.display_name || '';
        const avatar = item.avatar || name[0].toUpperCase();
        const inTaskBadge = item.in_task ? '<span class="badge bg-success" style="font-size:8px;">in task - will answer</span>' : (item.type === 'agent' ? '<span class="badge bg-secondary" style="font-size:8px;">in project - will be cloned</span>' : '<span class="badge bg-info" style="font-size:8px;">will be added to task</span>');
        sectionHtml += `
          <div class="mention-item ${isActive ? 'active' : ''}" data-index="${idx}" data-name="${name}" data-type="${item.type}" data-id="${item.id}">
            <div class="mention-avatar" style="background: ${item.type === 'user' ? '#0ea5e9' : '#6366f1'}">${avatar}</div>
            <div class="flex-grow-1">
              <div class="small fw-bold" style="font-size:12px;">@${name} <span class="text-dim" style="font-size:10px;">${role ? '- '+role : ''}</span></div>
              <div class="small text-dim" style="font-size:10px;">${inTaskBadge}</div>
            </div>
          </div>
        `;
        idx++;
      });
      return sectionHtml;
    }

    html += renderSection('Agents in this task', filtered.inTask, '🤖', 'bg-success', 'already in task, will answer');
    html += renderSection('Agents in project', filtered.inProject, '📦', 'bg-secondary', 'not in task, will be cloned + added');
    html += renderSection('People', filtered.people, '👤', 'bg-info', 'team members, will be added to channel');

    if (total === 0) {
      html = `<div class="p-2 small text-dim">No matches for "@${currentQuery}"</div>`;
    }

    dropdown.innerHTML = html;
    dropdown.classList.remove('d-none');

    // Attach click handlers
    dropdown.querySelectorAll('.mention-item').forEach(el => {
      el.addEventListener('click', () => {
        const name = el.dataset.name;
        selectMention(name);
      });
    });

    // Update active class
    dropdown.querySelectorAll('.mention-item').forEach((el, i) => {
      if (i === activeIndex) el.classList.add('active');
      else el.classList.remove('active');
    });
  }

  function selectMention(name) {
    const atQuery = getAtQuery();
    if (!atQuery) return;

    const before = textarea.value.substring(0, atQuery.start);
    const after = textarea.value.substring(atQuery.end);
    const insertion = `@${name} `;

    textarea.value = before + insertion + after;
    textarea.selectionStart = textarea.selectionEnd = before.length + insertion.length;
    textarea.focus();

    dropdown.classList.add('d-none');
    activeIndex = -1;
  }

  function handleInput() {
    const atQuery = getAtQuery();
    if (!atQuery) {
      dropdown.classList.add('d-none');
      activeIndex = -1;
      return;
    }

    currentQuery = atQuery.query;
    atStart = atQuery.start;

    filterCandidates(currentQuery);
    activeIndex = 0; // first item active
    renderDropdown();
  }

  function handleKeydown(e) {
    if (dropdown.classList.contains('d-none')) return;

    const items = dropdown.querySelectorAll('.mention-item');
    if (items.length === 0) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIndex = (activeIndex + 1) % items.length;
      renderDropdown();
      items[activeIndex]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIndex = (activeIndex - 1 + items.length) % items.length;
      renderDropdown();
      items[activeIndex]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      if (activeIndex >= 0 && activeIndex < items.length) {
        e.preventDefault();
        const selected = items[activeIndex];
        const name = selected.dataset.name;
        selectMention(name);
      }
    } else if (e.key === 'Escape') {
      dropdown.classList.add('d-none');
      activeIndex = -1;
    }
  }

  // Events
  textarea.addEventListener('input', handleInput);
  textarea.addEventListener('click', handleInput);
  textarea.addEventListener('keyup', (e) => {
    if (['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(e.key)) return;
    handleInput();
  });
  textarea.addEventListener('keydown', handleKeydown);

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (!dropdown.contains(e.target) && e.target !== textarea) {
      dropdown.classList.add('d-none');
    }
  });

  console.log('[Mention] Autocomplete initialized', mentionData);
});
